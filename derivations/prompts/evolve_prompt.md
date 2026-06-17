# Task: Propose a Prompt Addendum

The inner-loop derivation prompt produced a derivation that the pedagogical judge rejected. Your task: write a SHORT addendum section that, appended to the inner-loop prompt, would prevent this failure mode in future generations of similar targets.

The addendum is *local* — it's tested against this one target's evolution chain. Later, a coalescing step looks across many targets' addenda to decide which patterns are general enough to promote into the canonical prompt. Your addendum's job is to fix THIS judge failure, not to be universally optimal.

## Inputs

The target that the LLM was asked to derive:

```
<<TARGET>>
```

The judge's verdict on the most recent attempt (including each criterion's verdict and reason):

```
<<JUDGE>>
```

The current inner-loop prompt the LLM saw (canonical text plus any addenda from prior iterations of this same target's evolution chain):

```
<<CURRENT_VARIANT>>
```

## Output

Output ONLY the addendum text. No preamble, no code fences, no explanation. The addendum will be appended verbatim to the next iteration's prompt.

Format:

```
## Addendum (iteration <<ITERATION>>): <one-line failure mode name>

<the new rule, 1-3 sentences, framed as guidance the LLM should follow when generating>

<optional: 1-2 sentences of rationale tied to the specific judge criterion that failed>
```

## Constraints

- **Max 200 words.** Tight, specific.
- **Name the failing judge criterion explicitly** (e.g. `one_rule_per_edge`, `given_facts_visible`).
- **Give one actionable rule, not a general principle.** "Show every transformation as its own edge" is too vague; "When a step involves substitution, write the substituted-but-not-yet-simplified form as an explicit intermediate node before the simplification" is actionable.
- **Don't contradict existing addenda in `<<CURRENT_VARIANT>>`.** If you find yourself wanting to walk back something a prior iteration said, the chain has hit a real conflict — surface it by failing your output (write `CONTRADICTION DETECTED: <which addendum>`) rather than producing a contradictory addendum.
- **Don't broaden scope.** This addendum is one local edit, not a manifesto. The coalescing step decides what generalizes.
- **Never propose changes to verify.py, canvas_check.py, judge.py, or the judge rubric.** Those are axiomatic. You only edit the *generation* prompt.
