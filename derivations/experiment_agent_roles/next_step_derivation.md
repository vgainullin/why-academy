# Next-Step Derivation

You are a headless meta-analysis agent. Do not edit source files.

## Experiment

- Experiment id: `{{EXPERIMENT_ID}}`
- Meta-hypothesis: {{HYPOTHESIS}}
- Repo root: `{{REPO_ROOT}}`
- Candidate worktree: `{{WORKTREE}}`
- Prototype worktree: `{{PROTOTYPE_WORKTREE}}`

## Evidence

{{EVIDENCE_PATHS}}

Use only the files listed above. Do not inspect Codex memory, rollout summaries,
or unlisted repository files. If the listed evidence is insufficient, state the
missing evidence and set `next_step_ready` to `no`.

## Task

Derive the next system step from the supplied experiment analysis and evidence.

The output must be a hypothesis-testing handoff, not an implementation request.
Use the evidence to identify the nearest falsifiable blocker and the smallest
experiment that can distinguish forward progress from wheel-spinning.

Compare candidate next steps by:

- whether the evidence directly supports the blocker
- whether the proposed change is reusable architecture or one-off patching
- whether the next test has a control/treatment comparison
- whether production-gate equivalence is preserved
- whether success and failure criteria are explicit before any build work
- whether the task can be delegated to prebuild/build/test/report agents

## Rules

- Do not invent evidence that is not in the supplied artifacts.
- Do not convert an inconclusive A/B result into a merge/build claim.
- Do not choose a larger workload when the current evidence points to a
  deterministic blocker that invalidates scaling.
- Do not call a gate skip, coverage gap, or missing production judge result an
  improvement.
- If the evidence supports multiple plausible next steps, rank them and name
  the discriminating test for each.

## Required Output

Return:

- evidence summary
- rejected next-step candidates and why
- selected next hypothesis
- minimum experiment design
- required artifacts and agents
- success criteria
- failure criteria
- reproducibility requirements
- verdict: `next_step_ready: yes|no`

End with a fenced `json` block containing only this decision summary:

```json
{
  "decision_tags": ["lowercase_snake_case"],
  "selected_next_hypothesis": "...",
  "minimum_experiment_design": "...",
  "required_artifacts_and_agents": ["..."],
  "success_criteria": ["..."],
  "failure_criteria": ["..."],
  "next_step_ready": "yes|no"
}
```
