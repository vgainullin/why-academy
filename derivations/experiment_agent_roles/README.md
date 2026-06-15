# Experiment Agent Gates

These role prompts make hypothesis-driven changes repeatable. They are not
one-off chat prompts; they are the standard gates before a derivation experiment
can spend real model calls or be considered for merge.

Use `scripts/experiment_agents.sh render` to materialize a gate packet under
`derivations/_evolutions/experiment_agents/<experiment_id>/`.

Default flow:

1. `prebuild`: code-review the current proposal, design tests, and design
   integration.
2. `build`: implement only after the prebuild outputs are understood.
3. `postbuild`: review the patch, run local/pilot gates, then analyze full A/B
   results.

The gates are intentionally separate agents. They should disagree when the
proposal is weak; that disagreement is evidence, not friction.
