# Autoderivation and Learning-Example Synthesis Failure Analysis

**Audit date:** 2026-07-19

**Scope:** autonomous derivation and learning-example synthesis only

**Outcome:** neither attempted architecture demonstrated trustworthy autonomous
derivation, system learning, or improved example synthesis. Against that project
objective, both attempts failed.

This is not a statement about the student application. It is a record of the
research system's result.

## Required Capability

The intended system was conceptually similar to autoresearch or AlphaEvolve:

1. generate candidate derivations or learning examples;
2. evaluate them with a trusted, domain-owned oracle;
3. aggregate failure evidence;
4. propose changes to generation, prompts, validators, or rules;
5. evaluate each change against an unchanged baseline;
6. promote only changes that produce reproducible improvement;
7. reuse the same orchestration across very different domains.

A working implementation therefore needed to prove all of the following:

- accepted candidates are actually valid;
- candidate code cannot influence or fabricate its own evaluation;
- an observed improvement is caused by the proposed change;
- evaluation inputs, models, prompts, and artifacts are reproducible;
- the loop improves later synthesis rather than only producing more machinery;
- domain reuse works with real generators and evaluators, not constructed test
  answers.

Neither approach met this contract.

## Approach 1: Monolithic Autonomous Derivation Epochs

**Branch:** `feature/archive-e2e-autonomous-derivation`

**Head audited:** `4b9015e`

**Common base with the later typed refactor:** `e0e6e49`

### Design

The first approach coupled derivation generation, verification, pedagogical
judging, failure diagnosis, prompt evolution, validator implementation, closure
testing, and A/B experiments into `autonomous_epoch.py` and its supporting
scripts.

The intended loop was:

```text
target
-> generated graph
-> verifier / canvas / target / judge gates
-> accepted graph or labeled failure
-> aggregate failures
-> propose and implement a change
-> closure test or pipeline A/B
-> promote or revert
```

The branch added substantial orchestration, experiment adapters, reports, model
comparison tooling, and a deterministic Grade 8 algebra corpus. None of those
additions established that the autonomous loop learned or improved synthesis.

### Failure 1: The acceptance gate failed open

`target_check.py` returns exit code `0` with status `SKIP` when it cannot extract
a deterministic expected goal. `inner_evolve.py` treats any zero return code as
a successful target gate and proceeds to the LLM judge. A graph can therefore
be accepted without deterministic proof that it reached the requested target.

The same gate does not reject a matching goal that is non-terminal, unreachable,
or connected through an unknown endpoint.

Current contract-test result:

```text
Ran 10 tests
FAILED (failures=6)
```

The failures cover:

- missing structured target evidence accepted instead of failing closed;
- non-terminal goal accepted;
- unreachable goal accepted;
- unknown edge endpoint accepted;
- context-implied isolate target not extracted;
- factorization target not extracted.

Consequently, previous accepted rates cannot be used as evidence of correct
autoderivation. A `PASS` may have been reached after the deterministic target
gate silently skipped its responsibility.

### Failure 2: Validator "lift" was not a causal measurement

`closure_test.py` selects targets that previously contained failing edges, then
runs a fresh stochastic generation batch after the implementation change. It
counts passing edges with the same rule in the new graphs as resolved prior
failures.

It does not replay the exact prior candidate through baseline and candidate
implementations. The before and after populations can differ in graph shape,
edge count, prompt behavior, and model output. The resulting `lift_fraction`
cannot isolate the effect of the code change, yet `autonomous_epoch.py` can use
that fraction to promote the implementation.

### Failure 3: The pipeline A/B was not implementation versus baseline

The implementation phase mutates the workspace before the experiment phase.
Both control and treatment then run in that same mutated workspace. The arms
primarily differ by generation mode (`json` versus `rule_executor`), not by
baseline code versus proposed code.

This can compare two generation paths, but it cannot prove that the autonomous
implementation improved the system.

### Failure 4: Recorded experiments showed no improvement

The eight locally recorded epoch experiments produced:

| Epochs | Control | Treatment | Result |
| --- | ---: | ---: | --- |
| 1-6 | 1.0 | 1.0 | neutral |
| 7 | 0.2 | 0.0 | control won |
| 8 | 0.6 | 0.2 | control won |

Totals: six neutral results, two control wins, zero treatment wins, and zero
promotions.

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

No recorded verdict contained `"promoted": true`. No recorded output from the
dedicated cross-run learning probe was found outside its source code.

Even if the acceptance gate had been sound, these results would still show no
autonomous improvement.

### Failure 5: The evidence was not reproducible

The repository ignores:

- `derivations/_evolutions/`;
- `derivations/logs/`;
- `derivations/problems/`;
- `derivations/reports/`;
- holdout result sidecars.

`git ls-files` reports no tracked files in those evidence directories. The
archive commit preserved code and generated practice data, but not the run
artifacts required to reproduce its conclusions.

The active `v5.json` configuration also leaves the inner, evolve, outer, and
implement model names empty. Runs therefore inherit ambient model configuration
and cannot be compared reliably over time.

### Approach 1 conclusion

The first approach failed both correctness and learning evaluation. It could
generate activity, reports, proposals, and apparent acceptances, but it could
not establish that accepted derivations were valid or that promoted changes
caused improvement.

## Approach 2: Typed Contracts and Modular Evolution Kernel

**Typed branch:** `feature/typed-derivation-contracts` at `492fcfa`

**Modular branch:** `feature/modular-evolution-kernel` at `8e1fe21`

The typed branch diverged from the same `e0e6e49` base as Approach 1; it was not
a validated continuation of the archive branch. The modular branch was then
built on the typed branch.

### Design

The typed refactor attempted to repair the trust boundary with:

- frozen private task contracts;
- public task envelopes that omit expected answers;
- immutable digests and provenance;
- a clean, pinned oracle checkout;
- a deterministic typed linear-equation oracle;
- a read-only candidate-generation process.

The modular refactor extracted a domain-neutral runtime with:

- a `DomainPlugin` protocol;
- normalized `AttemptEvidence`;
- immutable artifact storage;
- shared aggregation and paired comparison;
- Grade 8 math, derivation-graph, and chaos adapters.

This is a better separation of responsibilities. It still did not demonstrate
the required capability.

### Failure 1: Passing unit tests proved plumbing, not synthesis

Current test results are:

```text
feature/typed-derivation-contracts: 353 tests passed
feature/modular-evolution-kernel:    364 tests passed
```

These suites prove contracts, serialization, evaluator behavior, and experiment
comparison mechanics. They do not prove that an autonomous generator can
produce useful examples, learn from failures, or improve across iterations.

The only located real typed-pilot summary evaluated one task,
`alg8-lin-001`, and passed. A one-task pass demonstrates that one generation can
travel through the pipeline; it is not a benchmark and contains no learning or
before/after comparison.

The typed Grade 8 plugin is limited to `linear_equation`. The checked-in pilot
queue contains 12 selected linear-equation tasks. There is no demonstrated
evolution loop over that cohort.

### Failure 2: The cross-domain proof used constructed answers

`test_evolution_kernel.py` constructs Grade 8 candidates by reading the private
`contract["expected"]` value. It also constructs chaos candidates by reading
`task["expected"]`. Correct and incorrect candidates are selected directly by
the test.

The Grade 8 fixture additionally supplies a fabricated verifier sidecar whose
only edge is marked `PASS` with reason `test evidence`.

Those tests prove that two plugins can satisfy the same runtime interface and
that the comparator can distinguish hand-constructed pass/fail records. They do
not prove autonomous cross-domain generation or evaluation.

### Failure 3: The generic runner broke the typed oracle's trust assumption

The typed oracle explicitly treats the verifier sidecar as a trusted input. In
the typed pilot, the supervisor runs the verifier and then passes its sidecar to
the oracle.

The modular `run_attempt` API instead accepts an arbitrary caller-supplied
producer. The Grade 8 plugin accepts a candidate containing both `graph` and
`verifier` and forwards both to the oracle. The conformance test exercises this
path with its fabricated all-pass verifier.

The abstraction therefore generalized the data shape without preserving the
original execution trust boundary. Candidate generation and trusted evidence
production are separable in the typed pilot but become caller convention in the
generic path.

### Failure 4: Real modular experiments showed no gain

Two located real paired experiments produced:

| Experiment | Tasks | Control | Treatment | Delta |
| --- | ---: | ---: | ---: | ---: |
| `real_neutral_ab_20260717` | 3 | 1.0 | 1.0 | 0.0 |
| `real_targeted_ab_20260717` | 3 | 0.0 | 0.0 | 0.0 |

All three targeted treatment attempts failed at `rule_plan_invalid` before
producing a valid derivation. Neither experiment showed a treatment win.

There is no real chaos candidate generator or autonomous chaos experiment. The
chaos plugin has a deterministic evaluator, but its cross-domain success exists
only in tests with answers constructed from private expected data.

### Failure 5: Modularity became the result instead of enabling the result

The refactor solved interface and ownership problems, but the project objective
was not "define a reusable protocol." The objective was a reusable system that
autonomously improves derivation and learning-example synthesis.

No evidence connects the new interfaces to:

- better generated derivations;
- better generated learning examples;
- successful failure-conditioned repair;
- improvement over an unchanged baseline;
- learning that transfers between tasks;
- a real second-domain workflow.

### Approach 2 conclusion

The second approach repaired parts of the architecture but failed as an
autoderivation and learning-example synthesis system. It produced reusable
implementation fragments, not a demonstrated research result.

## Shared Root Causes

Both attempts failed for the same higher-level reasons:

1. **The success criterion drifted.** Passing orchestration and protocol tests
   was treated as progress toward autonomous learning.
2. **Evaluation was added after implementation.** The system was not built
   around a frozen, causal benchmark from the start.
3. **Trust boundaries were incomplete.** Approach 1 failed open; Approach 2
   preserved trust in one pilot but weakened it in the generic integration.
4. **Artifacts were not first-class outputs.** Critical evidence was local,
   ignored, and dependent on ambient configuration.
5. **Domain breadth was asserted through fixtures.** Interface conformance was
   mistaken for real cross-domain capability.
6. **No improvement threshold was actually cleared.** The available real
   experiments contain no treatment win or promoted improvement.

## Disposition

| Work | Disposition |
| --- | --- |
| Autonomous epoch/archive branch | Failed research approach; do not merge as a working system |
| Historical acceptance and lift metrics | Invalid as evidence of progress |
| Typed contracts and oracle | Potential implementation material only; not a successful system |
| Modular kernel | Protocol prototype only; not proof of autonomous synthesis |
| Deterministic Grade 8 corpus | Test/input data; not autonomous learning-example synthesis |
| Local experiment artifacts | Audit evidence only; incomplete and not reproducible from Git |

## Minimum Evidence Required Before Another Attempt

A third implementation should not begin until the evaluation contract exists
as an executable, tracked gate:

1. immutable, versioned benchmark tasks and expected results;
2. a fail-closed oracle that generates all trusted evidence itself;
3. candidates unable to submit or alter verifier evidence;
4. pinned model, prompt, code, task, and environment identities;
5. exact paired evaluation of baseline and candidate on the same inputs;
6. tracked raw artifacts sufficient for independent reproduction;
7. predeclared improvement and regression thresholds;
8. repeated treatment wins before promotion;
9. a real second-domain generator and evaluator, not a fixture producer;
10. evidence that a promoted change improves later synthesis.

Until those conditions are met, more orchestration or modularization would be
another implementation exercise rather than progress on autoderivation or
learning-example synthesis.
