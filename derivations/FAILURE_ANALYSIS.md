# Case Study: Two Failed Attempts at Autonomous Derivation and Learning-Example Synthesis

**Audit date:** 2026-07-19

**Scope:** autonomous derivation and learning-example synthesis only

**Branches examined:**

- `feature/archive-e2e-autonomous-derivation` at `4b9015e`;
- `feature/typed-derivation-contracts` at `492fcfa`;
- `feature/modular-evolution-kernel` at `8e1fe21`.

**Project-result verdict:** total loss against the stated objective. Neither
approach demonstrated trustworthy autonomous derivation, learning from prior
attempts, improved example synthesis, or transferable cross-domain operation.

This case study does not assess any student-facing product. It is exclusively
about the attempted research system.

## Executive Summary

The project set out to build an autonomous research loop for creating verified,
teachable derivations and learning examples. The intended analogy was not a
simple content generator. It was closer to autoresearch or AlphaEvolve: propose
candidate artifacts, evaluate them against a trusted objective, learn from the
failures, change the system, and retain only changes that measurably improve
future results.

The first implementation used a large, tightly coupled derivation pipeline. An
LLM generated proof graphs. A sequence of symbolic and pedagogical gates judged
them. Failures produced repair prompts and cross-run memory. An outer agent then
aggregated failures, proposed changes to prompts or validators, implemented
those changes, and attempted to promote or revert them through closure tests and
A/B experiments.

That approach failed at its foundation. Its deterministic target gate could
return success while skipping target validation. Its validator-lift test
compared different stochastic generations rather than the same evidence before
and after a change. Its pipeline A/B compared generation modes inside the same
already-mutated workspace rather than candidate code against baseline code.
Critical artifacts were ignored by Git, several model identities were inherited
from ambient configuration, and the recorded experiments produced zero
treatment wins and zero promoted improvements.

The second approach was a refactor around typed contracts, a frozen evaluator,
and then a domain-neutral evolution kernel. This was intended to separate the
candidate, the trusted oracle, the experiment machinery, and domain-specific
semantics. The typed pilot improved the trust boundary for one narrow linear
equation workflow. The modular kernel established reusable interfaces for
evidence and comparison.

The refactor still failed against the objective. Its passing tests mainly proved
serialization and protocol conformance. The only located real typed run covered
one task. The supposed cross-domain proof constructed candidates directly from
private expected answers and supplied fabricated all-pass verifier evidence. A
generic Grade 8 adapter weakened the typed pilot's trust boundary by accepting a
producer-supplied verifier. The two located real modular experiments showed no
treatment improvement, and no autonomous learning loop existed around the new
kernel.

The first approach built an untrustworthy learning loop. The second built safer
pieces of an evaluation system but did not build or prove the learning loop.
Neither produced a research result.

## 1. The Objective

### 1.1 The practical problem

The system needed to synthesize a large library of correct, teachable
derivations and learning examples. Manually authoring every example would not
scale. Raw LLM output was unacceptable because mathematical plausibility is not
the same as correctness, and correctness alone is not the same as a useful
pedagogical derivation.

The desired output was therefore not merely an answer. It was a structured
artifact containing:

- a defensible starting point;
- explicit intermediate states;
- one justified transformation per edge;
- a terminal state that actually answered the requested target;
- enough structure to render and interact with as curriculum;
- machine-checkable evidence supporting acceptance.

Rejected attempts were also supposed to have value. A failure should become
structured evidence that could improve the generator, prompt, rule system, or
validator on later attempts.

### 1.2 The research-loop objective

The intended system was:

```text
task distribution
-> candidate derivation or learning example
-> trusted domain evaluation
-> structured failure evidence
-> proposed system change
-> controlled evaluation against baseline
-> promote only reproducible improvements
-> use the improved system on later tasks
```

This required more than successful generation. The system had to demonstrate a
causal learning cycle:

1. identify a repeated failure;
2. propose a general change rather than a target-specific patch;
3. apply the change without contaminating the evaluator;
4. replay an unchanged evaluation workload;
5. measure an improvement attributable to that change;
6. verify no unacceptable regressions;
7. retain the change;
8. improve later synthesis.

Without that chain, the project would be a generator plus a collection of test
harnesses, not an autonomous research system.

### 1.3 The autonomy constraint

The final intended system could not depend on a human approving every candidate
or every system change. Human review might be acceptable while developing the
machinery, but it could not be the operating trust boundary. At scale, the
evaluation and promotion loop needed to be automatic.

That made evaluator independence essential. Removing a human from the loop is
safe only when the candidate-producing system cannot change, bypass, or
fabricate the evidence used to judge itself.

### 1.4 The modularity constraint

The same high-level components needed to support very different workflows. A
Grade 8 linear-equation derivation and a chaos-theory investigation should be
able to share:

- run identity and provenance;
- candidate invocation;
- immutable artifact storage;
- normalized evidence;
- experiment pairing and comparison;
- promotion policy.

They should not share domain semantics. Each domain needed to own its task
contract, hidden expected results, candidate schema, evaluator, and acceptance
criteria.

Modularity was therefore a means to reuse trustworthy research machinery. It
was not itself the project result.

### 1.5 What would have counted as success

| Required claim | Minimum evidence |
| --- | --- |
| Candidate correctness | Fail-closed domain oracle, independent of candidate output |
| Pedagogical validity | Explicit deterministic rubric or separately calibrated judge |
| Learning | A later candidate improves because of retained prior failure evidence |
| System improvement | Same frozen workload evaluated before and after one isolated change |
| Causality | Baseline and treatment differ only by the proposed change |
| Reproducibility | Pinned code, task, model, prompt, environment, and raw artifacts |
| Generality | A real generator and evaluator complete the same workflow in a second domain |
| Promotion | Repeated treatment wins with a predefined regression gate |

Neither approach produced this evidence.

## 2. Project Timeline

| Date | Stage | What changed |
| --- | --- | --- |
| 2026-05-23 | Original pipeline introduced | A 10,770-line, 152-file derivation research system was added, including generation, verification, repair, memory, outer analysis, autonomous implementation, holdouts, and epoch state. |
| 2026-05-31 to 2026-06-14 | Gate hardening | Graph validation, rule proof obligations, calculus rules, adversarial judging, and judge-impact measurement were added. |
| 2026-06-15 to 2026-06-16 | Experiment scaffolding | Tactic-mode pilots, headless experiment-agent roles, reviewer-parity tools, and rule-executor A/B machinery were added. |
| 2026-06-17 to 2026-06-28 | Autonomous orchestration expanded | The epoch state machine gained experiment, bug-investigation, structured evaluation, replay adapters, and model-comparison paths. |
| 2026-06-27 to 2026-06-28 | Eight recorded epoch experiments | Six neutral results and two control wins were recorded; no treatment won. |
| 2026-07-09 | Original approach archived | `4b9015e` archived the branch code and added a large deterministic Grade 8 corpus, but not the ignored historical run evidence. |
| 2026-07-09 to 2026-07-11 | Typed refactor | Frozen task contracts, a typed linear-equation oracle, isolated candidate workspaces, and a typed pilot were developed on a divergent branch. |
| 2026-07-16 to 2026-07-17 | Modular refactor | A domain-neutral kernel, evidence protocol, shared comparator, and Grade 8/chaos adapters were added on top of the typed branch. |
| 2026-07-19 | Audit | The current acceptance contract, experiment results, trust boundaries, branch topology, and real-run artifacts were reviewed together. |

The timeline matters because the later work was not one continuously validated
implementation. The archive and typed branches both diverged from `e0e6e49`.
The modular branch continued from the typed branch. The refactor did not inherit
a validated benchmark or proven learning result from the original approach.

## 3. Approach 1: Monolithic Autonomous Derivation Epochs

### 3.1 Theory of operation

The original architecture treated derivation synthesis as structured knowledge
distillation. An LLM's latent mathematical knowledge would be forced through a
sequence of inspectable representations and gates until the result became either
a reusable curriculum artifact or labeled failure data.

Its conceptual pipeline was:

```text
target text
-> model-authored derivation graph
-> graph normalization
-> symbolic parsing and rule verification
-> canvas compatibility check
-> target check
-> pedagogical judge
-> accepted graph or failure diagnosis
-> local repair and cross-run memory
-> outer failure aggregation
-> prompt / validator / system proposal
-> implementation
-> closure test and experiment
-> promotion or reversion
```

This was a reasonable high-level decomposition. The failure was not the idea of
using structured derivation graphs or multiple gates. The failure was how the
gates, learning mechanism, implementation mechanism, and experiment machinery
were coupled.

### 3.2 The candidate artifact

The model generated a JSON proof graph. Nodes contained symbolic expressions,
usually serialized as SymPy `srepr`. Edges named a transformation rule and
could carry rule arguments. The graph declared a `root_node` and `goal_node`.

This representation was intended to solve several problems at once:

- make every intermediate state explicit;
- prevent a correct final answer from hiding invalid reasoning;
- let each edge be checked against one rule;
- support branching derivations;
- render the result into a stepwise learning interface;
- attach machine-readable evidence to every transition.

The prompt encouraged existing rule names and warned against collapsing several
operations into one edge. In practice, models frequently produced fused steps,
invented rule names, duplicate equivalent nodes, parser-incompatible symbols,
or a plausible final equation that did not satisfy the exact requested target.

### 3.3 The inner generation and evaluation loop

For each target, `inner_evolve.py` could make multiple attempts. A successful
attempt moved through the following gates:

1. **Generation:** create the graph JSON.
2. **Normalization:** rewrite graph structure into a more consistent form.
3. **Verifier:** parse every node, check truth preservation, and apply
   rule-specific validators to edges.
4. **Canvas check:** reject graph forms that collapsed pedagogically distinct
   states or could not be rendered as intended.
5. **Target check:** compare the declared goal with a goal extracted from the
   target text.
6. **Pedagogical judge:** assess requirements such as visible givens and one
   rule per edge.
7. **Adversarial judge:** attempt to refute primary judge passes.

If a repairable gate failed, the system wrote a normalized failure diagnosis.
An evolution model then generated a local prompt addendum for the next attempt.
`transition_score.json` attempted to distinguish acceptance, improvement,
same-gate movement, and regression.

### 3.4 The intended learning mechanism

The approach had two learning timescales.

#### Within-target repair

A failed attempt produced a diagnosis and a prompt addendum. The next attempt
received the original prompt plus that addendum. This was meant to test whether
explicit feedback could repair the current derivation.

#### Cross-run memory

Prompt variants and transition results were stored under batch artifacts. When
the same target appeared in a later batch, the system could seed it with a prior
variant. The dedicated `e2e_learning_probe.py` classified runs with outcomes
such as:

- `PASS_ACCEPTED`;
- `PASS_IMPROVED`;
- `FAIL_NO_MEMORY`;
- `FAIL_NO_EVOLVE`;
- `FAIL_TARGET_DRIFT`;
- `FAIL_NO_IMPROVEMENT`.

This probe captured the right conceptual question: did prior failure evidence
actually improve a later run? No persisted probe outcome demonstrating that
claim was located in the audit.

### 3.5 The outer research loop

The original outer-loop prompt aggregated attempt logs, categorized failures,
ranked recurring problems, and drafted proposals for changes to validators or
rules. It required concrete evidence and warned against reacting to isolated
examples.

The later autonomous state machine expanded into:

```text
GENERATE
-> ANALYZE
-> optional BUG_INVESTIGATE
-> IMPLEMENT
-> EXPERIMENT
-> CLOSE
```

- `GENERATE` ran a target cohort.
- `ANALYZE` asked an outer model to summarize failures and choose a route.
- `BUG_INVESTIGATE` attempted to confirm suspected system bugs from repeated
  evidence.
- `IMPLEMENT` asked another model to change validators, prompts, or judge code.
- `closure_test.py` or an adapter evaluated the implementation.
- `EXPERIMENT` compared configured control and treatment generation modes.
- `CLOSE` advanced the epoch.

The runner was resumable and handled quotas, wall-clock limits, stale proposals,
and partial batches. This made it operationally elaborate, but operational
resilience did not make the evaluation valid.

### 3.6 The original safety contradiction

The initial outer-loop prompt contained a correct warning:

> Auto-implementing validator changes would close the loop on itself and produce
> a self-deluding system.

It described the outer agent as a human-in-the-loop proposal layer and treated
the held-out suite as sacred. Yet the same initial research-pipeline commit also
contained `autonomous_epoch.py`, whose `IMPLEMENT` phase automatically changed
validators and promoted or reverted them using a computed lift threshold.

This was the central unresolved contradiction:

- the system needed full autonomy;
- the original safety design depended on a human disposing of proposals;
- autonomy was added by removing that human gate;
- no independent, frozen evaluator replaced the human gate.

The system being optimized could change components involved in judging future
outputs. The closure test and holdout were therefore required to be exceptionally
strict and causally sound. They were not.

### 3.7 Why the approach initially appeared promising

Several local signals could look like progress:

- an invalid graph could fail a specific rule validator;
- a repair addendum could move a later attempt to a different gate;
- an adversarial judge could catch a pedagogical false pass;
- a tactic plan could prevent a fused edge;
- a validator bug could be reproduced and fixed;
- epoch summaries could show high edge-pass rates;
- the system could create detailed, inspectable artifacts.

For example, the June 15 tactic experiment compared direct JSON graphs with
typed tactic plans and deterministic execution. Both arms accepted 4 of 10
targets. The treatment avoided one fused substitution/simplification graph that
the control accepted, but it regressed another target and lacked tactic
coverage. The written conclusion correctly said it was not merge-ready.

This was useful diagnostic work, but it was later surrounded by increasingly
large orchestration. Movement between failure categories and successful
protocol execution began to substitute for proof that the system was learning.

## 4. Why Approach 1 Failed

### 4.1 Acceptance was not fail-closed

`target_check.py` returns exit code `0` with status `SKIP` when it cannot extract
a deterministic expected goal. `inner_evolve.py` treats a zero return code as a
successful target gate and proceeds to the LLM judge.

The current acceptance-contract test directly demonstrates the consequence:

```text
Ran 10 tests
FAILED (failures=6)
```

The failures show that the gate:

- accepts missing structured target evidence instead of returning an error;
- accepts a matching goal that is not terminal;
- accepts a matching goal that is unreachable from the root;
- accepts an edge with an unknown endpoint;
- fails to extract a context-implied isolate target;
- fails to extract a supported factorization target.

An accepted graph could therefore have correct-looking local edges and an LLM
judge pass without deterministic proof that the graph answered the requested
question. This contaminated every downstream acceptance rate that included the
skip path.

### 4.2 Local correctness was confused with task correctness

The verifier answered questions such as:

- can the expressions be parsed?
- does this edge preserve truth?
- is the named rule plausible for the transformation?

Those checks are necessary but insufficient. A graph can contain valid local
transformations while reaching the wrong terminal result, omitting required
givens, or declaring an unreachable goal. The target and topology gates were
supposed to close that gap. Because they did not fail closed, strong edge-pass
rates could coexist with invalid task-level acceptance.

This is why apparently strong validator metrics could not establish end-to-end
progress.

### 4.3 Validator lift was not causally measured

For validator proposals, `closure_test.py` found targets that previously had
failing edges for the affected rule. After applying a change, it launched a new
stochastic batch for those target texts. It then counted newly generated passing
edges with the same rule as resolved prior failures.

The test did not hold the candidate constant. The post-change model could emit:

- a different number of nodes;
- different rules;
- different edge boundaries;
- a different derivation strategy;
- no comparable failing edge at all.

The resulting `lift_fraction` compared historical failing-edge counts with
passing edges from different generated graphs. It could not distinguish a real
validator improvement from model variance, prompt drift, or a changed graph
shape. Nevertheless, `autonomous_epoch.py` could promote changes when this
fraction crossed the configured threshold.

### 4.4 The A/B tested the wrong difference

The implementation phase changed the workspace before the experiment phase.
The control and treatment batches then both ran against that already-mutated
workspace. Their main difference was generation mode, commonly `json` versus
`rule_executor`.

That can answer:

> Does generation mode B outperform generation mode A in the current workspace?

It cannot answer:

> Did the autonomously proposed code or prompt change improve the system over
> the unchanged baseline?

The project needed the second question. Its automated promotion narrative
implicitly relied on it, but the experiment implemented the first.

### 4.5 The evaluator was inside the adaptation loop

The outer system could propose and implement changes to validators, prompts, and
judge behavior. These same components influenced later acceptance and failure
evidence. A mutable evaluator is not automatically invalid, but changing it
requires a higher-order frozen oracle capable of deciding whether the evaluator
became more correct rather than merely more permissive.

The available holdout and closure machinery did not provide that guarantee. The
system could therefore improve its measured score by changing the measurement
surface instead of improving derivation quality.

This is the exact self-delusion risk identified by the original outer-loop
prompt.

### 4.6 Experiment evidence showed no improvement anyway

The eight locally recorded epoch experiments produced:

| Epochs | Control acceptance | Treatment acceptance | Result |
| --- | ---: | ---: | --- |
| 1-6 | 1.0 | 1.0 | neutral |
| 7 | 0.2 | 0.0 | control won |
| 8 | 0.6 | 0.2 | control won |

Totals:

- six neutral results;
- two control wins;
- zero treatment wins;
- zero promotions.

The structured evaluation-verdict inventory contained:

| Status | Count |
| --- | ---: |
| reverted | 10 |
| evaluation failed | 5 |
| implementation failed | 1 |
| implementation no-op | 1 |
| skipped | 1 |
| experiment neutral | 8 |
| experiment control won | 2 |

No located verdict contained `"promoted": true`. Even if the acceptance and
causal-evaluation defects did not exist, the recorded experiments would still
show no autonomous improvement.

### 4.7 The evidence was not reproducible

The repository ignores the directories containing the core run record:

- `derivations/_evolutions/`;
- `derivations/logs/`;
- `derivations/problems/`;
- `derivations/reports/`;
- holdout results and sidecars.

`git ls-files` reports no tracked evidence in those paths. The archive commit
preserved the code and a large deterministic practice corpus, but not the logs,
reports, verdicts, prompts, checkpoints, and candidate artifacts required to
independently reproduce the historical claims.

The active `v5.json` configuration also leaves the inner, evolve, outer, and
implement model fields empty. Those roles inherit ambient Codex configuration.
Two nominally identical runs at different times may therefore use different
models without the checkpoint clearly identifying the change.

### 4.8 The deterministic corpus did not demonstrate synthesis

The archive branch included a checked-in corpus of 240 deterministic Grade 8
linear-equation problems. The generator and distribution tests for that corpus
are legitimate data-engineering work.

The corpus was not produced by the autonomous learning loop and does not
demonstrate improved example synthesis. It is benchmark/input material, not a
successful result of the research system.

### 4.9 Approach 1 causal failure chain

The system failed through a reinforcing chain:

```text
target gate can skip
-> invalid outputs can enter accepted data
-> failure/acceptance aggregates become contaminated
-> outer model reasons over contaminated evidence
-> implementation changes the scoring system
-> closure test compares different generated graphs
-> A/B tests generation modes in the same changed workspace
-> verdict cannot establish causal improvement
-> artifacts are not versioned well enough for independent audit
```

More epochs could not repair this. The learning signal itself was invalid.

### 4.10 Approach 1 outcome

The first approach produced a large amount of machinery and a detailed trail of
local failures. It did not produce trustworthy accepted derivations, a valid
autonomous promotion mechanism, or evidence that failure memory improved later
synthesis.

Against the project objective, it was a failed approach.

## 5. The Refactor Decision

The refactor began after the end-to-end problem was traced to trust-boundary and
acceptance semantics rather than a single weak validator. Continuing to patch
the monolithic state machine would have left candidate generation, evaluation,
learning, and promotion coupled.

The replacement direction was to separate:

1. the private task and expected result;
2. the public information given to a candidate model;
3. the candidate-generation workspace;
4. the trusted evaluator workspace;
5. immutable evidence and provenance;
6. shared experiment mechanics;
7. domain-owned semantics.

This was the correct architectural problem to address. The failure was treating
the resulting separation as sufficient progress before it had powered a real
learning experiment.

## 6. Approach 2A: Frozen Typed Contracts

### 6.1 Theory of operation

The typed branch narrowed the first proof to Grade 8 linear equations. Instead
of asking the system to infer task semantics from natural-language target text,
it created a frozen task contract with explicit givens, expected solution
cardinality, canonical result data, and pedagogical requirements.

The candidate process received only a public envelope:

- task id and type;
- display prompt;
- givens;
- pedagogical requirements.

It did not receive the expected answer, task digest, or contract digest.

The trusted supervisor owned:

- the frozen task bundle;
- task and contract digests;
- oracle commit identity;
- candidate workspace provenance;
- graph schema and topology checks;
- verifier execution;
- root, goal, and pedagogy evaluation;
- atomic acceptance records.

The candidate ran in a read-only isolated workspace with a reduced environment.
The oracle ran from a clean checkout pinned to an expected commit.

### 6.2 What this fixed

The typed approach addressed several real defects from Approach 1:

- natural-language target extraction was replaced by explicit task semantics;
- expected answers remained private to the oracle;
- graph topology was checked as a typed contract;
- solution cardinalities included one, none, and infinitely many solutions;
- canonical terminal goals were specified;
- model-authored result fields were excluded from acceptance;
- candidate and evaluator provenance were recorded;
- the supervisor, not the candidate, ran the verifier.

This was meaningful trust-boundary work. It made a narrow evaluation path more
defensible.

### 6.3 What it did not implement

The typed pilot was a one-shot generation and evaluation harness. It did not
provide:

- a population or search process;
- failure aggregation across a cohort;
- candidate mutation or prompt evolution;
- a baseline/candidate code experiment;
- promotion of a system change;
- proof that a retained change improved later tasks;
- a second real domain.

It therefore repaired part of the evaluator without reconstructing the research
loop.

## 7. Approach 2B: Modular Evolution Kernel

### 7.1 Theory of operation

The modular branch attempted to generalize the typed separation. A
domain-neutral kernel would own workflow mechanics while plugins would own
semantics.

The shared kernel introduced:

- `RunSpec` for run, cohort, arm, and provenance identity;
- `DomainPlugin` for task validation, public task exposure, and evaluation;
- `AttemptEvidence` and `GateResult` for normalized outcomes;
- `ArtifactStore` for immutable evidence;
- aggregation helpers;
- paired experiment comparison and success criteria;
- a generic `run_attempt` function driven by a caller-supplied producer.

Domain adapters included:

- Grade 8 math backed by the typed linear-equation oracle;
- a compatibility adapter for legacy derivation-graph batches;
- a chaos-logistic plugin with a domain-specific deterministic evaluator.

The intended architecture was:

```text
                         +-> Grade 8 plugin -> Grade 8 oracle
public task -> producer -+-> chaos plugin   -> chaos oracle
                         +-> future plugin  -> future oracle
                                      |
                                      v
                         normalized AttemptEvidence
                                      |
                                      v
                   shared artifact, aggregate, and A/B machinery
```

This is the right shape for reusable experiment infrastructure. The problem was
that conformance to the shape was treated as evidence of actual capability.

## 8. Why Approach 2 Failed

### 8.1 Unit-test success was mistaken for system success

Current branch results are:

```text
feature/typed-derivation-contracts: 353 tests passed
feature/modular-evolution-kernel:    364 tests passed
```

These suites demonstrate that:

- schemas reject malformed data;
- digests and provenance are stable;
- expected fields can be hidden from the public task;
- typed equation cases are evaluated consistently;
- artifacts can round-trip;
- two plugins can emit the same evidence type;
- a comparator can pair control and treatment records.

They do not demonstrate that:

- a model reliably synthesizes valid examples;
- failure evidence improves later generation;
- an autonomous change beats a baseline;
- the same learning loop works across domains.

The tests established a protocol, not an autonomous synthesis system.

### 8.2 The real typed evidence was one task

The only located real typed-pilot summary evaluated one task,
`alg8-lin-001`, and passed. The checked-in pilot queue contains 12 selected
linear-equation tasks, but no located real artifact demonstrates a complete run
over that cohort or evolution across it.

A one-task pass establishes that one candidate can traverse the typed pipeline.
It says nothing about reliability, learning, improvement, transfer, or promotion.

### 8.3 The cross-domain proof read private expected answers

`test_evolution_kernel.py` constructs the Grade 8 candidate by reading
`contract["expected"]`. It constructs chaos candidates by reading
`task["expected"]`. The test directly chooses whether to manufacture a correct
or incorrect candidate.

That is acceptable for testing comparator mechanics, but it cannot support a
claim of autonomous generation. The test producer has the answer because the
test itself is the oracle.

The chaos plugin demonstrates that a second domain can implement the interface.
There is no real chaos candidate generator, search process, or autonomous
experiment.

### 8.4 The Grade 8 conformance fixture fabricated verifier evidence

The Grade 8 test candidate includes both a graph and a verifier sidecar. The
fixture marks its only edge `PASS` with reason `test evidence`.

The typed oracle explicitly documents the verifier sidecar as a trusted input.
In the typed pilot, that trust is justified because the supervisor runs the
verifier itself before calling the oracle.

In the modular path:

1. `run_attempt` calls an arbitrary producer;
2. the producer returns the candidate;
3. the Grade 8 plugin requires the candidate to contain both `graph` and
   `verifier`;
4. the plugin forwards the producer-supplied verifier to the typed oracle.

The generic abstraction preserved the JSON shape but not the execution trust
boundary. A caller can supply the evidence that the oracle assumes was produced
by trusted code.

This does not mean the typed oracle was useless. It means the modular adapter
integrated it incorrectly.

### 8.5 The real modular experiments showed no improvement

Two located real paired experiments produced:

| Experiment | Tasks | Control | Treatment | Delta | Outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| `real_neutral_ab_20260717` | 3 | 1.0 | 1.0 | 0.0 | all three accepted in both arms |
| `real_targeted_ab_20260717` | 3 | 0.0 | 0.0 | 0.0 | all three failed in both arms |

All three targeted treatment attempts failed at `rule_plan_invalid` before
producing a valid derivation. Neither experiment showed a treatment win.

These experiments were small, but their limitation is not merely sample size.
They provided no positive signal to scale up.

### 8.6 The learning loop was missing

The generic runner performs one attempt:

```text
validate task
-> expose public task
-> call producer
-> evaluate candidate
-> normalize and optionally store evidence
```

It does not itself:

- select failures for study;
- propose a reusable change;
- produce candidate system variants;
- freeze baseline and treatment implementations;
- replay an immutable benchmark;
- promote a winning change;
- feed retained knowledge into later synthesis.

The module was named an evolution kernel, but the implemented core was an
evaluation protocol. The actual evolution mechanism remained in legacy
orchestration or did not exist for the new domains.

### 8.7 Modularity became the deliverable

The refactor shifted the visible evidence of progress from successful derivation
runs to cleaner boundaries, protocol tests, and cross-domain type conformance.
Those are valuable engineering properties only if they enable the research
objective.

No evidence connected the new abstractions to:

- better generated derivations;
- better generated learning examples;
- successful failure-conditioned repair;
- improvement over an unchanged baseline;
- retained learning across tasks;
- a real second-domain workflow.

The refactor therefore solved an architectural problem without solving the
project problem.

### 8.8 Approach 2 outcome

The typed branch produced a defensible narrow supervisor and oracle. The modular
branch produced reusable evidence and comparison interfaces. Neither branch
produced an autonomous learning-example synthesis system or evidence that such a
system improved.

Against the project objective, the refactor was also a failed approach.

## 9. Comparison of the Two Approaches

| Dimension | Approach 1: autonomous epochs | Approach 2: typed/modular refactor |
| --- | --- | --- |
| Primary unit | Natural-language target and derivation graph | Frozen typed task, then generic domain task |
| Candidate generation | LLM graph or tactic plan inside a large pipeline | Isolated one-shot producer |
| Expected result | Extracted partly from target text | Private typed contract |
| Evaluation | Verifier, canvas, target check, LLM judge | Domain plugin and typed/deterministic oracle |
| Trust boundary | Coupled and fail-open | Stronger in typed pilot; weakened in modular Grade 8 adapter |
| Learning mechanism | Repair addenda, cross-run memory, outer proposals | Not implemented in the new kernel |
| System mutation | Automated prompt/validator/judge implementation | No complete autonomous mutation loop |
| Experiment | Confounded closure test and mode A/B | Generic paired comparator, but no improving candidate |
| Cross-domain claim | Broad target queues in one derivation schema | Multiple plugin interfaces, synthetic second-domain proof |
| Real result | Zero treatment wins; acceptance evidence contaminated | One real typed task; two tiny A/B ties; no learning |
| Failure mode | Built a learning loop that could not be trusted | Built trustworthy pieces without a demonstrated learning loop |

The refactor did not simply reproduce the original implementation. It corrected
some important boundaries. But because it did not produce an empirical result,
those corrections cannot be counted as progress toward the stated capability.

## 10. Shared Root Causes

### 10.1 The benchmark did not precede the architecture

The project began with more than 10,000 lines spanning generation, validators,
holdouts, state management, model calls, repair, memory, and autonomous
implementation. A minimal frozen benchmark and a causal promotion test were not
first-class prerequisites before that machinery was built.

As a result, each new failure produced more infrastructure rather than a stable
measurement of whether the system was getting better.

### 10.2 Success criteria drifted to proxy achievements

Over time, the work produced many things that were easier to prove than the
actual objective:

- a graph passed a local validator;
- a repair moved to a later gate;
- a reviewer produced valid JSON;
- an experiment packet had matching hashes;
- two domains implemented the same protocol;
- hundreds of unit tests passed.

Each is a legitimate intermediate property. None establishes autonomous
learning or improved example synthesis. The project repeatedly promoted an
intermediate property into a result claim.

### 10.3 The evaluator was not treated as immutable infrastructure

Approach 1 let the research loop change parts of its own scoring system without
a sufficiently independent higher-order oracle. Approach 2 created a stronger
frozen oracle but then allowed a generic integration path to accept the trusted
verifier sidecar from the producer.

Both failures came from treating trust as a schema property rather than an
execution and ownership property.

### 10.4 Activity was confused with learning

The system generated attempts, diagnoses, prompt addenda, proposals, code
changes, test runs, reports, verdicts, and epochs. That is autonomous activity.

Learning requires evidence that retained information or a promoted change
caused later performance to improve. No such result was demonstrated.

### 10.5 Cross-domain modularity was proven at the interface level

A domain-neutral runner can accept two plugins while every real workflow still
requires different generation, evaluation, and search logic. The chaos test
proved the interface could carry a chaos result. It did not prove the system
could autonomously discover or improve one.

The project needed operational reuse, not just type-level reuse.

### 10.6 Evidence was not a durable product of each run

The first approach's critical evidence was ignored, locally stored, and partly
dependent on ambient models. The second approach improved artifact identity but
left the only located real evidence under `/tmp` or ignored batch directories.

An autonomous research system without a reproducible research ledger cannot
distinguish discovery from transient local state.

## 11. Total-Loss Assessment

Within the scope of autoderivation and learning-example synthesis, the work is a
total loss as a project result.

That conclusion means:

- there is no trustworthy corpus of autonomously accepted derivations;
- there is no demonstrated improvement in synthesized learning examples;
- there is no validated cross-run learning result;
- there is no promoted system change backed by a causal experiment;
- there is no demonstrated reusable workflow across real domains;
- there is no reproducible experiment history sufficient to recover the claims;
- neither branch can be merged or presented as a working research system.

Some code can be reused in a future implementation. That does not change the
result classification. Reusable fragments are implementation salvage, not
evidence that the project advanced toward its objective.

### Disposition

| Work | Disposition |
| --- | --- |
| Autonomous epoch/archive branch | Archive as a failed research approach; do not merge as a working system |
| Historical acceptance and lift metrics | Invalid as evidence of progress |
| Historical reports and local artifacts | Audit material only; incomplete and not reproducible from Git |
| Typed task contracts | Possible specification material for a future benchmark |
| Typed linear-equation oracle | Possible evaluator component after its trust boundary is preserved end to end |
| Modular protocols and artifact types | Possible implementation material; not an evolution result |
| Chaos plugin | Evaluator/interface fixture, not a real second-domain workflow |
| Deterministic Grade 8 corpus | Benchmark/input data, not autonomous synthesis |

## 12. Engineering Lessons

### 12.1 Freeze the research question before building the researcher

The first executable artifact should be a benchmark that can distinguish a
better candidate system from a worse one. The benchmark, oracle, metric, and
promotion threshold must exist before autonomous implementation machinery.

### 12.2 A candidate must never provide trusted evidence about itself

The trusted supervisor must execute all evaluators and bind their outputs to the
exact candidate digest. Passing a verifier-shaped object across an interface is
not a trust boundary.

### 12.3 Evaluate the same artifact before and after evaluator changes

When changing a validator, replay the exact same candidate corpus through the
old and new validator. Do not regenerate candidates and call the difference
validator lift.

### 12.4 Evaluate the same tasks under baseline and candidate systems

When changing generation or orchestration, baseline and treatment must use the
same frozen task cohort, model identity, prompt inputs, sampling configuration,
and evaluator. Only the proposed change may differ.

### 12.5 Unit tests cannot substitute for capability evaluation

Unit tests should establish that the harness behaves as specified. A separate
benchmark must establish that the system produces useful results and improves.

### 12.6 A second domain requires a real workflow

Cross-domain evidence requires a real producer, private task set, trusted
evaluator, failure evidence, and improvement experiment in the second domain.
Constructing the expected result inside a test proves only the adapter.

### 12.7 Every run must be independently reconstructable

Code, task bundle, prompts, model identities, environment, candidates, raw gate
outputs, comparison, and promotion decision must be immutable tracked artifacts
or content-addressed external artifacts referenced by a tracked manifest.

## 13. Minimum Contract Before Any Third Attempt

A third implementation should not begin until the following exists as a small,
executable evaluation system:

1. **Versioned benchmark:** immutable tasks, private expected results, and clear
   domain coverage.
2. **Frozen oracle:** fail-closed evaluation owned by a trusted supervisor.
3. **Evidence ownership:** candidates cannot submit, edit, or select their own
   verifier evidence.
4. **Reproducible identity:** pinned code, model, prompt, task, dependency, and
   environment digests.
5. **Paired baseline:** baseline and candidate run on identical inputs with only
   the proposed change differing.
6. **Replay for evaluator changes:** exact stored candidates are scored by both
   old and new evaluators.
7. **Predeclared metrics:** success, regression, uncertainty, and stop thresholds
   are defined before running the experiment.
8. **Durable ledger:** raw candidates, gate outputs, and verdicts are retained
   as immutable evidence.
9. **Repeated treatment wins:** one positive anecdote cannot trigger promotion.
10. **Longitudinal proof:** a promoted change must improve later synthesis, not
    only the cohort that motivated it.
11. **Real second domain:** a second producer and oracle must complete the same
    research cycle without changes to shared experiment machinery.
12. **Stop rule:** if the minimal system cannot demonstrate one causal treatment
    win, do not add orchestration, agents, workflows, or abstraction layers.

Until this contract is executable, more work on the current architectures would
repeat the same mistake: building machinery before proving that the machinery
can measure or produce progress.

## Appendix A: Audit Evidence

### Branch topology

- Archive branch and typed branch merge base: `e0e6e49`.
- Modular branch base: typed head `492fcfa`.
- Archive head audited before this case study: `4b9015e`.
- Modular head audited: `8e1fe21`.

### Test results reproduced on 2026-07-19

| Worktree | Test | Result |
| --- | --- | --- |
| Archive | `test_acceptance_gate_contracts` | 10 run, 6 failures |
| Typed | `scripts/test_derivations.sh` | 353 passed |
| Modular | `scripts/test_derivations.sh` | 364 passed |

The typed and modular suites being green is included as positive evidence about
their mechanics. It does not change the capability verdict.

### Recorded original epoch outcomes

The eight ignored local `experiment_verdict.json` files record six neutral
experiments followed by two control wins. Searches of the local evaluation
artifacts found no `status: promoted` or `promoted: true` result.

### Located typed and modular real-run artifacts

- `/tmp/why-academy-real-grade8-20260717/summary.json`: one typed task, one pass.
- `real_neutral_ab_20260717_treatment/ab_comparison.json`: three tasks, 1.0
  versus 1.0.
- `real_targeted_ab_20260717_treatment/ab_comparison.json`: three tasks, 0.0
  versus 0.0; three treatment `rule_plan_invalid` failures.

These artifacts are local evidence observed during the audit. They are not
tracked reproducibility assets.

## Appendix B: Key Implementation Surfaces

### Approach 1

- `derivations/inner_evolve.py`: per-target generation, gates, repair, and
  acceptance.
- `derivations/target_check.py`: target extraction and goal comparison.
- `derivations/closure_test.py`: proposal closure and validator-lift scoring.
- `derivations/autonomous_epoch.py`: outer state machine, implementation,
  experiment, promotion, and reversion.
- `derivations/prompts/outer_loop_epoch.md`: failure aggregation and proposal
  contract.
- `scripts/e2e_learning_probe.py`: cross-run repair and memory probe.
- `derivations/configs/v5.json`: active models, engines, and thresholds.

### Approach 2

- `derivations/task_contract.py`: private typed task contract.
- `derivations/frozen_task_store.py`: immutable task bundle access.
- `derivations/typed_pilot.py`: isolated candidate and trusted supervisor.
- `derivations/typed_linear_equation_oracle.py`: deterministic typed evaluator.
- `derivations/evolution/protocols.py`: shared run and evidence types.
- `derivations/evolution/runner.py`: domain-neutral one-attempt runner.
- `derivations/domains/grade8_math/plugin.py`: Grade 8 adapter.
- `derivations/domains/chaos/plugin.py`: chaos evaluator adapter.
- `derivations/tests/test_evolution_kernel.py`: cross-domain conformance tests.
