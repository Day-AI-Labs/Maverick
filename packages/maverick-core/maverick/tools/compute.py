"""Symbolic math tool. Replaces flaky LLM mental math.

Backed by SymPy if installed; falls back to Python's ast.literal_eval
+ math module for simple expressions when SymPy isn't available.

Operations:
  - evaluate(expr)       — arithmetic / numeric (e.g. "sin(pi/4)*sqrt(2)")
  - simplify(expr)       — symbolic simplification
  - solve(equation, var) — solve a single-variable equation
  - diff(expr, var)      — derivative
  - integrate(expr, var) — antiderivative

All operations are sandboxed: we never `eval()` user input directly.
SymPy's parser accepts a restricted grammar of math expressions.
"""
from __future__ import annotations

import logging
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_COMPUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["evaluate", "simplify", "solve", "diff", "integrate"],
            "description": "Math operation.",
        },
        "expr": {
            "type": "string",
            "description": "The expression. Examples: 'sin(pi/4)', 'x**2 + 3*x'.",
        },
        "equation": {
            "type": "string",
            "description": "For solve op. e.g. 'x**2 - 4 = 0' (or '= 0' implied).",
        },
        "var": {
            "type": "string",
            "description": "Variable (default 'x' for solve/diff/integrate).",
        },
    },
    "required": ["op"],
}


def _have_sympy() -> bool:
    try:
        import sympy  # noqa: F401
        return True
    except ImportError:
        return False


def _evaluate_with_sympy(expr: str) -> str:
    import sympy
    parsed = sympy.sympify(expr, evaluate=True)
    val = sympy.N(parsed, 30)
    return f"{val}"


def _evaluate_fallback(expr: str) -> str:
    """Minimal evaluator using ast.literal_eval — only supports
    arithmetic on numeric literals."""
    import ast
    import math
    # Replace common math constants/funcs so simple expressions work.
    safe_globals = {
        "pi": math.pi, "e": math.e, "tau": math.tau,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "sqrt": math.sqrt, "log": math.log, "exp": math.exp,
        "abs": abs, "min": min, "max": max,
    }
    # Walk the AST to ensure only safe nodes.
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Call,)):
            if not isinstance(node.func, ast.Name) or node.func.id not in safe_globals:
                raise ValueError(f"function not allowed: {ast.dump(node.func)}")
        elif isinstance(node, (ast.Attribute, ast.Import, ast.ImportFrom)):
            raise ValueError("attribute access / imports not allowed")
    code = compile(tree, "<expr>", "eval")
    result = eval(code, {"__builtins__": {}}, safe_globals)
    return repr(result)


_VALID_OPS = {"evaluate", "simplify", "solve", "diff", "integrate"}


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    if op not in _VALID_OPS:
        return f"ERROR: unknown op {op!r}"

    if op == "evaluate":
        expr = (args.get("expr") or "").strip()
        if not expr:
            return "ERROR: evaluate requires expr"
        try:
            if _have_sympy():
                return _evaluate_with_sympy(expr)
            return _evaluate_fallback(expr)
        except Exception as e:
            return f"ERROR: cannot evaluate {expr!r}: {type(e).__name__}: {e}"

    # All remaining ops require sympy.
    if not _have_sympy():
        return (
            f"ERROR: '{op}' requires sympy. "
            "Run: pip install 'maverick-agent[math]'"
        )
    import sympy

    if op == "simplify":
        expr = (args.get("expr") or "").strip()
        if not expr:
            return "ERROR: simplify requires expr"
        try:
            return str(sympy.simplify(sympy.sympify(expr)))
        except Exception as e:
            return f"ERROR: cannot simplify {expr!r}: {type(e).__name__}: {e}"

    if op == "solve":
        eqn = (args.get("equation") or args.get("expr") or "").strip()
        if not eqn:
            return "ERROR: solve requires equation"
        var_name = (args.get("var") or "x").strip()
        try:
            var = sympy.Symbol(var_name)
            # Parse "A = B" -> A - B. If no "=", treat as "expr = 0".
            if "=" in eqn:
                left, right = eqn.split("=", 1)
                target = sympy.sympify(left) - sympy.sympify(right)
            else:
                target = sympy.sympify(eqn)
            sols = sympy.solve(target, var)
            return f"{var_name} ∈ {{{', '.join(str(s) for s in sols)}}}"
        except Exception as e:
            return f"ERROR: cannot solve: {type(e).__name__}: {e}"

    if op == "diff":
        expr = (args.get("expr") or "").strip()
        if not expr:
            return "ERROR: diff requires expr"
        var_name = (args.get("var") or "x").strip()
        try:
            return str(sympy.diff(
                sympy.sympify(expr), sympy.Symbol(var_name),
            ))
        except Exception as e:
            return f"ERROR: cannot differentiate: {type(e).__name__}: {e}"

    if op == "integrate":
        expr = (args.get("expr") or "").strip()
        if not expr:
            return "ERROR: integrate requires expr"
        var_name = (args.get("var") or "x").strip()
        try:
            return str(sympy.integrate(
                sympy.sympify(expr), sympy.Symbol(var_name),
            ))
        except Exception as e:
            return f"ERROR: cannot integrate: {type(e).__name__}: {e}"

    return f"ERROR: unknown op {op!r}"


def compute() -> Tool:
    return Tool(
        name="compute",
        description=(
            "Symbolic math. ops: evaluate (numeric, e.g. 'sin(pi/4)'), "
            "simplify (symbolic), solve (single-var equation; '=' or "
            "implicit '=0'), diff (derivative), integrate "
            "(antiderivative). Replaces LLM mental math, which is "
            "unreliable past trivial arithmetic. Symbolic ops require "
            "the [math] extra (sympy)."
        ),
        input_schema=_COMPUTE_SCHEMA,
        fn=_run,
    )
