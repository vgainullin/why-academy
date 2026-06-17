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
4. `reporting`: generate the markdown report from artifacts, then review the
   report against those artifacts before it is committed.

The gates are intentionally separate agents. They should disagree when the
proposal is weak; that disagreement is evidence, not friction.

Reports are generated artifacts too. The report writer may edit only the target
markdown report path, and the report review gate must verify that claims are
grounded in the supplied evidence paths.
