# experiment/e2e_control

Control arm of the 2026-06-21 end-to-end run of the autonomous epoch loop with
the BUG_INVESTIGATE phase turned on.

## What the branch changes

One commit on top of `96bf71c` ("Accumulate seed evidence across all epochs,
not just current"):

- `derivations/configs/v5.json`: sets `runner.bug_investigate.enabled` to
  `true`. The rest of the diff is JSON reformatting.

The code is identical to `experiment/e2e_cross_epoch`. Only the run differs.

## The run

- One epoch on `derivations/targets/cohort_v1.txt` (batch
  `epoch_001_20260621_113452`). It ran from 15:34 to 15:48 UTC and closed at
  epoch 1.
- Seed evidence: `fused_subst_simplify` 14, `orientation_false_rejection` 0.
- Proposal handled: `proposal_bug_fused_subst_simplify.md`.

Run data lives only in the worktree at
`why-academy-worktrees/e2e_control`, and none of it is committed:

- `derivations/state.json`: uncommitted edit (epoch 1 -> 2)
- ignored: `derivations/_epoch_state.json`, `derivations/logs/`,
  `derivations/reports/`, `derivations/_evolutions/`

## Status

Archived experiment. The whole autonomous derivation line was later judged a
failed approach. See `derivations/FAILURE_ANALYSIS.md` on
`feature/archive-e2e-autonomous-derivation`.
