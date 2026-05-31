# Task: Emit Derivation Graph JSON

Generate one derivation graph for the target below. Return only one JSON object.
Do not write files. Do not run commands. Do not include Markdown fences or prose.

## Output Object

The top-level object must have exactly these keys:

```json
{
  "id": "<<PROBLEM_ID>>",
  "root_node": "n0",
  "goal_node": "n2",
  "nodes": [
    { "id": "n0", "sympy_srepr": "Eq(...)" }
  ],
  "edges": [
    { "from": "n0", "to": "n1", "rule": "rule_id", "rule_args": {} }
  ]
}
```

## Schema Rules

- The object is schema-validated before any verifier runs. Extra fields and wrong types fail immediately.
- `id` must be exactly `<<PROBLEM_ID>>`.
- `nodes` must be a non-empty array of `{ "id": string, "sympy_srepr": string }` objects only.
- `edges` must be an array of `{ "from": string, "to": string, "rule": string, "rule_args": object }` objects only. `rule_args` may be omitted.
- Every node `sympy_srepr` must be exactly one top-level `Eq(lhs, rhs)`.
- `goal_node` must be the exact requested target result, not a weaker or easier intermediate. If the target asks for `omega = sqrt(k/m)`, do not stop at `omega^2 = k/m`.
- Do not emit tuples, lists, sets, `And(...)`, assumptions, facts, prose nodes, or bundled equations.
- Do not include `latex`, `metadata`, `title`, `domain`, `level`, `hint`, `substeps`, or any extra fields.
- If the target states explicit givens or named facts, include each one as a visible `Eq(...)` node in `nodes`. Do not create fake edges such as `introduce_given_equation`; a given node may be disconnected if there is no one-rule algebraic edge that introduces it.
- Use SymPy expression syntax: `Rational(p, q)`, `sqrt`, `sin`, `cos`, `exp`, `log`, `Derivative`, `Integral`, `Sum`, `pi`, `oo`.
- Standard real symbols are available: `x y z r t u v theta phi n k m a b c`.
- For other variables use `Symbol('name')`, for example `Symbol('omega')`, `Symbol('xddot')`, `Symbol('R')`, `Symbol('g')`, `Symbol('h')`.
- Never use bare `I`, `E`, or `S` as variable names.
- Avoid forms that SymPy will auto-collapse into duplicate adjacent nodes.
- Do not add a separate `simplify_expression` edge when the previous algebraic edge already simplifies to that same displayed equation. For example, solve `x + 2 = 5` as one edge `Eq(x + 2, 5)` -> `Eq(x, 3)` using `subtract_constant_from_both_sides`, not as `Eq(x + 2 - 2, 5 - 2)` -> `Eq(x, 3)`.

## Edge Rules

- Exactly one mathematical transformation per edge.
- Use snake_case rule names.
- Prefer known rules when they fit:

<<KNOWN_RULES>>

- Canonical rule contracts:
<<RULE_CONTRACTS>>
- `rule_args` must be valid JSON. Symbolic expressions such as `-x`, `k/m`, or `-Symbol('omega')**2*x` must be quoted as strings.
- Non-swap rule contracts are side-sensitive: keep the same left/right orientation across the edge. For `x + 2 = 5`, emit `Eq(x + 2, 5)` -> `Eq(x, 3)` with `subtract_constant_from_both_sides`; do not swap to `Eq(5, x + 2)` first.
- If no validator-backed rule fits, do not invent a rule to hide the gap. Keep the requested target visible and let the verifier expose the missing proof obligation.
- Do not introduce a given with a non-truth-preserving edge. If a given is needed only as substitution evidence, include it as its own visible node and use a strict substitution rule edge from the equation being transformed.
- Do not rewrite the target to fit available validators. If a requested final step needs assumptions or validator support that is missing, still keep the requested target as `goal_node`; the failure should be visible to the gates instead of hidden by changing the goal.

## Target

<<TARGET>>
