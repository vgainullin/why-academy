#!/usr/bin/env python3
"""General worktree comparison framework.

Compares results from two experiment worktrees using pluggable extractors.
Each extractor implements a protocol that knows how to read a specific type
of experiment artifact, pair results between two worktrees, compute a
comparison summary, and render a markdown report.

Built-in extractors:
  bugfix   — reads BUGFIX closure sidecars, pairs by seed hypothesis
  batch    — reads generation batch target_metrics, pairs by target_index
  test     — runs the test suite in each worktree, compares pass/fail

Custom extractors can be registered by subclassing Extractor and adding
to the EXTRACTORS registry, or via the --extractor-module flag pointing
to a Python module that defines an Extractor subclass named ``Extractor``.

CLI:
  worktree_compare.py --control <path> --treatment <path>
                      [--extractor bugfix|batch|test|auto]
                      [--experiment-id <id>] [--out-dir <path>]
                      [--extractor-module <module_path>]
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _reexec_with_derivation_python() -> None:
    if os.environ.get("WORKTREE_COMPARE_REEXECED") == "1":
        return
    candidates: list[Path] = []
    configured = os.environ.get("DERIVATION_PYTHON")
    if configured:
        candidates.append(Path(configured))
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "derivations" / ".venv" / "bin" / "python")
        candidates.append(parent / ".venv" / "bin" / "python")
    current = Path(sys.executable).resolve()
    for candidate in candidates:
        if candidate.exists() and candidate.resolve() != current:
            os.environ["WORKTREE_COMPARE_REEXECED"] = "1"
            os.execv(str(candidate), [str(candidate), *sys.argv])


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


# ── Extractor protocol ───────────────────────────────────────────────────


class Extractor(ABC):
    """Base class for worktree comparison extractors.

    An extractor knows how to:
    1. Read experiment artifacts from a single worktree (``extract``)
    2. Pair results between control and treatment worktrees (``pair``)
    3. Compute aggregate comparison metrics (``summarize``)
    4. Render a markdown report (``render_markdown``)
    """

    name: str = "base"

    @abstractmethod
    def extract(self, worktree: Path) -> dict[str, Any]:
        """Read all experiment artifacts from a worktree.

        Returns a dict with at least a ``worktree_path`` key and a ``pairs_key``
        key naming the field that holds the list of individually-comparable
        results (e.g. ``seeds`` for bugfix, ``targets`` for batch).
        """
        ...

    @abstractmethod
    def pair(self, control: dict[str, Any], treatment: dict[str, Any]) -> list[dict[str, Any]]:
        """Pair results from two worktrees into a list of comparison records.

        Each record should have a ``pair_key`` identifying what was paired
        (e.g. a seed name, target index, test name), a ``control`` dict,
        a ``treatment`` dict, and a ``winner`` field.
        """
        ...

    @abstractmethod
    def summarize(self, pairs: list[dict[str, Any]], control: dict[str, Any],
                  treatment: dict[str, Any]) -> dict[str, Any]:
        """Compute aggregate comparison metrics from the paired results."""
        ...

    @abstractmethod
    def render_markdown(self, summary: dict[str, Any]) -> str:
        """Render the full comparison as a markdown report."""
        ...


# ── Bugfix extractor ─────────────────────────────────────────────────────


class BugfixExtractor(Extractor):
    """Compares BUGFIX closure sidecars, paired by seed hypothesis."""

    name = "bugfix"

    @staticmethod
    def _find_closures(worktree: Path) -> list[dict[str, Any]]:
        reports_root = worktree / "derivations" / "reports"
        if not reports_root.exists():
            return []
        sidecars: list[dict[str, Any]] = []
        for sc in sorted(reports_root.glob("epoch_*/proposal_bug_*_closure.json")):
            record = read_json(sc)
            if isinstance(record, dict):
                record["_closure_path"] = str(sc)
                sidecars.append(record)
        return sidecars

    @staticmethod
    def _find_proposals(worktree: Path) -> list[dict[str, Any]]:
        reports_root = worktree / "derivations" / "reports"
        if not reports_root.exists():
            return []
        kind_re = re.compile(r"^\*\*Kind\*\*:\s*`?([A-Za-z_]+)`?", re.MULTILINE)
        seed_re = re.compile(r"^\*\*Seed hypothesis\*\*:\s*`?([^\s`]+)`?", re.MULTILINE)
        rule_re = re.compile(r"^\*\*Affected rule\*\*:\s*`?([^\s`]+)`?", re.MULTILINE)
        ev_re = re.compile(r"^\*\*Evidence count\*\*:\s*(\d+)", re.MULTILINE)
        proposals: list[dict[str, Any]] = []
        for p in sorted(reports_root.glob("epoch_*/proposal_bug_*.md")):
            text = p.read_text()
            km = kind_re.search(text)
            sm = seed_re.search(text)
            rm = rule_re.search(text)
            em = ev_re.search(text)
            proposals.append({
                "kind": km.group(1) if km else "",
                "seed": sm.group(1) if sm else "",
                "rule": rm.group(1) if rm else "",
                "evidence_count": int(em.group(1)) if em else 0,
            })
        return proposals

    @staticmethod
    def _count_regression(worktree: Path, rule: str) -> dict[str, int]:
        corpus = worktree / "derivations" / "test_corpus" / rule
        pos = read_json(corpus / "positive.json", [])
        neg = read_json(corpus / "negative.json", [])
        bp = sum(1 for e in pos if "bugfix:" in e.get("description", "")) if isinstance(pos, list) else 0
        bn = sum(1 for e in neg if "bugfix:" in e.get("description", "")) if isinstance(neg, list) else 0
        return {
            "total_positive": len(pos) if isinstance(pos, list) else 0,
            "total_negative": len(neg) if isinstance(neg, list) else 0,
            "bugfix_positive": bp,
            "bugfix_negative": bn,
        }

    def extract(self, worktree: Path) -> dict[str, Any]:
        closures = self._find_closures(worktree)
        proposals = self._find_proposals(worktree)
        state = read_json(worktree / "derivations" / "state.json", {})
        epoch_state = read_json(worktree / "derivations" / "_epoch_state.json", {})

        closures_by_seed = {c.get("seed_hypothesis", ""): c for c in closures if c.get("seed_hypothesis")}
        proposals_by_seed = {p.get("seed", ""): p for p in proposals if p.get("seed")}
        all_seeds = sorted(set(closures_by_seed) | set(proposals_by_seed))

        seed_results: list[dict[str, Any]] = []
        for seed in all_seeds:
            c = closures_by_seed.get(seed, {})
            p = proposals_by_seed.get(seed, {})
            rule = c.get("rule") or p.get("rule", "")
            verdict = None
            if c:
                verdict = ("REPRO_CONFIRMED"
                           if c.get("lift_fraction", 0) >= c.get("min_lift_threshold", 0.4)
                           and not c.get("holdout_regressed")
                           else "REPRO_FAILED")
            seed_results.append({
                "pair_key": seed,
                "seed": seed,
                "kind": p.get("kind", c.get("kind", "")),
                "rule": rule,
                "evidence_count": p.get("evidence_count", 0),
                "closure_verdict": verdict,
                "lift_fraction": c.get("lift_fraction"),
                "holdout_regressed": c.get("holdout_regressed"),
                "actual_status": c.get("actual_status"),
                "expected_status": c.get("expected_status"),
                "regression_tests": self._count_regression(worktree, rule) if rule else {},
            })

        return {
            "worktree_path": str(worktree),
            "pairs_key": "seed_results",
            "epoch": state.get("epoch"),
            "validator_version": state.get("validator_version"),
            "phase": epoch_state.get("phase"),
            "n_bugfix_proposals": sum(1 for p in proposals if p.get("kind") == "BUGFIX"),
            "n_investigate_proposals": sum(1 for p in proposals if p.get("kind") == "INVESTIGATE"),
            "n_closures": len(closures),
            "seed_results": seed_results,
        }

    @staticmethod
    def _seed_winner(c_verdict: str | None, t_verdict: str | None,
                     c_lift: float | None, t_lift: float | None) -> str:
        if c_verdict == "REPRO_CONFIRMED" and t_verdict != "REPRO_CONFIRMED":
            return "control"
        if t_verdict == "REPRO_CONFIRMED" and c_verdict != "REPRO_CONFIRMED":
            return "treatment"
        if c_verdict == t_verdict:
            if c_lift is not None and t_lift is not None:
                if c_lift > t_lift:
                    return "control"
                if t_lift > c_lift:
                    return "treatment"
            elif c_lift is not None:
                return "control"
            elif t_lift is not None:
                return "treatment"
        return "tie"

    def pair(self, control: dict[str, Any], treatment: dict[str, Any]) -> list[dict[str, Any]]:
        c_by = {s["pair_key"]: s for s in control.get("seed_results", [])}
        t_by = {s["pair_key"]: s for s in treatment.get("seed_results", [])}
        all_keys = sorted(set(c_by) | set(t_by))
        pairs: list[dict[str, Any]] = []
        for key in all_keys:
            c = c_by.get(key, {})
            t = t_by.get(key, {})
            winner = self._seed_winner(
                c.get("closure_verdict"), t.get("closure_verdict"),
                c.get("lift_fraction"), t.get("lift_fraction"),
            )
            pairs.append({"pair_key": key, "winner": winner, "control": c, "treatment": t})
        return pairs

    def summarize(self, pairs: list[dict[str, Any]], control: dict[str, Any],
                  treatment: dict[str, Any]) -> dict[str, Any]:
        c_conf = sum(1 for p in pairs if p["control"].get("closure_verdict") == "REPRO_CONFIRMED")
        t_conf = sum(1 for p in pairs if p["treatment"].get("closure_verdict") == "REPRO_CONFIRMED")
        c_reg = sum(1 for p in pairs if p["control"].get("holdout_regressed"))
        t_reg = sum(1 for p in pairs if p["treatment"].get("holdout_regressed"))
        c_wins = sum(1 for p in pairs if p["winner"] == "control")
        t_wins = sum(1 for p in pairs if p["winner"] == "treatment")
        ties = sum(1 for p in pairs if p["winner"] == "tie")
        overall = "control" if c_wins > t_wins else "treatment" if t_wins > c_wins else "tie"
        return {
            "extractor": self.name,
            "experiment_id": None,
            "control_worktree": control,
            "treatment_worktree": treatment,
            "paired": {
                "n_pairs": len(pairs),
                "control_confirmed": c_conf,
                "treatment_confirmed": t_conf,
                "control_holdout_regressed": c_reg,
                "treatment_holdout_regressed": t_reg,
                "control_wins": c_wins,
                "treatment_wins": t_wins,
                "ties": ties,
                "overall_winner": overall,
            },
            "pairs": pairs,
        }

    def render_markdown(self, summary: dict[str, Any]) -> str:
        c = summary["control_worktree"]
        t = summary["treatment_worktree"]
        p = summary["paired"]
        lines = [
            f"# A/B Comparison ({self.name}): {summary.get('experiment_id', '')}",
            "",
            f"- Control: `{c['worktree_path']}`",
            f"- Treatment: `{t['worktree_path']}`",
            f"- Pairs: {p['n_pairs']}",
            f"- Confirmed: control {p['control_confirmed']}, treatment {p['treatment_confirmed']}",
            f"- Holdout regressed: control {p['control_holdout_regressed']}, treatment {p['treatment_holdout_regressed']}",
            f"- Wins: control {p['control_wins']}, treatment {p['treatment_wins']}, ties {p['ties']}",
            f"- **Overall winner: {p['overall_winner']}**",
            "",
            "## Worktree summaries",
            "",
            "| Metric | Control | Treatment |",
            "|--------|---------|-----------|",
            f"| Epoch | {c.get('epoch', '?')} | {t.get('epoch', '?')} |",
            f"| Validator version | {c.get('validator_version', '?')} | {t.get('validator_version', '?')} |",
            f"| BUGFIX proposals | {c.get('n_bugfix_proposals', '?')} | {t.get('n_bugfix_proposals', '?')} |",
            f"| INVESTIGATE proposals | {c.get('n_investigate_proposals', '?')} | {t.get('n_investigate_proposals', '?')} |",
            f"| Closures | {c.get('n_closures', '?')} | {t.get('n_closures', '?')} |",
            "",
            "## Per-seed comparison",
            "",
            "| Seed | Kind | Ctrl Verdict | Ctrl Lift | Ctrl Holdout | Treat Verdict | Treat Lift | Treat Holdout | Winner |",
            "|------|------|-------------|-----------|-------------|---------------|------------|---------------|--------|",
        ]
        for pair in summary["pairs"]:
            cv = pair["control"]
            tv = pair["treatment"]
            cl = f"{cv['lift_fraction']:.2%}" if cv.get("lift_fraction") is not None else "-"
            tl = f"{tv['lift_fraction']:.2%}" if tv.get("lift_fraction") is not None else "-"
            ch = cv.get("holdout_regressed") or "none"
            th = tv.get("holdout_regressed") or "none"
            lines.append(
                f"| {pair['pair_key']} | {cv.get('kind') or tv.get('kind', '')} | "
                f"{cv.get('closure_verdict') or '-'} | {cl} | {ch} | "
                f"{tv.get('closure_verdict') or '-'} | {tl} | {th} | "
                f"{pair['winner']} |"
            )
        lines.extend([
            "",
            "## Regression test coverage",
            "",
            "| Seed | Side | Bugfix + | Bugfix - | Total + | Total - |",
            "|------|------|----------|----------|---------|---------|",
        ])
        for pair in summary["pairs"]:
            for label, side_key in [("Control", "control"), ("Treatment", "treatment")]:
                rt = pair[side_key].get("regression_tests", {})
                lines.append(
                    f"| {pair['pair_key']} | {label} | "
                    f"{rt.get('bugfix_positive', 0)} | {rt.get('bugfix_negative', 0)} | "
                    f"{rt.get('total_positive', 0)} | {rt.get('total_negative', 0)} |"
                )
        lines.append("")
        return "\n".join(lines)


# ── Batch extractor ──────────────────────────────────────────────────────


class BatchExtractor(Extractor):
    """Compares generation batch target outcomes, paired by target_index."""

    name = "batch"

    @staticmethod
    def _find_batch_dir(worktree: Path) -> Path | None:
        evo = worktree / "derivations" / "_evolutions" / "batches"
        if not evo.exists():
            return None
        batches = sorted(evo.iterdir())
        return batches[-1] if batches else None

    def extract(self, worktree: Path) -> dict[str, Any]:
        batch_dir = self._find_batch_dir(worktree)
        state = read_json(worktree / "derivations" / "state.json", {})
        targets_dir = batch_dir / "targets" if batch_dir else None
        target_results: list[dict[str, Any]] = []
        if targets_dir and targets_dir.exists():
            for td in sorted(targets_dir.glob("target_*")):
                metrics = read_json(td / "target_metrics.json", {})
                target_json = read_json(td / "target.json", {})
                if not isinstance(metrics, dict):
                    continue
                target_results.append({
                    "pair_key": metrics.get("target_index"),
                    "target": target_json.get("target", "") if isinstance(target_json, dict) else "",
                    "accepted": metrics.get("accepted"),
                    "first_try_pass": metrics.get("first_try_pass"),
                    "n_iterations": metrics.get("n_iterations"),
                    "failure_reason": metrics.get("failure_reason"),
                })
        n_acc = sum(1 for t in target_results if t.get("accepted"))
        n_first = sum(1 for t in target_results if t.get("first_try_pass"))
        return {
            "worktree_path": str(worktree),
            "pairs_key": "target_results",
            "epoch": state.get("epoch"),
            "batch_id": batch_dir.name if batch_dir else None,
            "n_targets": len(target_results),
            "n_accepted": n_acc,
            "n_first_try_pass": n_first,
            "acceptance_rate": n_acc / len(target_results) if target_results else 0,
            "first_try_pass_rate": n_first / len(target_results) if target_results else 0,
            "target_results": target_results,
        }

    @staticmethod
    def _target_winner(c: dict[str, Any], t: dict[str, Any]) -> str:
        c_acc = c.get("accepted")
        t_acc = t.get("accepted")
        if c_acc and not t_acc:
            return "control"
        if t_acc and not c_acc:
            return "treatment"
        if c_acc and t_acc:
            c_it = c.get("n_iterations", 99) or 99
            t_it = t.get("n_iterations", 99) or 99
            if c_it < t_it:
                return "control"
            if t_it < c_it:
                return "treatment"
        return "tie"

    def pair(self, control: dict[str, Any], treatment: dict[str, Any]) -> list[dict[str, Any]]:
        c_by = {t["pair_key"]: t for t in control.get("target_results", []) if t.get("pair_key") is not None}
        t_by = {t["pair_key"]: t for t in treatment.get("target_results", []) if t.get("pair_key") is not None}
        all_keys = sorted(set(c_by) | set(t_by))
        pairs: list[dict[str, Any]] = []
        for key in all_keys:
            c = c_by.get(key, {})
            t = t_by.get(key, {})
            winner = self._target_winner(c, t)
            pairs.append({"pair_key": key, "winner": winner, "control": c, "treatment": t})
        return pairs

    def summarize(self, pairs: list[dict[str, Any]], control: dict[str, Any],
                  treatment: dict[str, Any]) -> dict[str, Any]:
        both_acc = sum(1 for p in pairs if p["control"].get("accepted") and p["treatment"].get("accepted"))
        both_fail = sum(1 for p in pairs if not p["control"].get("accepted") and not p["treatment"].get("accepted"))
        c_only = sum(1 for p in pairs if p["control"].get("accepted") and not p["treatment"].get("accepted"))
        t_only = sum(1 for p in pairs if not p["control"].get("accepted") and p["treatment"].get("accepted"))
        c_wins = sum(1 for p in pairs if p["winner"] == "control")
        t_wins = sum(1 for p in pairs if p["winner"] == "treatment")
        ties = sum(1 for p in pairs if p["winner"] == "tie")
        overall = "control" if c_wins > t_wins else "treatment" if t_wins > c_wins else "tie"
        c_rate = control.get("acceptance_rate", 0)
        t_rate = treatment.get("acceptance_rate", 0)
        return {
            "extractor": self.name,
            "experiment_id": None,
            "control_worktree": control,
            "treatment_worktree": treatment,
            "paired": {
                "n_pairs": len(pairs),
                "both_accepted": both_acc,
                "both_failed": both_fail,
                "control_only_accepted": c_only,
                "treatment_only_accepted": t_only,
                "control_acceptance_rate": c_rate,
                "treatment_acceptance_rate": t_rate,
                "acceptance_delta": t_rate - c_rate,
                "control_wins": c_wins,
                "treatment_wins": t_wins,
                "ties": ties,
                "overall_winner": overall,
            },
            "pairs": pairs,
        }

    def render_markdown(self, summary: dict[str, Any]) -> str:
        c = summary["control_worktree"]
        t = summary["treatment_worktree"]
        p = summary["paired"]
        lines = [
            f"# A/B Comparison ({self.name}): {summary.get('experiment_id', '')}",
            "",
            f"- Control: `{c['worktree_path']}`",
            f"- Treatment: `{t['worktree_path']}`",
            f"- Pairs: {p['n_pairs']}",
            f"- Acceptance: control {p['control_acceptance_rate']:.2%}, treatment {p['treatment_acceptance_rate']:.2%}, delta {p['acceptance_delta']:+.2%}",
            f"- Outcomes: both accepted {p['both_accepted']}, both failed {p['both_failed']}, control-only {p['control_only_accepted']}, treatment-only {p['treatment_only_accepted']}",
            f"- Wins: control {p['control_wins']}, treatment {p['treatment_wins']}, ties {p['ties']}",
            f"- **Overall winner: {p['overall_winner']}**",
            "",
            "## Per-target comparison",
            "",
            "| Target | Ctrl Accepted | Ctrl Iters | Treat Accepted | Treat Iters | Winner |",
            "|--------|---------------|------------|----------------|-------------|--------|",
        ]
        for pair in summary["pairs"]:
            cv = pair["control"]
            tv = pair["treatment"]
            target = (cv.get("target") or tv.get("target", ""))[:60]
            lines.append(
                f"| {target} | {cv.get('accepted', '-')} | {cv.get('n_iterations', '-')} | "
                f"{tv.get('accepted', '-')} | {tv.get('n_iterations', '-')} | "
                f"{pair['winner']} |"
            )
        lines.append("")
        return "\n".join(lines)


# ── Test suite extractor ─────────────────────────────────────────────────


class TestSuiteExtractor(Extractor):
    """Runs the test suite in each worktree and compares pass/fail counts."""

    name = "test"

    @staticmethod
    def _run_tests(worktree: Path) -> dict[str, Any]:
        script = worktree / "scripts" / "test_derivations.sh"
        if not script.exists():
            return {"ran": 0, "passed": False, "error": "test_derivations.sh not found"}
        venv_py = os.environ.get("DERIVATION_PYTHON") or str(
            PROJECT_ROOT / "derivations" / ".venv" / "bin" / "python")
        env = {**os.environ, "DERIVATION_PYTHON": venv_py}
        r = subprocess.run(
            ["bash", str(script)], cwd=str(worktree),
            capture_output=True, text=True, timeout=300, env=env,
        )
        output = r.stdout + r.stderr
        ran_match = re.search(r"Ran (\d+) tests?", output)
        ran = int(ran_match.group(1)) if ran_match else 0
        passed = "OK" in output and r.returncode == 0
        return {"ran": ran, "passed": passed, "returncode": r.returncode}

    def extract(self, worktree: Path) -> dict[str, Any]:
        result = self._run_tests(worktree)
        return {
            "worktree_path": str(worktree),
            "pairs_key": "test_results",
            "ran": result.get("ran", 0),
            "passed": result.get("passed", False),
            "test_results": [{"pair_key": "suite", **result}],
        }

    @staticmethod
    def _test_winner(c: dict[str, Any], t: dict[str, Any]) -> str:
        c_p = c.get("passed", False)
        t_p = t.get("passed", False)
        if c_p and not t_p:
            return "control"
        if t_p and not c_p:
            return "treatment"
        if c_p and t_p:
            c_ran = c.get("ran", 0)
            t_ran = t.get("ran", 0)
            if c_ran > t_ran:
                return "control"
            if t_ran > c_ran:
                return "treatment"
        return "tie"

    def pair(self, control: dict[str, Any], treatment: dict[str, Any]) -> list[dict[str, Any]]:
        c = control.get("test_results", [{}])[0]
        t = treatment.get("test_results", [{}])[0]
        return [{"pair_key": "suite", "winner": self._test_winner(c, t), "control": c, "treatment": t}]

    def summarize(self, pairs: list[dict[str, Any]], control: dict[str, Any],
                  treatment: dict[str, Any]) -> dict[str, Any]:
        p = pairs[0] if pairs else {"winner": "tie", "control": {}, "treatment": {}}
        return {
            "extractor": self.name,
            "experiment_id": None,
            "control_worktree": control,
            "treatment_worktree": treatment,
            "paired": {
                "n_pairs": 1,
                "control_passed": control.get("passed", False),
                "treatment_passed": treatment.get("passed", False),
                "control_tests_ran": control.get("ran", 0),
                "treatment_tests_ran": treatment.get("ran", 0),
                "overall_winner": p["winner"],
            },
            "pairs": pairs,
        }

    def render_markdown(self, summary: dict[str, Any]) -> str:
        c = summary["control_worktree"]
        t = summary["treatment_worktree"]
        p = summary["paired"]
        lines = [
            f"# A/B Comparison ({self.name}): {summary.get('experiment_id', '')}",
            "",
            f"- Control: `{c['worktree_path']}`",
            f"- Treatment: `{t['worktree_path']}`",
            f"- Control: ran {p['control_tests_ran']} tests, passed={p['control_passed']}",
            f"- Treatment: ran {p['treatment_tests_ran']} tests, passed={p['treatment_passed']}",
            f"- **Overall winner: {p['overall_winner']}**",
            "",
        ]
        return "\n".join(lines)


# ── Registry & auto-detection ────────────────────────────────────────────

EXTRACTORS: dict[str, type[Extractor]] = {
    "bugfix": BugfixExtractor,
    "batch": BatchExtractor,
    "test": TestSuiteExtractor,
}


def auto_detect(worktree: Path) -> str:
    """Detect which extractor to use based on artifacts present in a worktree."""
    reports = worktree / "derivations" / "reports"
    if reports.exists() and any(reports.glob("epoch_*/proposal_bug_*_closure.json")):
        return "bugfix"
    evo = worktree / "derivations" / "_evolutions" / "batches"
    if evo.exists() and any(evo.iterdir()):
        return "batch"
    return "test"


# ── Framework ────────────────────────────────────────────────────────────


def compare_worktrees(control: Path, treatment: Path, extractor: Extractor,
                      experiment_id: str | None = None) -> dict[str, Any]:
    """Run a full comparison between two worktrees using the given extractor."""
    c_metrics = extractor.extract(control)
    t_metrics = extractor.extract(treatment)
    pairs = extractor.pair(c_metrics, t_metrics)
    summary = extractor.summarize(pairs, c_metrics, t_metrics)
    summary["experiment_id"] = experiment_id or f"{extractor.name}_ab_{control.name}_vs_{treatment.name}"
    return summary


def load_extractor(name: str, module_path: str | None = None) -> Extractor:
    if module_path:
        spec = importlib.util.spec_from_file_location("custom_extractor", module_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot load extractor module: {module_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls = getattr(mod, "Extractor", None)
        if cls is None or not issubclass(cls, Extractor):
            raise ValueError(f"module {module_path} must define an Extractor subclass")
        return cls()
    if name not in EXTRACTORS:
        raise ValueError(f"unknown extractor: {name} (available: {', '.join(EXTRACTORS)})")
    return EXTRACTORS[name]()


def main() -> int:
    _reexec_with_derivation_python()

    ap = argparse.ArgumentParser(description="General worktree comparison framework")
    ap.add_argument("--control", required=True, type=Path)
    ap.add_argument("--treatment", required=True, type=Path)
    ap.add_argument("--extractor", default="auto",
                    help="extractor name (bugfix|batch|test|auto) or custom")
    ap.add_argument("--extractor-module", default=None,
                    help="path to a Python module defining a custom Extractor subclass")
    ap.add_argument("--experiment-id", default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    if not args.control.exists():
        print(f"control worktree not found: {args.control}", file=sys.stderr)
        return 2
    if not args.treatment.exists():
        print(f"treatment worktree not found: {args.treatment}", file=sys.stderr)
        return 2

    ext_name = args.extractor
    if ext_name == "auto":
        ext_name = auto_detect(args.control)
        print(f"[compare] auto-detected extractor: {ext_name}", file=sys.stderr)

    extractor = load_extractor(ext_name, args.extractor_module)

    summary = compare_worktrees(
        args.control.resolve(), args.treatment.resolve(),
        extractor, experiment_id=args.experiment_id,
    )

    out_dir = (args.out_dir or PROJECT_ROOT).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"ab_{extractor.name}_comparison"
    (out_dir / f"{prefix}.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / f"{prefix}.md").write_text(extractor.render_markdown(summary) + "\n")

    print(json.dumps(summary["paired"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
