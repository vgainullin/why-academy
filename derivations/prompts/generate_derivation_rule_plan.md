# Task: Emit Deterministic Rule Plan JSON

Generate one rule plan for the target below. Return only one JSON object.
Do not write files. Do not run commands. Do not include Markdown fences or prose.

The wrapper will execute your plan deterministically and then run the normal
verifier, canvas, target, primary judge, and adversarial judge gates. If a rule
is unsupported, the treatment fails as a coverage gap. Do not hide gaps by
inventing macro rules or by emitting final graph nodes/edges yourself.

## Output Object

```json
{
  "id": "<<PROBLEM_ID>>",
  "root_ref": "start",
  "goal_ref": "final",
  "facts": [
    { "ref": "start", "expr": "Eq(...)" }
  ],
  "steps": [
    {
      "id": "after_subtract",
      "from": "start",
      "rule": "subtract_constant_from_both_sides",
      "rule_args": { "constant": "Integer(2)" }
    }
  ]
}
```

## Schema Rules

- The object is schema-validated before execution. Extra fields and wrong types fail immediately.
- `id` must be exactly `<<PROBLEM_ID>>`.
- Do not include graph keys such as `nodes`, `edges`, `root_node`, or `goal_node`.
- `facts` are visible starting equations. Use stable `ref` names, not graph node ids.
- If the target states explicit givens or named facts, include each one as a visible `Eq(...)` fact.
- `steps[*].from` must reference a prior fact ref or prior step id.
- `goal_ref` must reference the exact requested target result, not a weaker or easier intermediate.
- Every `expr` must be exactly one top-level `Eq(lhs, rhs)`.
- Use SymPy expression syntax: `Rational(p, q)`, `sqrt`, `sin`, `cos`, `exp`, `log`, `Derivative`, `Integral`, `Sum`, `pi`, `oo`.
- Standard real symbols are available: `x y z r t u v theta phi n k m a b c`.
- For other variables use `Symbol('name')`, for example `Symbol('omega')`, `Symbol('xddot')`, `Symbol('R')`, `Symbol('g')`, `Symbol('h')`.

## Execution Rules

- Exactly one mathematical transformation per step.
- Use only supported executor rules:

<<SUPPORTED_EXECUTOR_RULES>>

- Known verifier rules are:

<<KNOWN_RULES>>

- `rule_args` must be valid JSON. Symbolic expressions such as `-x`, `k/m`, or `-Symbol('omega')**2*x` must be quoted as strings.
- Non-swap rules are side-sensitive: preserve left/right orientation across the step.
- For `substitute_value` and `substitute_expression`, the executor emits only the immediate substituted form. Any combining, cancelling, expanding, factoring, or simplification must be a later `simplify_expression`, `expand_expression`, or `factor_expression` step.
- If a substitution uses a prior given, include that given as a visible fact, then put the actual `symbol` and `replacement` in `rule_args`. Do not use hidden `target_eq` state.
- If no supported executor rule fits, still use the closest explicit rule name. The executor should expose the coverage gap rather than accepting a bundled step.

## Target

<<TARGET>>
