"""Shared sympy eval namespace + arg parsing.

verify.py, to_canvas.py, canvas_check.py, and every validator under validators/
all need to coerce strings to sympy expressions in the SAME namespace, otherwise
symbol assumptions diverge and simplify() can't cancel things that should cancel.

Standard symbols pre-declared real (matches the contract in prompts/generate_derivation.md):
  x y z r t u v theta phi n k m a b c
"""
from __future__ import annotations
import ast
import sympy as _sp

_STD_NAMES = "x y z r t u v theta phi n k m a b c"
_STD = _sp.symbols(_STD_NAMES, real=True)
EVAL_NS: dict = {s.name: s for s in _STD}
for _name in dir(_sp):
    if not _name.startswith("_"):
        EVAL_NS.setdefault(_name, getattr(_sp, _name))

_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.Call,
    ast.Name,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.keyword,
    ast.Tuple,
    ast.List,
    ast.Load,
)
_ALLOWED_AST_OPERATORS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
)


def _validate_expr_ast(node: ast.AST) -> None:
    """Reject Python syntax outside the small expression subset used by graphs."""
    for child in ast.walk(node):
        if isinstance(child, _ALLOWED_AST_OPERATORS):
            continue
        if not isinstance(child, _ALLOWED_AST_NODES):
            raise ValueError(f"disallowed syntax in sympy expression: {type(child).__name__}")
        if isinstance(child, ast.Name):
            if child.id.startswith("__") or child.id not in EVAL_NS:
                raise NameError(f"name not allowed in sympy expression: {child.id}")
        if isinstance(child, ast.Call):
            if not isinstance(child.func, ast.Name):
                raise ValueError("only direct calls to whitelisted SymPy names are allowed")
        if isinstance(child, ast.keyword) and child.arg is None:
            raise ValueError("**kwargs are not allowed in sympy expressions")


def safe_eval_sympy_expr(s: str):
    """Evaluate a SymPy expression string without exposing Python builtins.

    The graph format is intentionally a Python-expression subset, not arbitrary
    Python. This parser allows direct SymPy constructors/functions, standard
    symbols, constants, keyword args such as evaluate=False, and arithmetic
    operators. It rejects attributes, imports, comprehensions, lambdas,
    subscripts, and any unknown names.
    """
    tree = ast.parse(s, mode="eval")
    _validate_expr_ast(tree)
    compiled = compile(tree, "<sympy_expr>", "eval")
    return eval(compiled, {"__builtins__": {}}, EVAL_NS)


def parse_srepr(s: str):
    """Parse a sympy_srepr / SymPy expression string in the standard namespace."""
    return safe_eval_sympy_expr(s)


def parse_arg(v):
    """Coerce a rule_args value (JSON: int, float, or string) to a sympy expression."""
    if v is None:
        return None
    if isinstance(v, bool):
        return _sp.sympify(v)
    if isinstance(v, (int, float)):
        return _sp.sympify(v)
    if isinstance(v, str):
        return safe_eval_sympy_expr(v)
    return _sp.sympify(v)


def strip_symbol_assumptions(expr):
    """Return expr with Symbols matched only by name.

    Generated graphs mix bare prompt symbols such as `v` (predeclared real) with
    explicit `Symbol('v')` values (assumption-free). Verification should not
    reject a rule just because those assumption objects differ.
    """
    try:
        return expr.xreplace({s: _sp.Symbol(s.name) for s in expr.atoms(_sp.Symbol)})
    except Exception:
        return expr


def expr_equal_zero(expr) -> bool:
    expr = strip_symbol_assumptions(expr)
    return _sp.simplify(expr) == 0 or _sp.simplify(_sp.cancel(expr)) == 0


def align_symbols_to(reference, expr):
    """Replace symbols in expr with same-name symbols from reference."""
    try:
        by_name = {}
        for sym in sorted(reference.free_symbols, key=lambda s: (s.name, str(s.assumptions0))):
            by_name.setdefault(sym.name, sym)
        repl = {sym: by_name[sym.name] for sym in expr.free_symbols if sym.name in by_name}
        return expr.xreplace(repl)
    except Exception:
        return expr
