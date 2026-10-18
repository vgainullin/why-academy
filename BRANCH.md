# feature/modular-evolution-kernel

Approach 2B of the autonomous derivation research: a domain-neutral evolution
kernel with domain plugins.

## What the branch contains

It is built on `feature/typed-derivation-contracts` at `492fcfa`. Two commits
on top (`ca2f4f2`, `8e1fe21`) add:

- `derivations/evolution/`: the kernel (`RunSpec`, the `DomainPlugin`
  protocol, `AttemptEvidence`/`GateResult`, an immutable artifact store,
  aggregation, paired experiment comparison, `run_attempt`). Its design notes
  are in `derivations/evolution/README.md`.
- `derivations/domains/grade8_math/`: a plugin backed by the typed
  linear-equation oracle
- `derivations/domains/chaos/`: a logistic-map plugin that serves as an
  interface fixture
- `derivations/domains/derivation_graph/`: a compatibility adapter that
  converts legacy batch iterations into `AttemptEvidence`
- changes that route `ab_compare.py`, `autonomous_epoch.py`, `inner_evolve.py`
  and `typed_pilot.py` through the neutral evidence types, plus tests

## Status

Not merged and not expected to be. On 2026-07-19, `scripts/test_derivations.sh`
passed (364 tests). The two real modular A/B runs showed no treatment
improvement (1.0 vs 1.0 and 0.0 vs 0.0). Known problems:

- the chaos "cross-domain proof" builds candidates from private expected
  answers
- the Grade 8 conformance fixture supplies fabricated verifier evidence
- the Grade 8 adapter accepts a verifier supplied by the producer, which
  weakens the typed pilot's trust boundary
- no learning loop was built around the kernel

The protocols and artifact types may be reused as implementation material. See
`derivations/FAILURE_ANALYSIS.md` (sections 7 and 8) on
`feature/archive-e2e-autonomous-derivation`.
