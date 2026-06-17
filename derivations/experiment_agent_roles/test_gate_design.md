# Test Gate Design

You are a headless test-design agent. Do not edit files.

## Experiment

- Experiment id: `{{EXPERIMENT_ID}}`
- Hypothesis: {{HYPOTHESIS}}
- Repo root: `{{REPO_ROOT}}`
- Candidate worktree: `{{WORKTREE}}`
- Prototype worktree: `{{PROTOTYPE_WORKTREE}}`

## Evidence

{{EVIDENCE_PATHS}}

## Task

Design the minimum verification gates required before this experiment can spend
real workload calls.

Cover:

- unit tests for schema validation and deterministic execution
- local integration tests for the alternate mode
- control canaries proving the existing mode is unchanged
- unsupported target/tactic accounting
- malformed model-output handling
- artifact layout compatibility
- golden regression fixtures from introspection reports
- exact smoke commands and artifact assertions

## Rules

- The tests must distinguish a generic mechanism from a target-specific patch.
- Unsupported coverage must count as treatment failure or coverage gap, not as
  skip/pass.
- The expensive real workload is not a test substitute.

## Required Output

Return:

- test checklist with proposed test names and file locations
- smoke commands
- required artifact assertions
- blockers that must be fixed before implementation, if any
