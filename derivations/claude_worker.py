#!/usr/bin/env python3
"""Long-running Claude session worker.

Spawns one `claude -p --input-format stream-json --output-format stream-json`
subprocess. The harness loads ONCE; subsequent messages reuse the cached system
prompt + CLAUDE.md + memory (verified: cache_create drops from ~6K -> ~16 tokens
on turn 2, with cache_read at ~19K).

API:
    w = ClaudeWorker(model="sonnet", system_prompt=None)
    response_text = w.send(user_text)
    # ... many calls ...
    w.close()

Or as a context manager:
    with ClaudeWorker() as w:
        for target in targets:
            graph_json = w.send(prompt_for(target))

The pool wrapper (ClaudeWorkerPool) round-robins K workers, restarts dead ones,
and rotates a worker when its turn count exceeds a budget (context window cap).

This file is intentionally dependency-free beyond stdlib — designed to be
importable from any pipeline component without pulling in heavy modules.
"""
from __future__ import annotations
import json
import os
import queue
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")

# Sonnet/Opus context window (Sonnet 4.6 is 200K; Opus 4.7 same). Keep a buffer.
CONTEXT_BUDGET_TOKENS = 200_000
DEFAULT_ROTATION_SATURATION = 0.85  # rotate when cumulative context >= 85%


class WorkerError(RuntimeError):
    pass


from llm_cli import QuotaExhaustedError  # noqa: E402,F401 -- re-exported for backward compat

__all__ = ["WorkerError", "QuotaExhaustedError", "ClaudeWorker", "ClaudeWorkerPool"]


class ClaudeWorker:
    """One long-running claude -p session.

    Not thread-safe by itself; the pool serializes access per worker.
    """

    def __init__(self, model: str = "sonnet", system_prompt: str | None = None,
                 rotate_after_turns: int = 100,  # hard cap; saturation usually triggers first
                 rotation_saturation: float = DEFAULT_ROTATION_SATURATION,
                 startup_timeout_s: float = 30.0,
                 turn_timeout_s: float = 600.0,
                 extra_args: list | None = None,
                 worker_id: str | None = None,
                 quota_patterns: list | None = None):
        self.model = model
        self.system_prompt = system_prompt
        self.rotate_after_turns = rotate_after_turns
        self.rotation_saturation = rotation_saturation
        self.turn_timeout_s = turn_timeout_s
        self.startup_timeout_s = startup_timeout_s
        self.extra_args = list(extra_args or [])
        self.quota_patterns = list(quota_patterns or [
            "You've hit your limit", "Rate limit exceeded",
            "rate_limit_exceeded", "Anthropic API quota exceeded",
        ])
        self.worker_id = worker_id or f"w_{os.getpid()}_{id(self) & 0xffff:04x}"

        self.proc: subprocess.Popen | None = None
        self.turn_count = 0
        self.session_id: str | None = None
        self.last_saturation: float = 0.0
        self.peak_saturation: float = 0.0
        # Running counter of conversation content (user input + assistant output)
        # added to the session so far. More reliable saturation proxy than the
        # raw cache_read on tool-using turns, which double-counts due to the
        # model's internal sub-iterations.
        self._cumulative_content_tokens: int = 0
        # Approximate fixed overhead per turn (system prompt + memory + cwd info
        # that ride alongside the conversation in every turn's cache_read).
        self._fixed_context_baseline: int = 20_000
        self._reader_thread: threading.Thread | None = None
        self._lines_q: queue.Queue = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()

        self.spawn()

    # ── lifecycle ─────────────────────────────────────────────────
    def spawn(self) -> None:
        cmd = [
            CLAUDE_BIN, "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--model", self.model,
            "--no-session-persistence",
            "--permission-mode", "bypassPermissions",
        ]
        if self.system_prompt is not None:
            cmd += ["--system-prompt", self.system_prompt]
        cmd += self.extra_args

        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self._lines_q = queue.Queue()
        self._reader_thread = threading.Thread(
            target=self._reader, name=f"{self.worker_id}-reader", daemon=True)
        self._reader_thread.start()
        # init event is emitted on first send. We don't block for it here --
        # send() drains any pre-message events (including init) before returning.

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.send_signal(signal.SIGTERM)
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ── reader thread ────────────────────────────────────────────
    def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if line:
                self._lines_q.put(line)
        # process closed stdout
        self._lines_q.put(None)

    def _parse_line(self, line: str | None) -> dict | None:
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    # ── one round-trip ───────────────────────────────────────────
    def send(self, user_text: str) -> dict:
        """Send a user message, wait for the result event, return:
            {"text": "<assistant text>", "result": <result event dict>}
        Raises WorkerError on timeout, dead process, or unexpected protocol.
        """
        if self._closed:
            raise WorkerError(f"{self.worker_id} is closed")
        if self.proc.poll() is not None:
            raise WorkerError(f"{self.worker_id} died before turn: rc={self.proc.returncode}")

        msg = {"type": "user", "message": {"role": "user", "content": user_text}}
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise WorkerError(f"{self.worker_id} pipe broken on send: {e}")

        assistant_text_parts: list = []
        result_event: dict | None = None
        deadline = time.time() + self.turn_timeout_s

        while time.time() < deadline:
            try:
                line = self._lines_q.get(timeout=1.0)
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise WorkerError(f"{self.worker_id} died mid-turn: rc={self.proc.returncode}")
                continue
            if line is None:
                raise WorkerError(f"{self.worker_id} closed stdout mid-turn")
            # Quota detection: subscription-quota messages appear inline in the
            # assistant text or in error events, not as exceptions.
            for pat in self.quota_patterns:
                if pat in line:
                    raise QuotaExhaustedError(
                        f"{self.worker_id} hit quota: pattern={pat!r}")
            ev = self._parse_line(line)
            if ev is None:
                continue
            t = ev.get("type")
            if t == "system" and ev.get("subtype") == "init":
                if self.session_id is None:
                    self.session_id = ev.get("session_id")
                continue
            if t == "assistant":
                for c in ev.get("message", {}).get("content", []):
                    if c.get("type") == "text":
                        assistant_text_parts.append(c.get("text", ""))
            elif t == "result":
                result_event = ev
                break
            elif t == "user":
                # echo of our input under --replay-user-messages; ignore
                continue
            # other event types (rate_limit_event, tool_use, etc.) pass silently

        if result_event is None:
            raise WorkerError(f"{self.worker_id} turn timed out after {self.turn_timeout_s}s")

        self.turn_count += 1

        # Saturation: estimate how much of the 200K context window is occupied
        # by the running conversation. Use a running counter of (user input +
        # assistant output) added per turn, plus a fixed baseline for the system
        # prompt + memory. The raw cache_read/cache_creation fields can inflate
        # well past 200K on tool-using turns because the model issues multiple
        # internal iterations each re-reading the cached prefix; that doesn't
        # mean the context window is overflowing.
        usage = result_event.get("usage", {}) or {}
        new_content = (
            (usage.get("input_tokens", 0) or 0) +
            (usage.get("output_tokens", 0) or 0)
        )
        self._cumulative_content_tokens += new_content
        context_tokens = self._cumulative_content_tokens + self._fixed_context_baseline
        saturation = context_tokens / CONTEXT_BUDGET_TOKENS
        self.last_saturation = saturation
        if saturation > self.peak_saturation:
            self.peak_saturation = saturation

        needs_rotation = (
            saturation >= self.rotation_saturation
            or self.turn_count >= self.rotate_after_turns
        )

        return {
            "text": "".join(assistant_text_parts),
            "result": result_event,
            "needs_rotation": needs_rotation,
            "saturation": saturation,
            "turn_count": self.turn_count,
        }


class ClaudeWorkerPool:
    """Pool of long-running ClaudeWorker sessions.

    Round-robins requests across K workers. Rotates a worker when its
    `needs_rotation` flag fires (replaced with a fresh session). Restarts
    a worker on WorkerError.

    QuotaExhaustedError is NOT caught here — it propagates to the caller so
    the runner can write a PAUSED_QUOTA state and exit cleanly. Restarting
    a worker won't help when the subscription is exhausted.

    Thread-safe submission via a single queue; worker access is serialized
    per-worker by holding the worker's lock during each send.
    """

    def __init__(self, size: int = 4, **worker_kwargs):
        self.size = size
        self.worker_kwargs = worker_kwargs
        self._workers: list = []
        self._next = 0
        self._lock = threading.Lock()
        for i in range(size):
            self._workers.append(ClaudeWorker(worker_id=f"pool_{i}", **worker_kwargs))

    def _pick(self) -> ClaudeWorker:
        with self._lock:
            w = self._workers[self._next]
            self._next = (self._next + 1) % self.size
        return w

    def submit(self, user_text: str) -> dict:
        last_err = None
        for attempt in range(self.size):
            w = self._pick()
            with w._lock:
                try:
                    out = w.send(user_text)
                    if out.get("needs_rotation"):
                        self._replace(w)
                    return out
                except QuotaExhaustedError:
                    # Propagate up immediately; cycling workers won't help.
                    raise
                except WorkerError as e:
                    last_err = e
                    self._replace(w)
                    continue
        raise WorkerError(f"all {self.size} workers failed; last={last_err}")

    def _replace(self, w: ClaudeWorker) -> None:
        # Caller must hold w._lock
        idx = None
        with self._lock:
            for i, existing in enumerate(self._workers):
                if existing is w:
                    idx = i
                    break
        if idx is None:
            return
        try:
            w.close()
        except Exception:
            pass
        fresh = ClaudeWorker(worker_id=f"pool_{idx}", **self.worker_kwargs)
        with self._lock:
            self._workers[idx] = fresh

    def close(self) -> None:
        for w in self._workers:
            try:
                w.close()
            except Exception:
                pass


# ── CLI smoke test ───────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--turns", type=int, default=3)
    args = ap.parse_args()

    with ClaudeWorker(model=args.model) as w:
        print(f"[smoke] worker started: session={w.session_id}", file=sys.stderr)
        for i in range(args.turns):
            r = w.send(f"Round {i+1}. Reply with just the single word 'ACK{i+1}'.")
            ru = r["result"]
            usage = ru.get("usage", {})
            print(f"[smoke] turn {i+1}: text='{r['text']}' "
                  f"cost=${ru.get('total_cost_usd', 0):.4f} "
                  f"sat={r['saturation']*100:.1f}%  "
                  f"rotate={r['needs_rotation']}  "
                  f"cache_create={usage.get('cache_creation_input_tokens', 0)} "
                  f"cache_read={usage.get('cache_read_input_tokens', 0)}", file=sys.stderr)
