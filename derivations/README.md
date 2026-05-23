# Derivation Research Pipeline

## Problem

Why Academy needs a large library of correct, teachable derivations.

Hand-writing every derivation does not scale. Raw LLM derivations are not safe
to publish. A symbolic checker can reject bad math, but it does not discover
new lesson material or improve the rule system by itself.

We are solving this problem: turn unreliable generated derivations into
verified curriculum knowledge, or into useful failure data.

## Why We Need It

The student product should stay deterministic. Students derive in the browser;
their work is checked by local symbolic machinery, not by an AI grader.

LLMs are useful here only as proposal engines. They can explore many possible
derivation targets, but every output must pass deterministic and inspectable
gates before it can matter.

## How It Fits

This pipeline is offline research infrastructure for the lesson system.

Accepted graphs can become lesson content. Rejected graphs become evidence for
better prompts, validators, rule contracts, and future contribution jobs.

The long-term shape is distributed exploration: many small LLM runs search
unexplored derivation space; the central system accepts only artifacts that
survive verification.

## Loop

```text
target
-> generated derivation graph
-> graph normalization
-> symbolic verifier
-> canvas check
-> target check
-> pedagogical judge
-> accepted artifact or labeled failure
-> prompt / validator evolution
```

## What Counts As Progress

- accepted graph for a target
- repeated failure converted into a regression test
- validator/rule improvement with no holdout regression
- evolved prompt variant improves a later attempt
- hard target reuses prior failure memory and moves closer to acceptance

## Current State

Implemented:

- JSON graph generation
- safe SymPy parsing
- rule validators and truth checks
- graph normalization
- canvas, target, and judge gates
- failure diagnosis and transition scoring
- batch distillation reports
- small e2e probes for repair and memory

The system can generate, reject, repair, and sometimes accept derivations.

## Where We Are Stuck

The main blocker is proof-graph quality.

Generated graphs are often mathematically close but structurally bad:
duplicate equivalent nodes, fused multi-step edges, invented rule names, or
goals that are near the requested target but not exact.

Current weak points:

- canonicalization is not strong enough before canvas and judge
- one-rule-per-edge is enforced too late
- calculus and physics need better primitive rule contracts
- cross-run learning is proven only in small probes
- distributed contribution jobs are not yet a complete trust protocol

## Next Work

Build a canonical proof-graph layer:

- canonicalize every node before all gates
- merge duplicate/equivalent nodes
- rewrite edges to canonical ids
- drop self-edges and redundant edges
- enforce one-step edges before judge

Then run fixed benchmark cohorts so we can separate real learning from churn.

## Related

- `derivations/DISTILLATION.md`: distillation and worker contract
- `derivations/prompts/outer_loop_epoch.md`: validator proposal loop
- `scripts/e2e_learning_probe.py`: e2e repair/memory proof harness
