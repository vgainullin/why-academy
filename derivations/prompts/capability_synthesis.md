# Task: Synthesize a Candidate Validator Package

You are given a machine-generated capability proposal from verifier failures.
Produce a candidate validator and tests in JSON only. Do not edit files. Do not
run commands.

The candidate will be evaluated in isolation before any live validator is
changed. Evaluation includes both your generated positive/negative tests and a
closure check against the proposal's observed evidence edges, using their
current `rule_args` exactly as recorded. If the evidence does not justify a safe
local edge validator that closes those edges as-is, reject the proposal instead
of inventing permissive logic.

## Capability Proposal

```json
<<CAPABILITY_PROPOSAL_JSON>>
```

## Required Output

Return exactly one JSON object, no markdown fences:

```json
{
  "rule_name": "<same as proposal.rule_name>",
  "validator_py": "<complete Python source exporting RULE_NAME and validate(from_expr, to_expr, args)>",
  "tests": {
    "positive": [
      {
        "description": "<short>",
        "from_srepr": "Eq(...)",
        "to_srepr": "Eq(...)",
        "args": {},
        "expected": "PASS"
      }
    ],
    "negative": [
      {
        "description": "<short>",
        "from_srepr": "Eq(...)",
        "to_srepr": "Eq(...)",
        "args": {},
        "expected": "FAIL"
      }
    ]
  },
  "notes": "<short rationale>",
  "risks": ["<risk>", "..."]
}
```

If no safe local validator can be defined, return:

```json
{
  "reject": true,
  "rule_name": "<same as proposal.rule_name>",
  "reason": "<why this should not become a validator>"
}
```

## Validator Constraints

- Validate exactly one edge: `from_expr`, `to_expr`, and `args`.
- Export `RULE_NAME` equal to the proposal rule.
- Export `validate(from_expr, to_expr, args)` returning `("PASS", reason)` or `("FAIL", reason)`.
- Never raise from `validate`; catch exceptions and return `FAIL`.
- Use only `sympy` and `sympy_eval.parse_arg`.
- Do not import `os`, `sys`, `pathlib`, `subprocess`, networking, file I/O, or dynamic import tools.
- Do not inspect target text, whole-graph acceptance, judge output, or target_check output.
- Do not make a broad truth-preserving fallback. The validator must check the named rule's specific transformation.
- Unless the rule itself is `swap_sides` or explicitly about commutation, preserve Eq side orientation. Do not accept a candidate `to_expr` merely because it matches after swapping left and right sides.

## Test Constraints

- Include at least 3 positive and 3 negative tests when synthesizing a candidate.
- Positive tests should include at least one observed evidence edge with its recorded `rule_args`.
- If the observed evidence is missing assumptions required for a safe validator, reject the proposal and explain the missing contract instead of adding a positive test with invented args.
- Negative tests must include near misses: wrong RHS, missing required args when relevant, and a transformation that would be dangerously over-permissive.
- For every non-swap rule, include a negative test where the correct `to_expr` sides are reversed.
- Use the same SymPy expression string format as graph `sympy_srepr` values.

## Scientific Constraint

The candidate is not allowed to make the system approve its own mistakes. If the
rule requires assumptions, encode the assumptions as explicit `rule_args`; do not
silently accept the step for all domains.
