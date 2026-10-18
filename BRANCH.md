# feature/typed-derivation-contracts

Approach 2A of the autonomous derivation research: frozen typed task contracts
and a trusted oracle for Grade 8 linear equations.

## What the branch contains

It branches from `main` at `e0e6e49`. The 8 commits from `2bc8ea5` to `492fcfa`
add:

- `derivations/task_contract.py`: a frozen task contract (givens, solution
  cardinality, canonical result, pedagogy requirements) plus a public envelope
  that holds no expected answer or digests
- `derivations/frozen_task_store.py`: a digest-pinned frozen task bundle
- `derivations/graph_contract.py`, `derivations/generate_typed_graph.py`:
  graph schema/topology checks and typed graph generation
- `derivations/typed_linear_equation_oracle.py`: a trusted evaluator for
  linear equations, including special outcomes (no solution, infinitely many)
- `derivations/typed_pilot.py`, `scripts/typed_pilot.sh`: a pilot that runs the
  candidate in a read-only isolated (Codex) workspace and the oracle from a
  clean checkout pinned to a commit
- `derivations/practice/algebra_linear_8th_grade_summer.json`: a deterministic
  Grade 8 practice corpus
- `derivations/targets/typed_linear_equation_pilot_12.txt`: the pilot targets
- small judge prompt edits to match rule semantics, plus tests

## Related branches

- `feature/modular-evolution-kernel` is built on this branch's code at
  `492fcfa`.
- The detached worktree `why-academy-typed-oracle` is also at `492fcfa`.

## Status

Not merged and not expected to be. On 2026-07-19, `scripts/test_derivations.sh`
passed (353 tests). The only real typed run located covered one task (one
pass). The work tightened the trust boundary but did not show autonomous
synthesis or learning. Per the case study, the contracts and oracle may be
reused as specification or evaluator material for a future benchmark. See
`derivations/FAILURE_ANALYSIS.md` (sections 6 and 8) on
`feature/archive-e2e-autonomous-derivation`.
