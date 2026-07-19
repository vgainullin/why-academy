# Derivation Research Pipeline

> **Research status (2026-07-19): failed approaches.** Neither the autonomous
> epoch pipeline nor the typed/modular refactor demonstrated trustworthy
> autoderivation, system learning, or improved learning-example synthesis.
> Historical acceptance and lift metrics must not be treated as evidence of
> progress. See [FAILURE_ANALYSIS.md](FAILURE_ANALYSIS.md).

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

Implemented mechanisms include:

- JSON graph generation
- safe SymPy parsing
- rule validators and truth checks
- graph normalization
- canvas, target, and judge gates
- failure diagnosis and transition scoring
- batch distillation reports
- small e2e probes for repair and memory

These mechanisms have not produced a trustworthy end-to-end result. The active
archive branch fails six of ten acceptance-gate contract tests. Its recorded
experiments contain zero treatment wins and zero promotions. The later
typed/modular branches pass their unit suites but have not demonstrated
autonomous learning or improved example synthesis.

## Where We Are Stuck

The blocker is not proof-graph quality. The research loop itself has not
provided valid evidence:

- the original target gate fails open on unsupported targets;
- validator lift compares different stochastic candidates;
- the original A/B does not compare candidate code with baseline code;
- run artifacts are ignored and core model identities are unpinned;
- the typed/modular refactor proves interfaces but not real synthesis;
- no located real experiment shows a treatment win.

## Next Work

Do not extend either architecture until a tracked, frozen evaluation contract
exists. The minimum restart criteria are documented in
[FAILURE_ANALYSIS.md](FAILURE_ANALYSIS.md#minimum-evidence-required-before-another-attempt).

## Experiment Gates

Every system alteration should move through reusable headless-agent gates before
it spends real workload calls:

- code-review gate
- test-gate design
- integration design
- implementation
- postbuild review
- pilot runner
- A/B analysis

The role specs live in `derivations/experiment_agent_roles/`. Render a gate
packet with:

```bash
scripts/experiment_agents.sh render \
  --experiment-id tactic_inner_mode \
  --hypothesis "typed tactic plans plus deterministic execution reduce fused-edge failures" \
  --worktree /path/to/experiment/worktree \
  --evidence /path/to/batch_metrics.json \
  --evidence /path/to/introspection.json
```

The generated prompts are written under
`derivations/_evolutions/experiment_agents/<experiment_id>/`.

## Evaluation Artifacts

Autonomous implementation writes structured evaluation artifacts under
`derivations/reports/epoch_<NNN>/evals/`.

- Proposal changes use `evals/<proposal_stem>/eval_plan.json`,
  `change_manifest.json`, and `eval_verdict.json`.
- BUGFIX proposals use the `bugfix_reproduction_replay` adapter: replay the
  concrete reproduction case, run holdout, then write regression corpus entries
  only after promotion.
- Validator proposals use the `validator_lift_replay` adapter: replay the
  affected rule's previously failing targets and compare lift against the
  configured promotion gate.
- Prompt proposals use the `prompt_promotion` adapter.
- Pipeline experiments use the `pipeline_mode_ab` adapter and write
  `evals/<experiment_id>/eval_plan.json` plus `eval_verdict.json` alongside
  the legacy `experiment_verdict.json`.

For a completed paired control/treatment run, render the A/B introspection gate
directly from the batch directories:

```bash
scripts/experiment_agents.sh render-ab-analysis \
  --control derivations/_evolutions/batches/<control_batch> \
  --treatment derivations/_evolutions/batches/<treatment_batch>
```

This validates the required batch and comparison artifacts, discovers the
relevant target/iteration evidence, and writes an `ab_analysis` packet. To run a
rendered role through the headless agent runner:

```bash
scripts/experiment_agents.sh run-role \
  --packet derivations/_evolutions/experiment_agents/<experiment_id>_ab_analysis/packet.json \
  --role ab_analysis \
  --sandbox read-only
```

Derive the next falsifiable system step from a completed analysis artifact:

```bash
scripts/experiment_agents.sh render-next-step \
  --analysis derivations/_evolutions/experiment_agents/<experiment_id>_ab_analysis/ab_analysis_result.txt \
  --evidence derivations/_evolutions/batches/<treatment_batch>/ab_comparison.json
```

Rendered packets include prompt and evidence hashes. Verify a packet before
handing it to another agent:

```bash
scripts/experiment_agents.sh verify-packet \
  --packet derivations/_evolutions/experiment_agents/<experiment_id>_next_step/packet.json
```

To test whether the same model makes a stable next-step decision, run repeated
replicates against the same packet:

```bash
scripts/experiment_agents.sh run-reproducibility \
  --packet derivations/_evolutions/experiment_agents/<experiment_id>_next_step/packet.json \
  --model gpt-5.5 \
  --reasoning-effort xhigh \
  --runs 3
```

The reproducibility gate parses the required JSON decision summary and compares
declared/inferred decision tags, not raw wording. It fails if the next-step
concept or `next_step_ready` verdict diverges. Existing outputs can be compared
without rerunning the model:

```bash
scripts/experiment_agents.sh compare-next-step \
  --output /path/to/run_01.txt \
  --output /path/to/run_02.txt
```

Compare expensive outer-loop meta-analysis models from an immutable checkpoint:

```bash
scripts/meta_model_compare.sh freeze \
  --name epoch_008_outer_b862 \
  --prompt derivations/reports/epoch_008/run_b862a468-5b5e-4ba3-a94b-2a2d0ad2cbb9.prompt.md \
  --log derivations/logs/epoch_008/batch_epoch_008_20260628_095140.jsonl \
  --log derivations/logs/epoch_008/batch_epoch_008_20260628_100528.jsonl \
  --baseline-console derivations/reports/epoch_008/run_b862a468-5b5e-4ba3-a94b-2a2d0ad2cbb9.console.log \
  --baseline-decision derivations/reports/epoch_008/analysis_decision.json

scripts/meta_model_compare.sh run \
  --packet derivations/_evolutions/meta_model_comparisons/epoch_008_outer_b862/packet.json \
  --arm gpt55_xhigh \
  --model gpt-5.5 \
  --reasoning-effort xhigh

scripts/meta_model_compare.sh compare \
  --packet derivations/_evolutions/meta_model_comparisons/epoch_008_outer_b862/packet.json
```

The comparison is valid only when every arm uses the same packet input digest,
the same frozen workspace, explicit model and reasoning settings, and an
uncontaminated epoch log directory. The report intentionally does not pick a
subjective winner; it scores schema validity, generated artifacts, route fields,
proposal paths, and contamination guards.

## Related

- `derivations/FAILURE_ANALYSIS.md`: audited outcome of both attempted architectures
- `derivations/DISTILLATION.md`: distillation and worker contract
- `derivations/prompts/outer_loop_epoch.md`: validator proposal loop
- `scripts/e2e_learning_probe.py`: e2e repair/memory proof harness
