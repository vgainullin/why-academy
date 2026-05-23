# Structured Derivation Distillation

Why Academy's derivation pipeline is a structured knowledge distillation loop:

```text
LLM latent knowledge
-> explicit derivation graph
-> symbolic verifier
-> canvas compatibility check
-> independent pedagogical judge
-> failure-labeled corpus
-> prompt / validator evolution
-> reusable curriculum object
```

The purpose is not to trust generated content. The purpose is to force every
candidate through typed, inspectable bottlenecks until it becomes either a
reusable lesson artifact or a useful failure record.

## Frontier

Build a deterministic frontier from the queue and local JSONL logs:

```bash
scripts/distill.sh frontier \
  --queue derivations/targets/queue.txt \
  --out derivations/frontier/frontier.json \
  --markdown derivations/frontier/frontier.md
```

The frontier labels each target as:

- `unexplored`: no local attempts yet
- `explored_unaccepted`: attempts exist, but none accepted
- `distilled`: at least one accepted attempt exists

It also records failure taxonomy counts (`verify_fail`, `canvas_fail`,
`judge_fail`, `unjudged`) and priority scores for future exploration.

## Contribution Jobs

Emit small, shareable work units for donated-token workers:

```bash
scripts/distill.sh jobs \
  --queue derivations/targets/queue.txt \
  --out derivations/frontier/jobs.jsonl \
  --inner-engine codex --inner-model gpt-5.2 \
  --judge-engine deepseek --judge-model deepseek-v4-flash \
  --evolve-engine codex --evolve-model gpt-5.2
```

Each job captures:

- target text and target hash
- prompt / validator / config versions
- prompt file hashes
- engine plan
- expected output sidecars
- isolation assumptions

This is the minimum contract needed for a future distributed worker to run one
target, return artifacts, and let the central verifier decide whether to accept
anything.

## Batch Summaries

Summarize a completed batch into JSON and Markdown:

```bash
scripts/distill.sh summarize-batch codex_full_loop_20260515_002
```

Batch summaries are intended for human review and experiment tracking. The
canonical machine dataset remains the backfilled JSONL in
`derivations/logs/epoch_*/batch_<batch_id>.jsonl`.

## Cross-Run Evolution

Each target's local prompt variants are durable. Before a new batch starts a
target, `inner_evolve.py` searches prior batches for the best variant for the
same target and seeds iteration 0 from that variant instead of the canonical
prompt. This lets a hard target continue evolving across batches even when the
previous batch did not reach acceptance.

Global prompt promotion is still conservative: `coalesce.py` reports addenda
from all chains, but `promote_prompt.sh` only promotes addenda that appear in
accepted variants and pass human review.

## Failure-Conditioned Repair

Every repairable failure gate is normalized into a `failure_diagnosis.json`
record:

- verifier failures (`rule_fail`, `parse_error`)
- canvas failures (`parse_out`, `render_error`, `duplicate_forms`)
- judge failures (`given_facts_visible`, `one_rule_per_edge`)

When iteration budget remains, the same target can now evolve from verifier and
canvas failures, not only judge failures. The next iteration records
`transition_score.json`, which compares the prior diagnosis to the new outcome.
This lets the system distinguish acceptance, improvement, same-gate movement,
and regression before any addendum is considered for reuse or promotion.

## Trust Boundary

Generated graph expressions are untrusted input. `sympy_eval.py` intentionally
parses only a small SymPy expression subset and evaluates with no Python
builtins. Donated outputs must still run in a sandbox and must never be promoted
without verifier, canvas, judge, and human-audit gates appropriate to the use
case.
