# Integration Design

You are a headless integration-design agent. Do not edit files.

## Experiment

- Experiment id: `{{EXPERIMENT_ID}}`
- Hypothesis: {{HYPOTHESIS}}
- Repo root: `{{REPO_ROOT}}`
- Candidate worktree: `{{WORKTREE}}`
- Prototype worktree: `{{PROTOTYPE_WORKTREE}}`

## Evidence

{{EVIDENCE_PATHS}}

## Task

Design how this experiment should integrate into the derivation pipeline as a
real treatment, not a sidecar demo.

Specify:

- files to modify
- new modules and prompts
- CLI flags or modes
- per-iteration artifacts
- batch-level metrics
- failure statuses
- backfill/coalesce implications
- pilot commands
- full A/B commands

## Rules

- Existing production behavior remains the control.
- The treatment must be explicit and opt-in.
- Do not silently fall back from treatment to control.
- Do not bypass normal verifier, canvas, target, and judge gates when reporting
  acceptance.
- Do not allow target-specific plans except as golden fixtures.

## Required Output

Return:

- concrete integration plan
- artifact contract
- failure/metric contract
- pilot and full A/B commands
- explicit list of things not to do
