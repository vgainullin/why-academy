# Task: Generate Verified Derivation Graph

Generate a step-by-step derivation graph for a target equation, write it to disk in the project's schema, then run the SymPy verifier and report results.

## Context

This task adds one problem to the Why Academy derivation corpus.

Project layout (do not modify outside the problem file):

```
derivations/
  problems/             # <-- write the new file here
  rule_library/         # rule definitions (read-only for this task)
  validators/           # validator implementations (read-only)
  verify.py             # verifier entry point (read-only)
```

## Input

A target equation, substituted at the `<<TARGET>>` placeholder at the bottom of this prompt by the inner-loop wrapper. May be LaTeX, plain text, or SymPy. Convert to a SymPy expression internally before proceeding.

## Workflow

### 1. Resolve the problem id

Pre-assigned id: `<<PROBLEM_ID>>`

- If the line above says `AUTO`, derive a `snake_case` id from the target (e.g. `gaussian_integral`, `chain_rule_from_limit_def`), then check `derivations/problems/<id>.json` — if it exists, **stop** and ask whether to overwrite (do not silently overwrite).
- If the line above is anything else, use it verbatim as the id. The wrapper has cleared the canonical path; do not re-check for existence.

### 2. Pick a root
- Choose a pedagogically reasonable starting point: a definition, axiom, or foundational identity at the appropriate level (HS / calculus / linear algebra / etc.).
- If multiple roots are reasonable, list 2-3 candidates in your response with a one-line justification each, then proceed with the first unless instructed otherwise. Do not block on confirmation for routine cases.

### 3. Generate the graph
Write `derivations/problems/<id>.json` matching this schema exactly:

```json
{
  "id": "<snake_case>",
  "root_node": "n0",
  "goal_node": "<node id>",
  "nodes": [
    { "id": "n0", "sympy_srepr": "Eq(...)" }
  ],
  "edges": [
    { "from": "n0", "to": "n1", "rule": "<rule_id>", "rule_args": {} }
  ]
}
```

**Schema rules:**

- `sympy_srepr` is a Python expression that evaluates under `from sympy import *` plus standard symbol declarations. Source of truth. LaTeX is derived from this at display time; do not include a `latex` field.
- `goal_node` must be the exact requested target result, not a weaker or easier intermediate. If the target asks for `omega = sqrt(k/m)`, do not stop at `omega^2 = k/m`.
- Equations are always `Eq(lhs, rhs)`, never bare `=`.
- Use `oo`, `-oo` for infinity; `pi` for π; `Rational(p, q)` for fractions (never bare `1/2`, which is float division in Python).
- Standard symbols `x, y, z, r, t, u, v, theta, phi, n, k, m, a, b, c` are pre-declared as real in `verify.py`. Anything else, use `Symbol('foo')`.
- **SymPy's bare `I` is the imaginary unit, `E` is Euler's number, `S` is the singleton registry.** Do not name any symbol `I`, `E`, or `S` — pick a different letter. If you absolutely must, use `Symbol('I')` everywhere; expect bugs.
- **SymPy auto-simplifies during expression construction.** `Mul(Integer(2), Add(Symbol('x'), Integer(3)))` evaluates to `2*x + 6` immediately — there is no stable srepr for the unevaluated `2(x+3)` form. Likewise `Mul(Symbol('h'), Symbol('h'))/Symbol('h')` collapses to `Symbol('h')`. If two consecutive nodes differ only by a simplification sympy performs automatically, they will collapse to the same expression and the canvas integration check will flag them as DUPLICATE. When in doubt, write the form sympy will store, not the form you wish it stored.
- Functions: `Integral(f, (x, a, b))`, `Sum(f, (k, lo, hi))`, `Derivative(f, x)`, `exp`, `log`, `sin`, `sqrt`, `gamma`, etc.

**Edge rules:**

- Exactly one rule per edge. Two transformations → two edges with an intermediate node.
- Use `snake_case` rule names. Prefer names already in `derivations/rule_library/` — list them first with `ls derivations/rule_library/*/*.json | xargs -n1 basename | sed 's/.json//' | sort -u` and use existing names where applicable.
- If no existing rule fits, invent a name in the same style. The verifier will mark it as `UNCOVERED` (no specific validator); that's fine and is the feedback signal for adding new validators later.
- Include `rule_args` only when the rule's validator needs disambiguation (substitution variable, factoring target, etc.). Most edges omit it.
- **Canonical arg names for common rules:**
  - `add_constant_to_both_sides`, `subtract_constant_from_both_sides`: `"constant": <value>`
  - `divide_both_sides`, `multiply_both_sides`: `"divisor": <value>` / `"multiplier": <value>` (NOT `factor`)
  - `substitute_expression`, `substitute_value`: `"symbol": <name>, "replacement": <value>`
  - Consistency on these arg keys matters: validators dispatch on them. Use the canonical names; don't invent synonyms.

**Do not include:** `latex`, `canonical_hash`, `title`, `domain`, `level`, `metadata`, `hint`, `cost`, `depth_from_root`, `distance_to_goal`, `substeps`. These either derive from `sympy_srepr` at load time or aren't tracked yet.

**Branching:** If the derivation has multiple genuinely distinct paths (different first moves from the root, not reorderings), encode them. All paths share `root_node` and converge at a common state or at `goal_node`. If only one natural derivation exists, produce a single path; do not invent artificial branches.

### 4. Verify

Run:

```bash
python3 derivations/verify.py derivations/problems/<id>.json
```

The verifier writes a sidecar at `derivations/problems/<id>.verifier.json` (machine-readable; the outer-loop wrapper consumes this — you do not need to touch it) and prints the structured summary described below to stdout.

### 5. Report

Print the verifier's stdout **verbatim**. It already has this shape:

```
GRAPH:       <id>
NODES:       <count>
EDGES:       <count>
RULES USED:  <count distinct>
BRANCHING:   <node_ids with >1 outgoing edge, or "none">

VERIFIER:
  PARSE:     <n_parsed>/<n_total>
  NODE TRUTH: TRUE=<n>  FALSE=<n>  ERROR=<n>
  EDGES:     PASS=<n>  FAIL=<n>  UNCOVERED=<n>  WEAK_PASS=<n>  ERROR=<n>

FAILURES:
  <edge>  <rule>  <reason>      # only if any
```

Do **not** paraphrase or interpret. If the verifier reports a failure, print it verbatim and stop. Do **not** auto-retry, auto-correct, or modify the JSON to make verification pass — that path leads to the LLM training itself to produce graphs that look-valid-but-aren't. Wait for explicit instruction to retry with the failure information.

## Done criteria

- `derivations/problems/<id>.json` exists and is valid JSON
- `verify.py` ran to completion
- Structured summary printed
- No files outside `derivations/problems/<id>.json` were modified

## Hard constraints

- Read `derivations/rule_library/` to discover existing rules; do not invent rule names that already exist under a slightly different spelling.
- Do not modify `verify.py`, the validator code, the rule library, or other problem files. This task adds one file. If a bug in the verifier surfaces, report it; don't patch it.
- Do not pre-verify by silently re-running calculations and editing the JSON. Generate your best derivation, write it, let the verifier judge. The verifier's job is to catch your mistakes; making it harder to catch them defeats the loop.
- Do not include explanatory prose inside the JSON (no comments — JSON has no comment syntax; no extra fields).
- One graph per task invocation. Do not batch multiple problems.

## Target

<<TARGET>>
