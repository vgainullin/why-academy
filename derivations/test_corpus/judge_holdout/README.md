# Judge Holdout Corpus

Human-labeled derivation graphs for calibrating the pedagogical judge. The
verifier checks math; this corpus checks the judge. Every change to the judge
prompt, judge model, or adversarial pass should be measured against it before
promotion.

## Layout

```
cases/<case_id>/
  problem.json   # derivation graph in the standard problem schema
  case.json      # target text + per-criterion labels + rationale
```

`case.json` labels use the rubric keys from `prompts/judge_eval.md`
(`one_rule_per_edge`, `given_facts_visible`, `target_goal_reached`) plus
`overall`. `overall` is FAIL iff any criterion is FAIL.

## Label provenance

`label_provenance` is `"seed"` for labels authored during harness construction
and `"human_confirmed"` once a human has reviewed the case and agrees with the
label. Calibration reports count unconfirmed labels and warn; a calibration
verdict based on seed labels measures consistency with the harness author, not
ground truth. Review each case and flip `label_provenance` to
`"human_confirmed"` (or fix the label) to make the numbers meaningful.

## Running calibration

```bash
# primary judge alone (rubric prompt + model)
scripts/judge_calibration.sh

# primary + adversarial second pass (the verdict the pipeline actually uses)
scripts/judge_calibration.sh --adversarial
```

The report goes to `reports/` and the summary prints per-criterion agreement,
overall agreement, and -- the metric that matters most -- false passes: cases
the human labeled FAIL that the judge passed. A false pass ships a bad lesson;
a false fail only costs a regeneration. Thresholds come from the
`judge_calibration` section of the pipeline config (default: zero false
passes, >= 80% overall agreement) and can be overridden on the CLI.

## Adding cases

Prefer real pipeline failures: when a graph survives the judge but turns out
to be pedagogically wrong (or the judge rejects a good graph), freeze it here
with the corrected label. Keep the corpus balanced between PASS and FAIL
overall labels, and keep each FAIL case isolated to one criterion where
possible so per-criterion agreement stays interpretable.
