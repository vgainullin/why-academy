# Tactic Inner Mode Pilot - 2026-06-15

## Hypothesis

Typed tactic plans plus deterministic execution reduce fused-edge failures by
moving operation selection into a small schema and executing supported tactics in
code instead of asking the model to emit final graph edges directly.

## Evidence Inputs

- Control batch: `derivations/_evolutions/batches/real_workload_20260614_001`
- Control introspection: `derivations/_evolutions/batches/real_workload_20260614_001/introspective_log_review_target_008_output.json`
- Treatment worktree: `derivations/_evolutions/worktrees/tactic-inner-mode-experiment`
- Treatment pilot batch: `derivations/_evolutions/worktrees/tactic-inner-mode-experiment/derivations/_evolutions/batches/tactic_real_pilot_20260615_002`
- Treatment JSONL: `derivations/_evolutions/worktrees/tactic-inner-mode-experiment/derivations/logs/epoch_001/batch_tactic_real_pilot_20260615_002.jsonl`
- Expanded treatment pilot batch: `derivations/_evolutions/worktrees/tactic-inner-mode-experiment/derivations/_evolutions/batches/tactic_real_pilot_20260615_003`
- Corrected treatment pilot batch: `derivations/_evolutions/worktrees/tactic-inner-mode-experiment/derivations/_evolutions/batches/tactic_real_pilot_20260615_004`
- Fresh JSON control batch: `derivations/_evolutions/batches/tactic_control_json_pilot_20260615_001`

## Treatment

The implementation adds opt-in `INNER_MODE=tactic`.

The model emits a typed plan:

- explicit fact refs
- `root_ref` and `goal_ref`
- one tactic per step
- tactic args only, not graph nodes/edges

The wrapper validates the plan, executes supported tactics deterministically,
then sends the resulting graph through the normal verifier, normalizer, canvas,
target, primary judge, and adversarial judge gates.

## Pilot Command

```bash
DERIVATION_PYTHON=/Users/vlad/projects/why-academy/derivations/.venv/bin/python3 \
INNER_ENGINE=codex INNER_MODEL= \
EVOLVE_ENGINE=codex EVOLVE_MODEL= \
ADVERSARIAL_JUDGE_ENGINE=openrouter \
ADVERSARIAL_JUDGE_MODEL=anthropic/claude-sonnet-4.6 \
BATCH_PARALLEL=1 MAX_ITER=1 \
scripts/batch.sh \
  --batch-id tactic_real_pilot_20260615_002 \
  --inner-mode tactic \
  --parallel 1 \
  --max-iter 1 \
  derivations/targets/e2e_smoke.txt
```

The same command failed inside the sandbox because Codex CLI could not initialize
its app-server client. It succeeded outside the sandbox.

## Result

| Target | Control | Treatment |
| --- | --- | --- |
| `solve x + 2 = 5 for x` | PASS in `real_workload_20260614_001` target 000 | PASS in `tactic_real_pilot_20260615_002` target 000 |
| vertical loop height | FAIL after 3 iterations; final failure was `verify_fail` from fused `divide_both_sides` + `swap_sides` | FAIL closed before graph construction as `tactic_coverage_gap` |

Treatment target 000 passed through the full hardened gate:

- verifier: 1 PASS edge, 0 FAIL/ERROR
- target check: PASS
- primary judge: DeepSeek PASS
- adversarial judge: OpenRouter Claude upheld

Treatment target 001 produced no graph. The model emitted unsupported tactics:

- `solve_for_expression`
- `substitute_into_equation`

The JSONL record preserves this as an explicit pregraph treatment failure with
zero nodes and zero edges.

## Interpretation

This is a material diagnostic and safety improvement, not yet an acceptance
improvement.

The treatment changed the vertical-loop failure from a malformed graph that
fused adjacent operations into a pregraph coverage gap. That means the model no
longer shipped a bad edge for this case; it exposed missing executor capability.

The next blocker is deterministic tactic coverage, not another prompt reminder.

## Next Hypothesis

If the executor adds sound deterministic support for `solve_for_expression` and
`substitute_into_equation`, then the vertical-loop target should progress from
coverage gap to valid graph without reintroducing fused `divide_both_sides` +
`swap_sides` failures.

Required proof before full A/B:

- unit tests for sound solve and substitution contracts
- target 008 golden fixture requiring `Eq(5*R/2, h)` before final `swap_sides`
- real pilot on `derivations/targets/e2e_smoke.txt`
- side-by-side comparison against the existing control batch

## Expanded Executor Result

The next iteration added deterministic `solve_for_expression` and
`substitute_into_equation` support plus verifier contracts for both rules.

Treatment pilot `tactic_real_pilot_20260615_003` passed both targets, but code
review found that it allowed `solve_for_expression` for bare symbol `h`. That
made `solve_for_expression` too powerful: it could collapse final divide/swap
isolation into one macro edge. The treatment was tightened so
`solve_for_expression` is allowed only for compound expressions such as `v**2`;
bare symbols must use sidewise tactics.

Corrected treatment pilot `tactic_real_pilot_20260615_004` passed both targets:

| Target | Result | Notes |
| --- | --- | --- |
| `solve x + 2 = 5 for x` | PASS | 1 verified edge |
| vertical loop height | PASS | 7 verified edges: divide, multiply, swap, substitute, simplify, divide, swap |

The vertical-loop treatment graph had:

- verifier: 7 PASS edges, 0 FAIL/ERROR
- target check: PASS, with both givens matched
- primary judge: DeepSeek PASS
- adversarial judge: OpenRouter Claude upheld
- unsupported tactics: none

Fresh JSON control `tactic_control_json_pilot_20260615_001` also passed both
targets, but the vertical-loop graph used one `substitute_expression` edge from
the energy equation directly to the already-combined `5*m*g*R/2 = m*g*h` form.
That edge bundled substitution with simplification. The primary and adversarial
judges both missed this and accepted the graph.

Updated interpretation:

- The treatment did not show acceptance lift on the tiny two-target pilot because
  the fresh control was also accepted.
- It did show material quality lift: the treatment accepted graph preserved the
  one-operation-per-edge decomposition, while the accepted control graph still
  contained the fused substitution/simplification pitfall.
- This is evidence that typed tactic execution can reduce false-pass risk even
  when the judge fails to detect the same issue.

Next required experiment before merge:

- Run a larger side-by-side workload, not just `e2e_smoke.txt`.
- Score accepted graphs for fused substitution/simplification and fused
  side-operation/orientation changes, not only acceptance.
- Treat accepted-but-fused control outputs as false passes.
