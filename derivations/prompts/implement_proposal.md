# Task: Implement an Approved Proposal

You implement ONE specific, human-approved outer-loop proposal. The proposal describes a single change to the validator library; you write the code and the test cases the proposal calls for, then verify no regression against the held-out suite.

**Critical:** this is the only task in the entire pipeline that modifies validator code. The pipeline's integrity depends on the discipline of *stopping at the proposal stage*. By the time you're invoked, a human has read the proposal and chosen to ship it. Implement exactly what the proposal specifies. Do not extend scope.

## Input

Proposal path: `<<PROPOSAL_PATH>>`

## Workflow

### 1. Read and verify the proposal

Read `<<PROPOSAL_PATH>>`. Confirm it has the required sections:
- `Kind` (NEW_VALIDATOR / STRENGTHEN_VALIDATOR / WEAKEN_VALIDATOR / INVESTIGATE)
- `Affected rule` (the rule_id this proposal addresses)
- `Proposed change` (a concrete description, with a code sketch for validator changes)
- `Test cases required` (a list of +/- examples)

If any section is missing or empty, **stop** and print:
```
PROPOSAL INCOMPLETE: <which section is missing>
```
Do not implement. Do not write any files. The proposal author must revise.

If `Kind` is `INVESTIGATE`, stop and print `KIND IS INVESTIGATE — no implementation step exists; the proposal is for human follow-up.`

### 2. Implement the validator

For `NEW_VALIDATOR`:
- Write `derivations/validators/<rule>.py` based on the code sketch in the proposal.
- The file must export:
  - `RULE_NAME` (str, matching `Affected rule`)
  - `validate(from_expr, to_expr, args)` returning a tuple `(status, reason)` where `status` is `"PASS"` or `"FAIL"`.
- Use `from sympy import ...` for sympy primitives and `from sympy_eval import parse_arg` to coerce `args` values into sympy expressions (matches the namespace verify.py uses).
- `validate()` must never raise — wrap in try/except and return `("FAIL", f"validator raised: {e}")`.

For `STRENGTHEN_VALIDATOR` / `WEAKEN_VALIDATOR`:
- Edit the existing `derivations/validators/<rule>.py` per the proposal.
- Preserve the `RULE_NAME` and `validate()` signature.

### 3. Write the test corpus

For each `+` example in `Test cases required`: write to `derivations/test_corpus/<rule>/positive.json`.
For each `-` example: write to `derivations/test_corpus/<rule>/negative.json`.

Schema (one file per polarity, each is a JSON list):
```json
[
  {
    "description": "<one-line summary>",
    "from_srepr": "Eq(...)",
    "to_srepr": "Eq(...)",
    "args": {...},
    "expected": "PASS" | "FAIL"
  }
]
```

Use the same sympy_srepr conventions as `problems/`. The held-out test runner consumes these.

### 4. Regression-check against the held-out suite

Run:
```
scripts/holdout.sh
```

If any holdout problem changed from PASS to FAIL — STOP. Print the regression, revert your validator file change, and report:
```
REGRESSION: <which holdout problem failed>
REVERTED:   <which file>
```

The proposal's "Risk" section should have anticipated this; if it didn't, the proposal needs revision.

### 5. Report

```
IMPLEMENTED: <rule_name>
KIND:        <kind>
FILE:        derivations/validators/<rule>.py  (N lines)
TESTS:       derivations/test_corpus/<rule>/  (P positive, N negative)
HOLDOUT:     PASS (no regression vs previous epoch)
```

The `validator_version` bump in `derivations/state.json` is handled by the implement.sh wrapper after this task completes successfully. Do not modify `state.json`.

## Hard constraints

- **One proposal per invocation.** Do not chain multiple implementations.
- **Do NOT modify** `verify.py`, `canvas_check.py`, `judge.py`, `to_canvas.py`, `sympy_eval.py`, `state.json`, or any file under `prompts/`. The proposal scope is the validator and its test corpus; everything else is out of scope.
- **Do NOT add scope beyond the proposal.** If the proposal lists 7 test cases, write 7. If you think 3 more would help, surface that in your report as a follow-up suggestion — don't silently add them.
- **Do NOT close the loop.** You implement; you do not run inner-loop generations or outer-loop epochs. The human reviews the implementation and decides when to run the next epoch.
- **If anything is ambiguous, stop and report.** Forcing a guess at this step is exactly the failure mode the outer-loop gate exists to prevent.
