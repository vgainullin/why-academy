#!/usr/bin/env python3
"""Small LLM CLI adapter for pipeline prompts.

Claude remains the default engine. Codex is supported both as a one-shot
`codex exec` backend and as a resumable worker pool that keeps one Codex thread
warm across multiple turns in a target-local evolution loop.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")

DEFAULT_QUOTA_PATTERNS = [
    "You've hit your limit",
    "Rate limit exceeded",
    "rate_limit_exceeded",
    "Anthropic API quota exceeded",
]

CONTEXT_BUDGET_TOKENS = 200_000
DEFAULT_ROTATION_SATURATION = 0.85
CODEX_MINIMAL_FEATURES = [
    "plugins",
    "memories",
    "shell_tool",
    "unified_exec",
    "tool_search",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "multi_agent",
    "workspace_dependencies",
    "apps",
    "in_app_browser",
]


class LLMEngineError(RuntimeError):
    pass


class QuotaExhaustedError(LLMEngineError):
    pass


class CodexWorkerError(LLMEngineError):
    pass


def step_engine(cfg: dict, step: str, default: str = "claude") -> str:
    """Return configured engine for a pipeline step."""
    env_name = f"{step.upper()}_ENGINE"
    if os.environ.get(env_name):
        return os.environ[env_name].strip().lower()
    return str(cfg.get("engines", {}).get(step, default)).strip().lower()


def _check_quota(text: str, patterns: list[str] | None = None) -> None:
    for pat in patterns or DEFAULT_QUOTA_PATTERNS:
        if pat and pat in text:
            raise QuotaExhaustedError(f"quota pattern matched: {pat!r}")


def _parse_jsonl_events(text: str) -> list[dict]:
    events: list[dict] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def tail(text: str, limit: int) -> str:
    return (text or "")[-limit:]


def _codex_base_cmd(cwd_path: Path, sandbox: str) -> list[str]:
    return [
        CODEX_BIN,
        "exec",
        "-C",
        str(cwd_path),
        "--sandbox",
        sandbox,
    ]


def _append_codex_common_args(cmd: list[str], model: str | None) -> list[str]:
    if _env_flag("CODEX_MINIMAL", True):
        cmd += ["--ignore-user-config", "--ignore-rules"]
        disable_raw = os.environ.get("CODEX_MINIMAL_DISABLES")
        disables = (
            [s.strip() for s in disable_raw.split(",") if s.strip()]
            if disable_raw
            else CODEX_MINIMAL_FEATURES
        )
        for feature in disables:
            cmd += ["--disable", feature]
    if model:
        cmd += ["--model", model]
    profile = os.environ.get("CODEX_PROFILE")
    if profile:
        cmd += ["--profile", profile]
    return cmd


def run_prompt(
    prompt: str,
    *,
    engine: str = "claude",
    model: str | None = None,
    budget: str | None = None,
    timeout_s: int | float | str | None = None,
    cwd: Path | str | None = None,
    quota_patterns: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a prompt through the selected CLI and return a CompletedProcess.

    For Codex, stdout is normalized to the final assistant message when
    `codex exec --output-last-message` succeeds. stderr still contains CLI
    diagnostics, which callers can include in logs.
    """
    engine = (engine or "claude").strip().lower()
    cwd_path = Path(cwd or PROJECT_ROOT)
    timeout = int(float(timeout_s)) if timeout_s else None

    if engine == "claude":
        cmd = [
            CLAUDE_BIN,
            "-p",
            prompt,
            "--output-format",
            "text",
            "--permission-mode",
            "bypassPermissions",
            "--no-session-persistence",
        ]
        if model:
            cmd += ["--model", model]
        if budget:
            cmd += ["--max-budget-usd", str(budget)]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                timeout=(timeout + 30) if timeout else None,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMEngineError(f"{engine} timed out after {timeout_s}s") from e
        _check_quota((result.stdout or "") + (result.stderr or ""), quota_patterns)
        return result

    if engine == "codex":
        sandbox = os.environ.get("CODEX_SANDBOX", "workspace-write")
        if sandbox in ("seatbelt", "sandbox"):
            sandbox = "workspace-write"
        with tempfile.NamedTemporaryFile(
            prefix="codex-last-message-", suffix=".txt", delete=False
        ) as tmp:
            last_message_path = Path(tmp.name)
        cmd = _append_codex_common_args(_codex_base_cmd(cwd_path, sandbox), model)
        cmd += ["--ephemeral", "--output-last-message", str(last_message_path)]
        cmd.append("-")
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                timeout=(timeout + 30) if timeout else None,
            )
            last_message = ""
            if last_message_path.exists():
                last_message = last_message_path.read_text()
            stdout = last_message if last_message.strip() else result.stdout
            normalized = subprocess.CompletedProcess(
                args=result.args,
                returncode=result.returncode,
                stdout=stdout,
                stderr=result.stderr,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMEngineError(f"{engine} timed out after {timeout_s}s") from e
        finally:
            try:
                last_message_path.unlink(missing_ok=True)
            except Exception:
                pass
        _check_quota((normalized.stdout or "") + (normalized.stderr or ""), quota_patterns)
        return normalized

    if engine == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise LLMEngineError("OPENROUTER_API_KEY not set")
        selected_model = model or os.environ.get("OPENROUTER_MODEL")
        if not selected_model:
            raise LLMEngineError("OpenRouter model not set; pass --model or set OPENROUTER_MODEL")
        base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        payload = json.dumps({
            "model": selected_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if os.environ.get("OPENROUTER_SITE_URL"):
            headers["HTTP-Referer"] = os.environ["OPENROUTER_SITE_URL"]
        if os.environ.get("OPENROUTER_APP_NAME"):
            headers["X-Title"] = os.environ["OPENROUTER_APP_NAME"]
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return subprocess.CompletedProcess(
                args=["openrouter", selected_model],
                returncode=1,
                stdout=body,
                stderr=f"HTTPError {e.code}: {tail(body, 2000)}",
            )
        except Exception as e:
            return subprocess.CompletedProcess(
                args=["openrouter", selected_model],
                returncode=1,
                stdout="",
                stderr=f"{type(e).__name__}: {e}",
            )
        try:
            data = json.loads(body)
            raw = data["choices"][0]["message"].get("content") or ""
        except Exception as e:
            return subprocess.CompletedProcess(
                args=["openrouter", selected_model],
                returncode=1,
                stdout=body,
                stderr=f"{type(e).__name__}: {e}; body_tail={tail(body, 2000)}",
            )
        _check_quota(raw, quota_patterns)
        return subprocess.CompletedProcess(
            args=["openrouter", selected_model],
            returncode=0,
            stdout=raw,
            stderr="",
        )

    raise LLMEngineError(f"unknown LLM engine: {engine!r}")


class CodexWorker:
    """One target-local resumable Codex CLI thread.

    Codex CLI does not expose the same long-lived stdin protocol as Claude Code.
    The warm path therefore starts one persisted `codex exec --json` thread and
    sends later turns through `codex exec resume <thread_id> --json`. That still
    starts a small CLI process per turn, but it reuses the recorded Codex thread
    instead of forcing every prompt to be a cold, ephemeral session.
    """

    def __init__(
        self,
        *,
        model: str,
        timeout_s: int | float | str | None = None,
        cwd: Path | str | None = None,
        sandbox: str | None = None,
        rotate_after_turns: int = 20,
        rotation_saturation: float = DEFAULT_ROTATION_SATURATION,
        worker_id: str | None = None,
        quota_patterns: list[str] | None = None,
    ):
        self.engine = "codex"
        self.model = model
        self.timeout_s = int(float(timeout_s)) if timeout_s else None
        self.cwd = Path(cwd or PROJECT_ROOT)
        self.sandbox = sandbox or os.environ.get("CODEX_SANDBOX", "workspace-write")
        if self.sandbox in ("seatbelt", "sandbox"):
            self.sandbox = "workspace-write"
        self.rotate_after_turns = rotate_after_turns
        self.rotation_saturation = rotation_saturation
        self.worker_id = worker_id or f"codex_{os.getpid()}_{id(self) & 0xffff:04x}"
        self.quota_patterns = list(quota_patterns or DEFAULT_QUOTA_PATTERNS)
        self.reuse_session = _env_flag("CODEX_REUSE_SESSION", False)
        self.thread_id: str | None = None
        self.turn_count = 0
        self.last_saturation: float | None = None
        self.peak_saturation: float = 0.0
        self._lock = threading.Lock()

    def reset(self) -> None:
        self.thread_id = None
        self.turn_count = 0
        self.last_saturation = None
        self.peak_saturation = 0.0

    def close(self) -> None:
        # Codex resume state is persisted by the CLI; there is no live process.
        return None

    def _command(self, last_message_path: Path) -> list[str]:
        if self.reuse_session and self.thread_id:
            cmd = [CODEX_BIN, "exec", "resume", "--json"]
            cmd = _append_codex_common_args(cmd, self.model)
            cmd += ["--output-last-message", str(last_message_path), self.thread_id, "-"]
            return cmd

        cmd = _append_codex_common_args(_codex_base_cmd(self.cwd, self.sandbox), self.model)
        cmd += ["--json", "--output-last-message", str(last_message_path), "-"]
        if not self.reuse_session:
            cmd.insert(cmd.index("--json"), "--ephemeral")
        return cmd

    def send(self, user_text: str) -> dict:
        started = time.time()
        with tempfile.NamedTemporaryFile(
            prefix="codex-last-message-", suffix=".txt", delete=False
        ) as tmp:
            last_message_path = Path(tmp.name)

        cmd = self._command(last_message_path)
        try:
            result = subprocess.run(
                cmd,
                input=user_text,
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=(self.timeout_s + 30) if self.timeout_s else None,
            )
            combined = (result.stdout or "") + (result.stderr or "")
            _check_quota(combined, self.quota_patterns)
            if result.returncode != 0:
                raise CodexWorkerError(
                    f"{self.worker_id} codex exited {result.returncode}: {combined[-800:]}"
                )

            events = _parse_jsonl_events(result.stdout)
            assistant_parts: list[str] = []
            result_event: dict = {}
            for ev in events:
                if ev.get("type") == "thread.started" and ev.get("thread_id"):
                    self.thread_id = ev["thread_id"]
                elif ev.get("type") == "item.completed":
                    item = ev.get("item") or {}
                    if item.get("type") == "agent_message" and item.get("text"):
                        assistant_parts.append(item["text"])
                elif ev.get("type") == "turn.completed":
                    result_event = ev

            last_message = ""
            if last_message_path.exists():
                last_message = last_message_path.read_text()
            text = last_message if last_message.strip() else "\n".join(assistant_parts)
            if not self.thread_id:
                raise CodexWorkerError(f"{self.worker_id} codex did not emit thread_id")

            self.turn_count += 1
            usage = result_event.get("usage", {}) or {}
            context_tokens = usage.get("input_tokens", 0) or 0
            saturation = context_tokens / CONTEXT_BUDGET_TOKENS if context_tokens else 0.0
            self.last_saturation = saturation
            self.peak_saturation = max(self.peak_saturation, saturation)
            needs_rotation = self.reuse_session and (
                self.turn_count >= self.rotate_after_turns
                or saturation >= self.rotation_saturation
            )

            result_payload = {
                **result_event,
                "duration_ms": int((time.time() - started) * 1000),
                "thread_id": self.thread_id,
                "worker_id": self.worker_id,
                "resumed": self.reuse_session and self.turn_count > 1,
            }
            return {
                "text": text,
                "result": result_payload,
                "needs_rotation": needs_rotation,
                "saturation": saturation,
                "turn_count": self.turn_count,
                "session_id": self.thread_id,
            }
        except subprocess.TimeoutExpired as e:
            raise CodexWorkerError(f"{self.worker_id} codex timed out after {self.timeout_s}s") from e
        finally:
            try:
                last_message_path.unlink(missing_ok=True)
            except Exception:
                pass


class CodexWorkerPool:
    """Pool of resumable Codex threads.

    `begin_target()` binds one worker to the current executor thread, so all
    submits for a target's inner/evolve loop reuse the same Codex thread. The
    binding is cleared and the worker is reset at `end_target()` to avoid
    carrying target-specific context into the next target.
    """

    engine = "codex"

    def __init__(self, size: int = 4, **worker_kwargs):
        self.size = size
        self.worker_kwargs = worker_kwargs
        self.model = worker_kwargs.get("model", "unknown")
        self._workers = [
            CodexWorker(worker_id=f"codex_pool_{i}", **worker_kwargs)
            for i in range(size)
        ]
        self._next = 0
        self._busy: set[int] = set()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._local = threading.local()

    def begin_target(self, target_index: int | None = None) -> None:
        with self._condition:
            while len(self._busy) >= self.size:
                self._condition.wait()
            preferred = target_index % self.size if target_index is not None else self._next
            idx = None
            for offset in range(self.size):
                candidate = (preferred + offset) % self.size
                if candidate not in self._busy:
                    idx = candidate
                    break
            if idx is None:
                idx = self._next
            self._busy.add(idx)
            self._next = (idx + 1) % self.size
            self._local.worker_index = idx

    def end_target(self) -> None:
        idx = getattr(self._local, "worker_index", None)
        if idx is None:
            return
        with self._workers[idx]._lock:
            self._workers[idx].reset()
        with self._condition:
            self._busy.discard(idx)
            self._condition.notify()
        self._local.worker_index = None

    def _pick_index(self) -> int:
        bound = getattr(self._local, "worker_index", None)
        if bound is not None:
            return bound
        with self._lock:
            idx = self._next
            self._next = (self._next + 1) % self.size
            return idx

    def submit(self, user_text: str) -> dict:
        last_err = None
        for _ in range(self.size):
            idx = self._pick_index()
            w = self._workers[idx]
            with w._lock:
                try:
                    out = w.send(user_text)
                    if out.get("needs_rotation"):
                        w.reset()
                    return out
                except QuotaExhaustedError:
                    raise
                except CodexWorkerError as e:
                    last_err = e
                    w.reset()
                    if getattr(self._local, "worker_index", None) is not None:
                        break
                    continue
        raise CodexWorkerError(f"all {self.size} codex workers failed; last={last_err}")

    def close(self) -> None:
        for w in self._workers:
            try:
                w.close()
            except Exception:
                pass


class LLMExecPool:
    """Thread-safe enough pool facade for engines without persistent sessions.

    The interface matches ClaudeWorkerPool.submit(), but each submission starts
    a fresh CLI process.
    """

    def __init__(
        self,
        *,
        engine: str,
        model: str,
        timeout_s: int | float | str | None = None,
        budget: str | None = None,
    ):
        self.engine = engine
        self.model = model
        self.timeout_s = timeout_s
        self.budget = budget

    def submit(self, user_text: str) -> dict:
        started = time.time()
        result = run_prompt(
            user_text,
            engine=self.engine,
            model=self.model,
            budget=self.budget,
            timeout_s=self.timeout_s,
            cwd=PROJECT_ROOT,
        )
        if result.returncode != 0:
            raise LLMEngineError(
                f"{self.engine} exited {result.returncode}: {(result.stderr or result.stdout)[-500:]}"
            )
        return {
            "text": result.stdout,
            "result": {
                "duration_ms": int((time.time() - started) * 1000),
                "usage": None,
                "total_cost_usd": None,
            },
            "needs_rotation": False,
            "saturation": None,
            "turn_count": None,
        }

    def close(self) -> None:
        return None
