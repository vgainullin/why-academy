"""Validator for rule: divide_both_sides.

Transformation: Eq(A, B) -> Eq(A/d, B/d).

Accepts the divisor under any of these arg-key aliases the inner-loop LLM
has been observed to emit: 'divisor' (canonical), 'factor', 'constant'. The
canonical name is 'divisor'; the others are accepted to unblock the corpus
of existing graphs without requiring a synchronized prompt update. Future
generations are nudged toward 'divisor' via prompts/generate_derivation.md.

Note: does not verify d != 0; that constraint is the derivation author's
responsibility. If d contains free symbols, sympy may not simplify fully
without assumptions — cancel() is attempted as a fallback.
"""
from sympy import Eq
from sympy_eval import align_symbols_to, expr_equal_zero, parse_arg

RULE_NAME = "divide_both_sides"
_DIVISOR_ARG_ALIASES = ("divisor", "factor", "constant")


def validate(from_expr, to_expr, args):
    try:
        if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
            return ("FAIL", "both endpoints must be Eq")
        if not args:
            return ("FAIL", "missing required arg (any of: divisor/factor/constant)")
        raw_divisor = None
        used_key = None
        for k in _DIVISOR_ARG_ALIASES:
            if k in args:
                raw_divisor = args[k]
                used_key = k
                break
        if raw_divisor is None:
            return ("FAIL", f"missing divisor arg (looked for {_DIVISOR_ARG_ALIASES}); got keys {list(args)}")
        try:
            d = parse_arg(raw_divisor)
            d = align_symbols_to(from_expr, d)
        except Exception as e:
            return ("FAIL", f"could not parse rule_args.{used_key}: {e}")

        expected_lhs = from_expr.lhs / d
        expected_rhs = from_expr.rhs / d

        if expr_equal_zero(to_expr.lhs - expected_lhs) and expr_equal_zero(to_expr.rhs - expected_rhs):
            return ("PASS", f"divided both sides by {d} (arg key '{used_key}')")
        return (
            "FAIL",
            f"dividing by {d} should give Eq({expected_lhs}, {expected_rhs}); "
            f"got Eq({to_expr.lhs}, {to_expr.rhs})",
        )
    except Exception as e:
        return ("FAIL", f"validator raised: {e}")
