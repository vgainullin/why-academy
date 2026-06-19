# Task: Outer-Loop Epoch — Analyze and Propose Validator/Rule Updates

Analyze accumulated inner-loop failure logs, identify systematic gaps in the validator and rule library, and draft a prioritized proposal for human review. **Do not implement changes in this task.** Implementation is a separate, gated step.

## Context

This is the outer loop of the derivation auto-research pipeline. The inner loop (`generate_derivation` task) produces logs of per-edge pass/fail results across many derivations. This task aggregates those logs, identifies patterns, and proposes specific code/rule changes that would strengthen verification.

**Critical invariant:** the outer loop is the human-in-the-loop layer. It proposes; humans dispose. Auto-implementing validator changes would close the loop on itself and produce a self-deluding system. Stop at the proposal stage.

Project layout:

```
derivations/
  logs/                 # <-- read these
    epoch_<NNN>/
      run_<UUID>.jsonl  # one line per generation attempt
  problems/             # accepted derivations (read for context)
  rule_library/         # current rule definitions (read-only this task)
  validators/           # current validator implementations (read-only this task)
  test_corpus/          # curated +/- examples per rule (read-only this task)
  reports/              # <-- write the proposal here
```

## Inputs (substituted by the outer-loop wrapper)

- `EPOCH_RANGE = <<EPOCH_RANGE>>` — log directories to analyze. Format: `epoch_042..epoch_048` or `since:2026-05-01`.
- `MAX_PROPOSALS = <<MAX_PROPOSALS>>` — cap on proposals to draft this epoch. Outer loop should be deliberate, not exhaustive.

## Workflow

### 1. Aggregate logs

Read all `.jsonl` files in the specified epoch range. Each line is a generation attempt record:

```json
{
  "timestamp": "...",
  "problem_id": "...",
  "prompt_version": "v3",
  "validator_library_version": "v7",
  "edge_results": [
    {"from": "n0", "to": "n1", "rule": "u_substitution", "status": "PASS|FAIL|UNCOVERED|WEAK_PASS", "reason": "..."}
  ],
  "canvas_check": {"summary": {...}, "n_duplicates": N, "duplicates": [...]} | null,
  "judge_eval":   {"overall": "PASS|FAIL", "verdicts": {...}} | null
}
```

Build a single in-memory aggregate. Do not write intermediate files unless analysis is too large (>100MB of logs); if it is, paginate.

### 2. Categorize failures

This pipeline does not maintain a separate rule library; the existence of `derivations/validators/<rule>.py` is the source of truth for whether a rule has coverage. Categorize each non-PASS edge and each non-PASS attempt-level signal:

**Edge-level (one category per non-PASS edge):**

- `PARSE_FAILURE`: srepr didn't evaluate. Indicates prompt-level issue, not validator-level. Flag for prompt update, not validator work.
- `VALIDATOR_UNCOVERED`: no validator at `derivations/validators/<rule>.py`. Candidate for new validator. Rule names with no validator that recur across many edges are the cleanest signal for `NEW_VALIDATOR` proposals.
- `VALIDATOR_REJECTED`: validator ran and said no. Two sub-cases:
  - True positive (LLM misused the rule) → prompt-level signal, skip
  - False positive (transformation is actually valid) → candidate for validator weakening or refinement
  - This distinction requires human review per case; flag both but mark as "needs adjudication"
- `WEAK_PASS_ONLY`: passed truth-preservation fallback but not a rule-specific check (== VALIDATOR_UNCOVERED, since with no rule library these are the same condition). Aggregate them together; prefer `VALIDATOR_UNCOVERED` as the primary label.

**Attempt-level (zero or one per attempt):**

- `CANVAS_DUPLICATE`: `canvas_check.n_duplicates > 0`. Two or more nodes in the graph rendered to the same LaTeX -- almost always sympy auto-simplification eating a pedagogically-distinct step. Surface as a prompt-level signal (the LLM needs to avoid the offending construction). Do not propose validator work.
- `JUDGE_REJECTED`: `judge_eval.overall == "FAIL"`. The math was correct but the derivation failed a pedagogical rubric criterion (one-rule-per-edge, given-facts-visible, etc.). Sub-categorize by which judge criterion failed; concentrated single-criterion failures across many attempts are the cleanest signal for prompt-level updates. Do not propose validator work for these -- they're prompt-engineering candidates.

### 3. Rank by impact

For each category, compute:

- **Frequency**: how many edges across the epoch range
- **Breadth**: how many distinct problems affected
- **Concentration**: is this one rule dominating, or spread across many?

Rank candidates by `frequency × log(breadth)`. Concentrated single-rule issues outrank diffuse multi-rule ones — they're cheaper to fix and unblock more.

### 4. Draft proposals

For the top `<<MAX_PROPOSALS>>` candidates, draft a proposal. Each proposal lives at `derivations/reports/epoch_<NNN>/proposal_<NN>_<kind>.md` with this structure:

```markdown
# Proposal <NN>: <one-line title>

**Kind**: NEW_RULE | NEW_VALIDATOR | STRENGTHEN_VALIDATOR | WEAKEN_VALIDATOR | INVESTIGATE
**Affected rule**: <rule_id or "none">
**Frequency**: <n edges in epoch range>
**Breadth**: <n distinct problems>
**Priority**: <1-5, 1 = highest>

## Observation

<What the logs show. 2-4 sentences. Reference specific problem ids and edges.>

## Hypothesis

<Why this is happening. One paragraph.>

## Proposed change

<Concrete description of the change. For new validators, include a code sketch
(20-100 lines of Python) showing the intended pattern-match logic. Do not
write this to disk yet — embed in the proposal.>

## Test cases required

<List 5-10 +/- examples that the new/strengthened validator must handle.
For each: brief description and expected pass/fail. The human reviewer
should be able to use this list to extend test_corpus/ when approving.>

## Risk

<What could go wrong. Specifically: what existing edges might regress.
Reference any specific problems that currently pass with the weak/old
validator and might fail with the new one.>

## Open questions for review

<Anything you couldn't decide. Be explicit.>
```

### 5. Write the epoch summary

Create `derivations/reports/epoch_<NNN>/summary.md` with:

```markdown
# Outer-Loop Epoch <NNN> Summary

**Range**: <<EPOCH_RANGE>>
**Logs analyzed**: <n generation attempts>
**Total edges**: <n>
**Pass rate overall**: <pct> (target: trending up)
**Pass rate, strong validators only**: <pct> (target: trending up)
**Weak-pass-only fraction**: <pct> (target: trending down)

## Failure distribution

Edge-level:

| Category | Count | % of failures | Top affected rules |
|----------|-------|---------------|---------------------|
| PARSE_FAILURE       | <n> | <%> | <rule, rule> |
| VALIDATOR_UNCOVERED | <n> | <%> | <rule, rule> |
| VALIDATOR_REJECTED  | <n> | <%> | <rule, rule> |

Attempt-level:

| Signal | Count | % of attempts | Top patterns |
|--------|-------|---------------|---------------|
| CANVAS_DUPLICATE | <n> | <%> | <pattern, pattern> |
| JUDGE_REJECTED   | <n> | <%> | <which criterion, which criterion> |

## Proposals drafted

1. <Proposal 01 title> — <kind> — priority <N>
2. ...

## Trends vs last epoch

<If epoch_<NNN-1>/summary.md exists, compute deltas. Otherwise note "baseline epoch".>

## Held-out test set pass rate

<Read derivations/test_corpus/holdout/results_epoch_<NNN>.json if it exists.
Report pass rate and any regressions vs prior epoch. If file missing, note that
the held-out suite hasn't been run this epoch — that's a process gap to flag.>

## Recommended next actions

<2-4 sentences. Which proposals to prioritize, anything urgent (e.g. a sudden
regression in pass rate), and whether the held-out suite needs to run.>
```

### 6. Stop

Print the path to `summary.md` and the list of proposals. **Do not implement any of the proposals.** Do not edit `validators/`, `rule_library/`, or `verify.py`. Do not run tests against proposed changes — there's nothing to run against yet, since nothing was written.

Wait for the human reviewer to either:
- Approve specific proposals (separate Claude Code task `implement_proposal $PATH` will be invoked per approved item)
- Request revisions to specific proposals
- Reject and provide reasoning that should inform the next epoch

## Done criteria

- `derivations/reports/epoch_<NNN>/summary.md` exists with all required sections
- One proposal file per top-K candidate, all using the schema above
- No files outside `derivations/reports/` modified
- Console output gives the human reviewer everything needed to start review

## Hard constraints

- **No implementation.** The temptation to "just go ahead and write the validator" is exactly the failure mode this loop is designed to prevent. The strength of the auto-research framework comes from the gate at this step.
- **Never draft `Kind: BUGFIX` here.** BUGFIX proposals are reserved for the BUG_INVESTIGATE phase, which emits them only from a seed hypothesis with a confirmed reproduction case. The outer loop works from aggregate evidence and must not claim a confirmed reproduction. If you believe a candidate is a confirmed bug with a reproduction case, draft it as `INVESTIGATE` and flag it as a seed-hypothesis candidate for the bug-investigate config.
- **No prompt-level fixes here.** PARSE_FAILURE and VALIDATOR_REJECTED true-positives belong in the inner-loop prompt update, which is a separate concern handled at a different cadence. Note them in the summary but do not propose prompt changes here.
- **Cite specific evidence.** Every proposal must reference at least 3 concrete log entries (problem_id + edge). No abstract "the LLM sometimes does X" — anchor everything in observed data. If you can't find 3 concrete examples, the candidate isn't ranked high enough yet.
- **Don't conflate categories.** If a rule shows up in both VALIDATOR_UNCOVERED and WEAK_PASS_ONLY across the epoch, those are two different proposals (write the validator vs. strengthen the fallback). Don't merge.
- **Held-out suite is sacred.** If you find yourself wanting to propose changes that would specifically make held-out tests pass, stop. That's the contamination path. The held-out suite measures reality; proposals should be motivated by inner-loop logs only.
- **Cadence discipline.** Outer-loop epochs should produce ≤5 proposals, even if the data could support more. Better to ship 3 carefully-vetted validator changes per epoch than 15 hasty ones.

## Notes for Claude Code

- This task is read-heavy and write-light. Most of the work is in analysis. Don't rush to draft proposals before the categorization and ranking are solid.
- Threshold for drafting proposals is **evidence-based, not volume-based**. Draft a proposal if EITHER:
  - The range has ≥100 generation attempts (the historical floor), OR
  - A specific rule has ≥5 fail/uncovered edges across ≥3 distinct problems AND across ≥2 distinct batches (cross-batch consistency means the signal isn't single-batch noise even at lower total volumes).
  - If neither condition holds for any candidate, report that and stop. Drafting from genuine cross-batch consistency is fine; drafting from a single batch's idiosyncrasies is not.
- If logs are too dense to analyze in one pass (millions of entries), build a sampling strategy and document it in the summary. Sampling is fine; pretending you read everything when you didn't is not.
- The proposal documents are the deliverable. Take time on them. They're what the human reviewer engages with for the next several hours of decision-making.
