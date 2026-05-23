# Task: Propose a Failure-Conditioned Prompt Addendum

The derivation attempt failed at a typed gate: verifier, canvas, judge, or target.
Write a SHORT addendum section that, appended to the inner-loop prompt, repairs
this failure mode on the next attempt.

## Target

```
<<TARGET>>
```

## Failure Diagnosis

```json
<<DIAGNOSIS>>
```

## Current Inner-Loop Prompt Variant

```
<<CURRENT_VARIANT>>
```

## Output

Output ONLY the addendum text. No preamble, no code fences, no explanation.

Format:

```
## Addendum (iteration <<ITERATION>>): <one-line failure mode name>

<the new rule, 1-3 sentences, framed as guidance the LLM should follow when generating>

<optional: 1-2 sentences of rationale tied to the exact failure class>
```

## Constraints

- Max 220 words.
- Name the failed gate and failure class explicitly.
- Give one actionable rule, not a broad principle.
- Preserve the requested target exactly. Do not repair a failure by weakening, rewriting, or stopping short of the target equation.
- Stay within the current graph schema: every graph node in `nodes` must remain an `Eq(...)` expression. Do not invent non-equation nodes, fact container nodes, assumption nodes, or extra top-level JSON fields.
- If the target contains explicit givens, represent each one as an ordinary visible `Eq(...)` node. Do not introduce a given with a non-truth-preserving edge; leave it disconnected if no one-rule algebraic edge can introduce it.
- For canvas failures, prefer renderable SymPy forms and avoid unevaluated or metadata-like constructs that round-trip poorly.
- For verifier failures, avoid repeating the failed rule shape. If the rule lacks validator support, use smaller truth-preserving algebraic edges that existing validators can check.
- Do not propose changes to verifier, canvas, judge, schema, or validators. The addendum only changes generation behavior.
- If a prior addendum in the current variant directly conflicts with the needed repair, output `CONTRADICTION DETECTED: <which addendum>`.
