# Task: Bug Investigation Candidate

You are running the BUG_INVESTIGATE branch for one candidate selected by the
outer-loop meta-analysis. Your job is to inspect the candidate and referenced
evidence, then write a structured result. Do not implement fixes.

## Candidate

```json
<<CANDIDATE_JSON>>
```

## Evidence

```json
<<EVIDENCE_JSON>>
```

## Output Directory

Write artifacts only under:

```text
<<EPOCH_REPORT_DIR>>
```

## Required Result

Write this JSON file:

```text
<<RESULT_PATH>>
```

Schema:

```json
{
  "status": "BUGFIX_CANDIDATE | INVESTIGATE | FEATURE_GAP | NO_REPRO | NO_ACTIONABLE_BUGFIX",
  "recommended_route": "CONTINUE_EPOCH | IMPLEMENT | EXPERIMENT | CLOSE",
  "rationale": "<short explanation grounded in evidence>",
  "candidate": {},
  "evidence_refs": [],
  "proposal_paths": []
}
```

Use statuses this way:

- `BUGFIX_CANDIDATE`: you produced an actionable `proposal_bug_*.md` with a
  concrete reproduction that the current closure harness can replay:
  - validator bug: `from_srepr`, `to_srepr`, `args`, `expected`, `actual`;
  - judge/system bug: a fenced JSON object containing `judge_eval.verdicts`
    and `judge_eval.overall`, plus any explicit expected outcome.
- `INVESTIGATE`: the pattern is real but not actionable enough for a bugfix.
- `FEATURE_GAP`: the system lacks a capability rather than containing a bug.
- `NO_REPRO`: the evidence does not reproduce or support the hypothesis.
- `NO_ACTIONABLE_BUGFIX`: no focused bugfix should be attempted.

If you write `BUGFIX_CANDIDATE`, also write a proposal file under the same
directory. Name it `proposal_bug_<short_id>.md`.

Proposal schema:

```markdown
# Bug Investigation Proposal: <short title>

**Kind**: BUGFIX | INVESTIGATE
**Affected rule**: <rule id or none>
**Seed hypothesis**: <candidate id or short slug>

## Hypothesis

...

## Evidence

...

## Reproduction case

Include this section only if the reproduction is concrete enough for
`closure_test.sh` now.

For validator bugs, use bullet fields:

```markdown
- from_srepr: ...
- to_srepr: ...
- args: {...}
- expected: PASS
- actual: FAIL
```

For judge/system bugs, set `Affected rule` to `none` and include a fenced JSON
fixture:

```json
{
  "judge_eval": {
    "verdicts": {
      "one_rule_per_edge": {"verdict": "PASS"},
      "given_facts_visible": {"verdict": "SKIP"},
      "target_goal_reached": {"verdict": "PASS"}
    },
    "overall": "FAIL"
  },
  "expected": {"overall": "PASS"}
}
```

If you cannot provide one of those replayable forms, do not mark the result
`BUGFIX_CANDIDATE`; use `INVESTIGATE` or `NO_ACTIONABLE_BUGFIX`.

## Proposed change

...

## Risk

...
```

For `INVESTIGATE`, `FEATURE_GAP`, `NO_REPRO`, or `NO_ACTIONABLE_BUGFIX`, do not
write a proposal unless it adds clear human-review value. Set
`recommended_route` to `CONTINUE_EPOCH` unless there is a concrete reason to
route elsewhere. When you do write a bug proposal, the epoch controller returns
to meta-analysis so the outer loop can decide whether to implement it.

## Constraints

- Do not edit validators, rule libraries, prompts, state, tests, or source code.
- Do not run implementation commands.
- Ground all claims in the provided candidate and evidence.
- If the evidence is insufficient, say so and choose a non-actionable status.
