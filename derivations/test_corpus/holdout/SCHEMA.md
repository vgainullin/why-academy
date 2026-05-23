# Holdout corpus

The holdout is the **locked reality test** that gates auto-promotion of prompt and validator changes. It must never be read by any LLM in the training loop.

## Schema (generation-format, post-v0.5)

Each problem under `problems/` is JSON with:

```json
{
  "id": "<unique snake_case id>",
  "category": "<one of cohort_v1 categories>",
  "difficulty": "easy | medium | hard",
  "target_text": "<the prompt that would go through inner.sh>",
  "expected_goal_srepr": "<sympy srepr of the canonical goal node>",
  "acceptable_alternate_goals": ["<srepr>", "..."],
  "source": "<citation: textbook tradition, not a specific URL>"
}
```

### How holdout pass is measured

For each holdout problem:
1. Run `inner.sh` (or `inner_with_evolution.sh`) on `target_text`
2. Check the generated graph satisfies:
   - `verify.py` reports 0 FAIL / 0 ERROR edges
   - `canvas_check.py` reports 0 MISMATCH / 0 PARSE_ERROR / 0 DUPLICATES
   - The graph's `goal_node` srepr is sympy-equivalent (after assumption-stripping) to `expected_goal_srepr` OR any entry in `acceptable_alternate_goals`

A holdout problem PASSes iff all three conditions hold.

### Regression semantics

The holdout is run at epoch close and before any auto-promotion. A candidate change (prompt addendum, new validator) is allowed to promote iff:

- The candidate run's holdout pass-rate >= baseline run's holdout pass-rate
- Zero items that previously passed now fail
- Per-category pass rates do not regress by more than the configured tolerance

### Categories and counts (target: ~5 per category)

| Category | Source tradition |
|---|---|
| algebra_linear      | OpenStax Elementary Algebra 2e Ch.2 |
| algebra_quadratic   | OpenStax Intermediate Algebra 2e Ch.9 |
| algebra_factoring   | OpenStax Elementary Algebra 2e Ch.7 |
| calculus_derivatives | OpenStax Calculus Vol.1 Ch.3 |
| calculus_integrals   | OpenStax Calculus Vol.1 Ch.5 |
| calculus_limits      | OpenStax Calculus Vol.1 Ch.2 |
| physics_mechanics    | OpenStax College Physics 2e Ch.2-3 |
| physics_oscillations | OpenStax College Physics 2e Ch.16 |
| trig_identities      | OpenStax Algebra and Trigonometry 2e Ch.9 |
| linear_algebra       | OpenStax Intermediate Algebra 2e Ch.4 (systems) |

Citations name the textbook tradition the problem belongs to; many of these problems appear in equivalent form across most introductory texts.

## Legacy (`problems_legacy_verifier/`)

The original 3 hand-written full-graph holdout problems. Used by the older verifier regression test. Keep them for now as a separate sanity check on `verify.py` + validator changes that doesn't require any LLM call.
