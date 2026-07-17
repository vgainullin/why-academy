# Modular evolution kernel

`evolution/` owns workflow mechanics only: run identity, candidate invocation,
immutable artifacts, normalized gate evidence, aggregation, and paired
experiments. It must not import a subject domain.

A domain plugin owns its private task contract, public candidate envelope, and
evaluation gates. `domains/grade8_math/` adapts the existing typed algebra
oracle; `domains/chaos/` proves the same kernel works without derivation graphs,
SymPy, canvas checks, or pedagogical judges.

The boundary is `DomainPlugin`:

1. validate a private frozen task;
2. expose a public task without expected results;
3. evaluate an opaque candidate into named `GateResult` records.

Everything after those gates is shared. Adding a domain must require a new
plugin and plugin tests, not edits to `evolution/`.

`domains/derivation_graph/` is the compatibility adapter for the pre-kernel
batch loop. It translates each existing iteration into `AttemptEvidence`, so
legacy orchestration can migrate without teaching the kernel about derivation
graphs or legacy status names.
