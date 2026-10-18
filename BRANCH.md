# experiment/e2e_cross_epoch

Cross-epoch arm of the 2026-06-21 end-to-end run of the autonomous epoch loop
with the BUG_INVESTIGATE phase turned on. It checks whether bug-seed evidence
accumulates across epochs, which is the behaviour added in the base commit.

## What the branch changes

One commit on top of `96bf71c` ("Accumulate seed evidence across all epochs,
not just current"):

- `derivations/configs/v5.json`: sets `runner.bug_investigate.enabled` to
  `true`. The rest of the diff is JSON reformatting.

The code is identical to `experiment/e2e_control`. Only the run differs.

## The run

- Two epochs on `derivations/targets/cohort_v1.txt`. The last batch was
  `epoch_002_20260621_114859`. It ran from 15:16 to 16:04 UTC and closed at
  epoch 2.
- Accumulated seed evidence: `fused_subst_simplify` 20,
  `orientation_false_rejection` 10. The control arm saw 0 for the
  orientation seed after one epoch.
- Proposals handled: `proposal_bug_fused_subst_simplify.md` and
  `proposal_bug_orientation_false_rejection.md`.

Run data lives only in the worktree at
`why-academy-worktrees/e2e_cross_epoch`, and none of it is committed:

- `derivations/state.json`: uncommitted edit (epoch 1 -> 3, validator v2 -> v4)
- untracked: three
  `derivations/test_corpus/holdout/problems_legacy_verifier/*.verifier.json`
- ignored: `derivations/_epoch_state.json`, `derivations/logs/` (including
  `implementations/`), `derivations/reports/`, `derivations/_evolutions/`,
  holdout `results_epoch_00{1,2}.json` and `sidecars/`

## Status

Archived experiment. The whole autonomous derivation line was later judged a
failed approach. See `derivations/FAILURE_ANALYSIS.md` on
`feature/archive-e2e-autonomous-derivation`.
