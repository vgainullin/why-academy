"""Validator for rule: subtract_constant_from_both_sides.

Transformation: Eq(a, b) -> Eq(a - c, b - c).
Required arg: constant.

Equivalent to add_constant_to_both_sides with negated constant. Kept as its own
file because the inner-loop prompt's generated rule names treat add/subtract as
distinct rules; merging them at the validator layer would hide that signal.
"""
from sympy import Eq

from sympy_eval import align_symbols_to, expr_equal_zero, parse_arg

RULE_NAME = "subtract_constant_from_both_sides"


def validate(from_expr, to_expr, args):
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("FAIL", "both endpoints must be Eq")
    if not args or "constant" not in args:
        return ("FAIL", "missing required arg 'constant'")
    try:
        c = parse_arg(args["constant"])
        c = align_symbols_to(from_expr, c)
    except Exception as e:
        return ("FAIL", f"could not parse rule_args.constant: {e}")
    expected_lhs = from_expr.lhs - c
    expected_rhs = from_expr.rhs - c
    if expr_equal_zero(to_expr.lhs - expected_lhs) and expr_equal_zero(to_expr.rhs - expected_rhs):
        return ("PASS", f"subtracted {c} from both sides")
    if expr_equal_zero(to_expr.lhs - expected_rhs) and expr_equal_zero(to_expr.rhs - expected_lhs):
        return ("PASS", f"subtracted {c} from both sides (swapped orientation)")
    return ("FAIL",
            f"subtracting {c} should give Eq({expected_lhs}, {expected_rhs}); got Eq({to_expr.lhs}, {to_expr.rhs})")
