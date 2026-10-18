# feature/archive-e2e-autonomous-derivation

Archive of Approach 1 of the autonomous derivation research: the monolithic
autonomous epoch loop. It also holds the post-mortem for all of the
derivation research.

## What the branch contains

It branches from `main` at `e0e6e49`. It has 16 commits, from `7ebac4a` to
`f3b9b49`:

- 2026-06-26 to 2026-06-28: last work on the epoch loop. That includes the
  meta-selected BUG_INVESTIGATE route (`prompts/bug_investigate_candidate.md`),
  structured evaluation artifacts, the judge bugfix replay adapter,
  A/B target selection, `python_env.py` re-exec, and analysis-chosen
  experiment specs.
- 2026-07-09 (`4b9015e`): archive snapshot. It adds
  `algebra_linear_practice.py` with the Grade 8 practice corpus,
  `meta_model_compare.py`/`scripts/meta_model_compare.sh`, the
  `algebra_linear_8th_grade_summer` target, and tests.
- 2026-07-19 (`3e73f26`, `f3b9b49`): `derivations/FAILURE_ANALYSIS.md`, the
  case study of both failed approaches, and a status banner at the top of
  `derivations/README.md`.

## Related branches

- `experiment/e2e_control`, `experiment/e2e_cross_epoch`: the 2026-06-21
  BUG_INVESTIGATE e2e runs that came before this work
- `feature/typed-derivation-contracts`: Approach 2A
- `feature/modular-evolution-kernel`: Approach 2B

## Status

Archived as a failed research approach. Do not merge it as a working system.
On 2026-07-19, `test_acceptance_gate_contracts` failed 6 of 10 tests. The
recorded experiments include zero treatment wins and zero promotions. Treat
the historical acceptance and lift metrics as invalid. The run reports and
artifacts were never tracked in Git.

Read `derivations/FAILURE_ANALYSIS.md` first. Section 13 lists the minimum
contract required before any third attempt.
