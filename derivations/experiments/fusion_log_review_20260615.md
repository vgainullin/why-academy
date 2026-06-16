# Fusion Log Review Pilot - 2026-06-15

## Hypothesis

OpenRouter Fusion (`openrouter/fusion`) may produce better meta-hypotheses than
a single Codex reviewer because it runs a multi-model panel and judge.

## Correction

The first Fusion pilot was not a valid GPT-5.5 vs Fusion comparison. GPT-5.5 had
repo-local filesystem access, while Fusion only saw prompt text. The corrected
experiment below uses a single self-contained packet and sends that exact packet
to both reviewers.

## Mechanism Change

`derivations/introspective_log_review.py` now supports:

- `--engine codex` (default): existing local Codex reviewer.
- `--engine openrouter --model openrouter/fusion`: remote Fusion reviewer.
- Remote reviewers inline selected target artifacts because they cannot inspect
  local paths.
- Fenced/prose-wrapped model output is normalized into JSON while preserving the
  raw response.

`derivations/llm_cli.py` now calls OpenRouter through raw HTTP so non-JSON router
failures preserve the response body in artifacts instead of collapsing to an
opaque SDK `JSONDecodeError`.

`derivations/reviewer_parity_experiment.py` writes one self-contained packet and
runs:

- Codex GPT-5.5 xhigh from an empty temp cwd with config/rules/tools disabled.
- OpenRouter Fusion on the same packet file.

Both run metadata files record the same `prompt_sha256`.

## Commands

```bash
uv run --with-requirements derivations/requirements.txt \
  python derivations/introspective_log_review.py \
  derivations/_evolutions/batches/ab_control_json_queue_20260615_001 \
  --target-id target_007 \
  --out-dir derivations/_evolutions/batches/ab_control_json_queue_20260615_001/fusion_reviews_inline_v2 \
  --run \
  --engine openrouter \
  --timeout 600

uv run --with-requirements derivations/requirements.txt \
  python derivations/introspective_log_review.py \
  derivations/_evolutions/batches/ab_control_json_queue_20260615_001 \
  --target-id target_008 \
  --out-dir derivations/_evolutions/batches/ab_control_json_queue_20260615_001/fusion_reviews_inline_v2 \
  --run \
  --engine openrouter \
  --timeout 600
```

Corrected parity command:

```bash
uv run --with-requirements derivations/requirements.txt \
  python derivations/reviewer_parity_experiment.py \
  derivations/_evolutions/batches/ab_control_json_queue_20260615_001 \
  --target-id target_008 \
  --out-dir derivations/_evolutions/batches/ab_control_json_queue_20260615_001/reviewer_parity_20260615_v2 \
  --timeout 1200
```

## Results

Artifacts:

- `derivations/_evolutions/batches/ab_control_json_queue_20260615_001/fusion_reviews_inline_v2/introspective_log_review_target_007_output.json`
- `derivations/_evolutions/batches/ab_control_json_queue_20260615_001/fusion_reviews_inline_v2/introspective_log_review_target_008_output.json`
- `derivations/_evolutions/batches/ab_control_json_queue_20260615_001/reviewer_parity_20260615_v2/reviewer_parity_target_008_comparison.json`
- `derivations/_evolutions/batches/ab_control_json_queue_20260615_001/reviewer_parity_20260615_v2/reviewer_parity_target_008_codex_output.json`
- `derivations/_evolutions/batches/ab_control_json_queue_20260615_001/reviewer_parity_20260615_v2/reviewer_parity_target_008_fusion_output.json`

Target 007:

- Fusion set `accepted_false_pass: true`.
- It did not identify the previously recorded substitution/simplification fuse
  on `n0->n2`.
- It proposed a different accepted-quality hypothesis: `divide_both_sides` by
  compound divisor `-m*x` is too macro and should split into divide by `x`,
  divide by `m`, then multiply by `-1`.
- This is useful but risky: current rules already allow compound divisors such
  as `m*g`, so this needs a false-rejection experiment before any verifier
  change.

Target 008:

- Fusion reproduced the main failed-run pattern: the final graph passed verifier
  and target check, then failed judge because `n4->n5` fused substitution with
  arithmetic simplification.
- Its hypothesis differed from the earlier GPT-5.5 xhigh introspection:
  - GPT-5.5 emphasized side-sensitive planning and explicit intermediate
    orientation.
  - Fusion emphasized non-monotonic repair: each iteration fixes the latest
    failure while regressing a previously-green invariant.
- Fusion proposed a cumulative regression ledger: every previously-passed check
  becomes a persistent gate in later repair attempts, with a side-by-side
  experiment measuring regression count, oscillation rate, success rate, and
  iterations to success.

Corrected parity target 008:

- Packet hash matched for both reviewers:
  `126122d5b5c2076e29cf1af9d378f42772ead3b53b913165be107ab857eb4d96`.
- Codex GPT-5.5 xhigh ran with `codex_packet_only: true` from an empty temp cwd.
- Both reviewers identified the same concrete final failure: iter_02 edge
  `n4->n5` used `substitute_value` but fused substitution with arithmetic
  simplification/term combining.
- Codex hypothesis: add an immediate-substitution structural check for
  `substitute_value` and feed back the expected intermediate form.
- Fusion hypothesis: add the same deterministic pre-judge bundling lint, but
  wrap it in a cumulative regression checklist so later repairs cannot regress
  previously-satisfied constraints.
- Conclusion: under equal context, Fusion did not contradict GPT-5.5; it added a
  stronger meta-hypothesis around non-monotonic repair memory. The next
  pre-registered experiment should test immediate-substitution lint alone versus
  lint plus cumulative regression ledger.

## Lessons

The first non-inline Fusion prompt was invalid as a comparison because it listed
local paths that OpenRouter could not read. Remote reviewers must receive a
self-contained artifact packet, and local reviewers must be run packet-only for
context parity.

Fusion is useful as a hypothesis generator, not as an oracle. It found a
plausible meta-solution for target 008 and a plausible but over-broad atomicity
hypothesis for target 007. Both require pre-registered side-by-side tests before
implementation.
