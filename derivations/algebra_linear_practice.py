#!/usr/bin/env python3
"""Deterministic Grade 8 algebra practice corpus generator.

The corpus is aligned to the Grade 8 algebra/linear-function frontier:
one-variable linear equations, special cases, rational coefficients, linear
functions, rate of change, modeling, and two-equation systems.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from task_contract import (
    CORPUS_SCHEMA_VERSION,
    TASK_CONTRACT_VERSION,
    build_task_contract,
    validate_task_contract,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_JSON = ROOT / "practice" / "algebra_linear_8th_grade_summer.json"
DEFAULT_MD = ROOT / "practice" / "algebra_linear_8th_grade_summer.md"
DEFAULT_TARGETS = ROOT / "targets" / "algebra_linear_8th_grade_summer.txt"

STANDARDS = {
    "8.EE.B.5": "Use graphs and equations of proportional relationships; interpret unit rate as slope.",
    "8.EE.C.7": "Solve linear equations in one variable, including one solution, no solution, and infinitely many solutions.",
    "8.EE.C.8": "Analyze and solve pairs of simultaneous linear equations.",
    "8.F.A.2": "Compare properties of functions represented in different ways.",
    "8.F.A.3": "Interpret y = mx + b as a linear function.",
    "8.F.B.4": "Construct and interpret linear functions from contexts, tables, graphs, or points.",
}

STRANDS = [
    "equation_fluency",
    "distribution_multi_step",
    "variables_both_sides",
    "special_cases_no_solution",
    "special_cases_infinite_solutions",
    "rational_coefficients",
    "modeling_one_variable",
    "slope_from_points_or_table",
    "linear_vs_nonlinear",
    "build_linear_function",
    "compare_linear_functions",
    "systems_linear_equations",
]

STRAND_LABELS = {
    "equation_fluency": "One-variable equation fluency",
    "distribution_multi_step": "Multi-step equations with distribution",
    "variables_both_sides": "Variables on both sides",
    "special_cases_no_solution": "No-solution equations",
    "special_cases_infinite_solutions": "Infinitely-many-solution equations",
    "rational_coefficients": "Equations with rational coefficients",
    "modeling_one_variable": "Modeling with one-variable equations",
    "slope_from_points_or_table": "Slope and rate of change",
    "linear_vs_nonlinear": "Linear vs. nonlinear functions",
    "build_linear_function": "Build linear functions",
    "compare_linear_functions": "Compare linear functions",
    "systems_linear_equations": "Systems of linear equations",
}

STRAND_STANDARDS = {
    "equation_fluency": ["8.EE.C.7"],
    "distribution_multi_step": ["8.EE.C.7"],
    "variables_both_sides": ["8.EE.C.7"],
    "special_cases_no_solution": ["8.EE.C.7"],
    "special_cases_infinite_solutions": ["8.EE.C.7"],
    "rational_coefficients": ["8.EE.C.7"],
    "modeling_one_variable": ["8.EE.C.7"],
    "slope_from_points_or_table": ["8.EE.B.5", "8.F.B.4"],
    "linear_vs_nonlinear": ["8.F.A.3"],
    "build_linear_function": ["8.F.B.4"],
    "compare_linear_functions": ["8.F.A.2"],
    "systems_linear_equations": ["8.EE.C.8"],
}

COEFFS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12]
SLOPES = [-4, -3, -2, -1, 1, 2, 3, 4, 5]
SOLUTIONS = [-12, -10, -8, -6, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15]
CONSTANTS = [-15, -12, -10, -9, -7, -5, -4, -3, 3, 4, 5, 7, 9, 10, 12, 15]


@dataclass(frozen=True)
class ProblemSpec:
    strand: str
    cycle: int
    ordinal: int


def fmt_frac(value: Fraction | int) -> str:
    f = value if isinstance(value, Fraction) else Fraction(value)
    if f.denominator == 1:
        return str(f.numerator)
    sign = "-" if f < 0 else ""
    return f"{sign}{abs(f.numerator)}/{f.denominator}"


def fmt_signed_const(value: Fraction | int) -> str:
    f = value if isinstance(value, Fraction) else Fraction(value)
    if f < 0:
        return f" - {fmt_frac(-f)}"
    return f" + {fmt_frac(f)}"


def fmt_term(coefficient: Fraction | int, variable: str = "x") -> str:
    c = coefficient if isinstance(coefficient, Fraction) else Fraction(coefficient)
    if c == 1:
        return variable
    if c == -1:
        return f"-{variable}"
    if c.denominator == 1:
        return f"{c.numerator}{variable}"
    return f"({fmt_frac(c)}){variable}"


def fmt_linear(coefficient: Fraction | int, constant: Fraction | int, variable: str = "x") -> str:
    c = coefficient if isinstance(coefficient, Fraction) else Fraction(coefficient)
    b = constant if isinstance(constant, Fraction) else Fraction(constant)
    if c == 0:
        return fmt_frac(b)
    if b == 0:
        return fmt_term(c, variable)
    return f"{fmt_term(c, variable)}{fmt_signed_const(b)}"


def fmt_point(point: tuple[int, int]) -> str:
    return f"({point[0]}, {point[1]})"


def line_value(m: int | Fraction, b: int | Fraction, x: int | Fraction) -> Fraction:
    return Fraction(m) * Fraction(x) + Fraction(b)


def linear_equation_problem(
    spec: ProblemSpec,
    *,
    lhs: tuple[Fraction, Fraction],
    rhs: tuple[Fraction, Fraction],
    prompt_prefix: str,
    steps: list[dict[str, str]],
    difficulty: int,
    target_suffix: str = "",
) -> dict[str, Any]:
    a, b = lhs
    c, d = rhs
    equation = f"{fmt_linear(a, b)} = {fmt_linear(c, d)}"
    if a == c and b == d:
        answer_kind = "infinitely_many_solutions"
        answer = "infinitely many solutions"
        solution_value = None
    elif a == c:
        answer_kind = "no_solution"
        answer = "no solution"
        solution_value = None
    else:
        solution = (d - b) / (a - c)
        answer_kind = "one_solution"
        solution_value = fmt_frac(solution)
        answer = f"x = {fmt_frac(solution)}"
    prompt = f"{prompt_prefix} {equation}."
    return base_problem(
        spec,
        kind="linear_equation",
        difficulty=difficulty,
        prompt=prompt,
        answer=answer,
        target_prompt=f"{prompt_prefix.lower()} {equation}{target_suffix}",
        steps=steps,
        structured={
            "lhs": {"x": fmt_frac(a), "constant": fmt_frac(b)},
            "rhs": {"x": fmt_frac(c), "constant": fmt_frac(d)},
            "answer_kind": answer_kind,
            "solution_value": solution_value,
        },
    )


def base_problem(
    spec: ProblemSpec,
    *,
    kind: str,
    difficulty: int,
    prompt: str,
    answer: str,
    target_prompt: str,
    steps: list[dict[str, str]],
    structured: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": f"alg8-lin-{spec.ordinal:03d}",
        "kind": kind,
        "strand": spec.strand,
        "strand_label": STRAND_LABELS[spec.strand],
        "standards": STRAND_STANDARDS[spec.strand],
        "difficulty": difficulty,
        "prompt": prompt,
        "answer": answer,
        "steps": steps,
        "target_prompt": target_prompt,
        "structured": structured,
    }


def make_problem(spec: ProblemSpec) -> dict[str, Any]:
    strand = spec.strand
    i = spec.cycle
    strand_index = STRANDS.index(strand)
    x = Fraction(SOLUTIONS[(i + 3 * strand_index) % len(SOLUTIONS)])
    y = Fraction(SOLUTIONS[(i + 5 * strand_index + 4) % len(SOLUTIONS)])
    a = Fraction(COEFFS[(i + strand_index) % len(COEFFS)])
    b = Fraction(CONSTANTS[(2 * i + strand_index) % len(CONSTANTS)])
    c = Fraction(COEFFS[(3 * i + strand_index + 4) % len(COEFFS)])
    if c == a:
        c += 1

    if strand == "equation_fluency":
        rhs = a * x + b
        return linear_equation_problem(
            spec,
            lhs=(a, b),
            rhs=(0, rhs),
            prompt_prefix="Solve",
            target_suffix=" for x",
            difficulty=1,
            steps=[
                {"action": f"Move the constant term {fmt_frac(b)} to the other side.", "equation": f"{fmt_term(a)} = {fmt_frac(a * x)}"},
                {"action": f"Divide both sides by {fmt_frac(a)}.", "equation": f"x = {fmt_frac(x)}"},
            ],
        )

    if strand == "distribution_multi_step":
        inner = b
        outside = a
        extra = Fraction(CONSTANTS[(i + 5) % len(CONSTANTS)])
        rhs = outside * (x + inner) + extra
        equation_text = f"{fmt_frac(outside)}(x{fmt_signed_const(inner)}){fmt_signed_const(extra)} = {fmt_frac(rhs)}"
        return base_problem(
            spec,
            kind="linear_equation",
            difficulty=3,
            prompt=f"Solve {equation_text}.",
            answer=f"x = {fmt_frac(x)}",
            target_prompt=f"solve {equation_text} for x by distributing first",
            steps=[
                {"action": "Distribute first.", "equation": f"{fmt_linear(outside, outside * inner + extra)} = {fmt_frac(rhs)}"},
                {"action": "Move the constant term to the other side.", "equation": f"{fmt_term(outside)} = {fmt_frac(outside * x)}"},
                {"action": f"Divide both sides by {fmt_frac(outside)}.", "equation": f"x = {fmt_frac(x)}"},
            ],
            structured={
                "lhs": {"x": fmt_frac(outside), "constant": fmt_frac(outside * inner + extra)},
                "rhs": {"x": "0", "constant": fmt_frac(rhs)},
                "answer_kind": "one_solution",
                "solution_value": fmt_frac(x),
            },
        )

    if strand == "variables_both_sides":
        d = (a - c) * x + b
        return linear_equation_problem(
            spec,
            lhs=(a, b),
            rhs=(c, d),
            prompt_prefix="Solve",
            target_suffix=" by collecting variable terms",
            difficulty=3,
            steps=[
                {"action": f"Subtract {fmt_term(c)} from both sides.", "equation": f"{fmt_linear(a - c, b)} = {fmt_frac(d)}"},
                {"action": "Move the constant term to the other side.", "equation": f"{fmt_term(a - c)} = {fmt_frac((a - c) * x)}"},
                {"action": f"Divide both sides by {fmt_frac(a - c)}.", "equation": f"x = {fmt_frac(x)}"},
            ],
        )

    if strand == "special_cases_no_solution":
        d = b + Fraction(i % 5 + 1)
        return linear_equation_problem(
            spec,
            lhs=(a, b),
            rhs=(a, d),
            prompt_prefix="Determine whether this equation has one solution, no solution, or infinitely many solutions:",
            difficulty=3,
            steps=[
                {"action": "Subtract the same variable term from both sides.", "equation": f"{fmt_frac(b)} = {fmt_frac(d)}"},
                {"action": "The constants are different, so the equation is false.", "equation": "no solution"},
            ],
        )

    if strand == "special_cases_infinite_solutions":
        return linear_equation_problem(
            spec,
            lhs=(a, b),
            rhs=(a, b),
            prompt_prefix="Determine whether this equation has one solution, no solution, or infinitely many solutions:",
            difficulty=3,
            steps=[
                {"action": "Subtract the same variable term from both sides.", "equation": f"{fmt_frac(b)} = {fmt_frac(b)}"},
                {"action": "Both sides are identical for every x.", "equation": "infinitely many solutions"},
            ],
        )

    if strand == "rational_coefficients":
        coefficient = Fraction((i % 5) + 1, (i % 4) + 2)
        constant = Fraction(CONSTANTS[(i + 2) % len(CONSTANTS)], (i % 3) + 1)
        rhs = coefficient * x + constant
        return linear_equation_problem(
            spec,
            lhs=(coefficient, constant),
            rhs=(0, rhs),
            prompt_prefix="Solve",
            target_suffix=" for x",
            difficulty=4,
            steps=[
                {"action": "Move the constant term to the other side.", "equation": f"{fmt_term(coefficient)} = {fmt_frac(coefficient * x)}"},
                {"action": f"Divide by {fmt_frac(coefficient)}.", "equation": f"x = {fmt_frac(x)}"},
            ],
        )

    if strand == "modeling_one_variable":
        rate = int(a)
        start = abs(int(b))
        classes = (i % 12) + 1
        total = rate * classes + start
        prompt = f"A summer program charges ${start} to register plus ${rate} per class. The total paid is ${total}. How many classes were taken?"
        return base_problem(
            spec,
            kind="linear_equation",
            difficulty=3,
            prompt=prompt,
            answer=f"x = {classes} classes",
            target_prompt=f"model and solve {start} + {rate}x = {total} for x",
            steps=[
                {"action": "Write the model.", "equation": f"{start} + {rate}x = {total}"},
                {"action": f"Subtract {start} from both sides.", "equation": f"{rate}x = {rate * classes}"},
                {"action": f"Divide by {rate}.", "equation": f"x = {classes}"},
            ],
            structured={
                "lhs": {"x": fmt_frac(rate), "constant": fmt_frac(start)},
                "rhs": {"x": "0", "constant": fmt_frac(total)},
                "answer_kind": "one_solution",
                "solution_value": fmt_frac(classes),
            },
        )

    if strand == "slope_from_points_or_table":
        m = SLOPES[(i + 2) % len(SLOPES)]
        intercept = int(b)
        x1 = i % 6 - 2
        x2 = x1 + (i % 4 + 2)
        p1 = (x1, int(line_value(m, intercept, x1)))
        p2 = (x2, int(line_value(m, intercept, x2)))
        prompt = f"Find the slope of the line through {fmt_point(p1)} and {fmt_point(p2)}."
        return base_problem(
            spec,
            kind="slope",
            difficulty=2,
            prompt=prompt,
            answer=f"slope = {fmt_frac(m)}",
            target_prompt=f"find the slope of the line through {fmt_point(p1)} and {fmt_point(p2)}",
            steps=[
                {"action": "Compute change in y.", "equation": f"{p2[1]} - {p1[1]} = {p2[1] - p1[1]}"},
                {"action": "Compute change in x.", "equation": f"{p2[0]} - {p1[0]} = {p2[0] - p1[0]}"},
                {"action": "Divide rise by run.", "equation": f"slope = {fmt_frac(Fraction(p2[1] - p1[1], p2[0] - p1[0]))}"},
            ],
            structured={"points": [p1, p2], "slope": fmt_frac(Fraction(m))},
        )

    if strand == "linear_vs_nonlinear":
        linear = i % 2 == 0
        if linear:
            m = SLOPES[i % len(SLOPES)]
            intercept = int(b)
            table = [[n, int(line_value(m, intercept, n))] for n in range(0, 4)]
            answer = f"linear; constant rate of change {fmt_frac(m)}"
        else:
            shift = i
            table = [[n, n * n + shift] for n in range(0, 4)]
            answer = "not linear; the rate of change is not constant"
        prompt = f"Decide whether the table {table} represents a linear function."
        return base_problem(
            spec,
            kind="linear_classification",
            difficulty=2,
            prompt=prompt,
            answer=answer,
            target_prompt=f"decide whether the table {table} represents a linear function",
            steps=[
                {"action": "Compare consecutive changes in y.", "equation": "constant changes mean linear"},
            ],
            structured={"table": table, "is_linear": linear},
        )

    if strand == "build_linear_function":
        m = SLOPES[(i + 4) % len(SLOPES)]
        intercept = int(b)
        p1 = (0, intercept)
        p2 = (2, int(line_value(m, intercept, 2)))
        prompt = f"Write an equation y = mx + b for the line through {fmt_point(p1)} and {fmt_point(p2)}."
        return base_problem(
            spec,
            kind="linear_function",
            difficulty=3,
            prompt=prompt,
            answer=f"y = {fmt_linear(m, intercept)}",
            target_prompt=f"write the linear function through {fmt_point(p1)} and {fmt_point(p2)} in slope-intercept form",
            steps=[
                {"action": "Find the slope.", "equation": f"m = {fmt_frac(m)}"},
                {"action": "Use the point where x = 0 as the initial value.", "equation": f"b = {intercept}"},
                {"action": "Write y = mx + b.", "equation": f"y = {fmt_linear(m, intercept)}"},
            ],
            structured={"slope": fmt_frac(Fraction(m)), "intercept": fmt_frac(Fraction(intercept)), "points": [p1, p2]},
        )

    if strand == "compare_linear_functions":
        m1 = SLOPES[(i + 1) % len(SLOPES)]
        b1 = int(b)
        m2 = SLOPES[(i + 5) % len(SLOPES)]
        if m2 == m1:
            m2 += 1
        b2 = int(CONSTANTS[(i + 6) % len(CONSTANTS)])
        table = [[0, b2], [2, int(line_value(m2, b2, 2))], [4, int(line_value(m2, b2, 4))]]
        winner = "A" if m1 > m2 else "B"
        prompt = f"Function A is y = {fmt_linear(m1, b1)}. Function B is shown by the table {table}. Which function has the greater rate of change?"
        return base_problem(
            spec,
            kind="function_comparison",
            difficulty=3,
            prompt=prompt,
            answer=f"Function {winner}; rates are A = {fmt_frac(m1)}, B = {fmt_frac(m2)}",
            target_prompt=f"compare the rates of change of y = {fmt_linear(m1, b1)} and the table {table}",
            steps=[
                {"action": "Read Function A's slope from its equation.", "equation": f"m_A = {fmt_frac(m1)}"},
                {"action": "Compute Function B's slope from the table.", "equation": f"m_B = {fmt_frac(m2)}"},
                {"action": "Compare the slopes.", "equation": f"Function {winner} has the greater rate of change"},
            ],
            structured={
                "function_a": {"slope": fmt_frac(Fraction(m1)), "intercept": fmt_frac(Fraction(b1))},
                "function_b": {"table": table, "slope": fmt_frac(Fraction(m2)), "intercept": fmt_frac(Fraction(b2))},
                "greater_rate": winner,
            },
        )

    if strand == "systems_linear_equations":
        sol_x = int(x)
        sol_y = int(y)
        a1 = int(a)
        b1 = int((i % 4) + 1)
        a2 = int(c)
        b2 = int((i % 5) + 2)
        if a1 * b2 == a2 * b1:
            b2 += 1
        d1 = a1 * sol_x + b1 * sol_y
        d2 = a2 * sol_x + b2 * sol_y
        eq1 = f"{fmt_linear(a1, 0)} + {fmt_term(b1, 'y')} = {d1}"
        eq2 = f"{fmt_linear(a2, 0)} + {fmt_term(b2, 'y')} = {d2}"
        prompt = f"Solve the system: {eq1}; {eq2}."
        return base_problem(
            spec,
            kind="linear_system",
            difficulty=4,
            prompt=prompt,
            answer=f"x = {sol_x}, y = {sol_y}",
            target_prompt=f"solve the system {eq1}; {eq2}",
            steps=[
                {"action": "Use elimination or substitution.", "equation": "keep both equations equivalent"},
                {"action": "Solve for one variable, then substitute back.", "equation": f"x = {sol_x}, y = {sol_y}"},
            ],
            structured={
                "equations": [
                    {"x": a1, "y": b1, "constant": d1},
                    {"x": a2, "y": b2, "constant": d2},
                ],
                "solution": {"x": sol_x, "y": sol_y},
            },
        )

    raise ValueError(f"unknown strand: {strand}")


def build_corpus(total: int = 240, set_size: int = 10) -> dict[str, Any]:
    if total % len(STRANDS) != 0:
        raise ValueError(f"total must be divisible by {len(STRANDS)} strands")
    if total % set_size != 0:
        raise ValueError("total must be divisible by set_size")

    source_problems = []
    ordinal = 1
    cycles = total // len(STRANDS)
    for cycle in range(cycles):
        for strand in STRANDS:
            source_problems.append(make_problem(ProblemSpec(strand=strand, cycle=cycle, ordinal=ordinal)))
            ordinal += 1

    tasks = [build_task_contract(problem) for problem in source_problems]

    daily_sets = []
    for start in range(0, len(tasks), set_size):
        set_index = start // set_size + 1
        daily_sets.append({
            "id": f"alg8-linear-day-{set_index:02d}",
            "title": f"Day {set_index}: Grade 8 algebra practice",
            "task_ids": [task["id"] for task in tasks[start:start + set_size]],
        })

    return {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "task_contract_version": TASK_CONTRACT_VERSION,
        "course": "Grade 8 mathematics",
        "frontier": "algebra, linear equations, linear functions, and systems",
        "use_case": "summer school practice",
        "standards_source": {
            "name": "Common Core State Standards Mathematics Grade 8",
            "urls": [
                "https://www.thecorestandards.org/Math/Content/8/introduction/",
                "https://www.thecorestandards.org/Math/Content/8/F/",
            ],
            "note": "This corpus targets the Grade 8 algebra and linear-function frontier, not the full Grade 8 course.",
        },
        "standards": STANDARDS,
        "total_tasks": len(tasks),
        "set_size": set_size,
        "daily_set_count": len(daily_sets),
        "strands": [
            {
                "id": strand,
                "label": STRAND_LABELS[strand],
                "standards": STRAND_STANDARDS[strand],
            }
            for strand in STRANDS
        ],
        "daily_sets": daily_sets,
        "contract_manifest": {task["id"]: task["contract_digest"] for task in tasks},
        "tasks": tasks,
    }


def _task_by_id(corpus: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in corpus["tasks"]}


def parse_fraction(value: str | int) -> Fraction:
    return Fraction(value)


def verify_linear_equation(problem: dict[str, Any]) -> None:
    data = problem["structured"]
    a = parse_fraction(data["lhs"]["x"])
    b = parse_fraction(data["lhs"]["constant"])
    c = parse_fraction(data["rhs"]["x"])
    d = parse_fraction(data["rhs"]["constant"])
    answer_kind = data["answer_kind"]
    if a == c and b == d:
        expected_kind = "infinitely_many_solutions"
        expected_value = None
    elif a == c:
        expected_kind = "no_solution"
        expected_value = None
    else:
        expected_kind = "one_solution"
        expected_value = (d - b) / (a - c)
    if answer_kind != expected_kind:
        raise AssertionError(f"{problem['id']} answer kind mismatch")
    if expected_kind == "one_solution":
        if parse_fraction(data["solution_value"]) != expected_value:
            raise AssertionError(f"{problem['id']} solution value mismatch")
        if a * expected_value + b != c * expected_value + d:
            raise AssertionError(f"{problem['id']} solution does not satisfy equation")
    if expected_kind == "no_solution" and "no solution" not in problem["answer"]:
        raise AssertionError(f"{problem['id']} answer text should say no solution")
    if expected_kind == "infinitely_many_solutions" and "infinitely many" not in problem["answer"]:
        raise AssertionError(f"{problem['id']} answer text should say infinitely many")


def verify_slope(problem: dict[str, Any]) -> None:
    p1, p2 = [tuple(point) for point in problem["structured"]["points"]]
    expected = Fraction(p2[1] - p1[1], p2[0] - p1[0])
    if parse_fraction(problem["structured"]["slope"]) != expected:
        raise AssertionError(f"{problem['id']} slope mismatch")


def verify_linear_classification(problem: dict[str, Any]) -> None:
    table = problem["structured"]["table"]
    deltas = [table[i + 1][1] - table[i][1] for i in range(len(table) - 1)]
    is_linear = len(set(deltas)) == 1
    if bool(problem["structured"]["is_linear"]) != is_linear:
        raise AssertionError(f"{problem['id']} linear classification mismatch")


def verify_linear_function(problem: dict[str, Any]) -> None:
    m = parse_fraction(problem["structured"]["slope"])
    b = parse_fraction(problem["structured"]["intercept"])
    for x, y in problem["structured"]["points"]:
        if m * x + b != y:
            raise AssertionError(f"{problem['id']} function does not fit point")


def verify_function_comparison(problem: dict[str, Any]) -> None:
    a = problem["structured"]["function_a"]
    b = problem["structured"]["function_b"]
    m_a = parse_fraction(a["slope"])
    table = b["table"]
    m_b = Fraction(table[1][1] - table[0][1], table[1][0] - table[0][0])
    if parse_fraction(b["slope"]) != m_b:
        raise AssertionError(f"{problem['id']} function B slope mismatch")
    expected = "A" if m_a > m_b else "B"
    if problem["structured"]["greater_rate"] != expected:
        raise AssertionError(f"{problem['id']} greater rate mismatch")


def verify_linear_system(problem: dict[str, Any]) -> None:
    equations = problem["structured"]["equations"]
    solution = problem["structured"]["solution"]
    x = Fraction(solution["x"])
    y = Fraction(solution["y"])
    e1, e2 = equations
    det = e1["x"] * e2["y"] - e2["x"] * e1["y"]
    if det == 0:
        raise AssertionError(f"{problem['id']} system determinant should be nonzero")
    for equation in equations:
        if equation["x"] * x + equation["y"] * y != equation["constant"]:
            raise AssertionError(f"{problem['id']} system solution mismatch")


def verify_problem(problem: dict[str, Any]) -> None:
    kind = problem["kind"]
    if kind == "linear_equation":
        verify_linear_equation(problem)
    elif kind == "slope":
        verify_slope(problem)
    elif kind == "linear_classification":
        verify_linear_classification(problem)
    elif kind == "linear_function":
        verify_linear_function(problem)
    elif kind == "function_comparison":
        verify_function_comparison(problem)
    elif kind == "linear_system":
        verify_linear_system(problem)
    else:
        raise AssertionError(f"{problem['id']} unknown kind {kind}")


def verify_corpus(corpus: dict[str, Any]) -> None:
    if corpus.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise AssertionError(f"unexpected corpus schema: {corpus.get('schema_version')!r}")
    if corpus.get("task_contract_version") != TASK_CONTRACT_VERSION:
        raise AssertionError(f"unexpected task contract version: {corpus.get('task_contract_version')!r}")
    tasks = corpus["tasks"]
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate task ids")
    prompts = [task["display"]["prompt"] for task in tasks]
    if len(prompts) != len(set(prompts)):
        raise AssertionError("duplicate prompts")
    if corpus["total_tasks"] != len(tasks):
        raise AssertionError("total_tasks does not match tasks")
    counts = Counter(task["metadata"]["strand"] for task in tasks)
    expected = corpus["total_tasks"] // len(STRANDS)
    if set(counts) != set(STRANDS):
        raise AssertionError(f"missing strands: {set(STRANDS) - set(counts)}")
    if any(count != expected for count in counts.values()):
        raise AssertionError(f"unbalanced strand counts: {counts}")
    manifest = corpus["contract_manifest"]
    if set(manifest) != set(ids):
        raise AssertionError("contract_manifest task ids do not match tasks")
    for task in tasks:
        validate_task_contract(task)
        if manifest[task["id"]] != task["contract_digest"]:
            raise AssertionError(f"{task['id']} manifest digest mismatch")
    task_by_id = _task_by_id(corpus)
    for daily_set in corpus["daily_sets"]:
        if len(daily_set["task_ids"]) != corpus["set_size"]:
            raise AssertionError(f"{daily_set['id']} has wrong set size")
        for task_id in daily_set["task_ids"]:
            if task_id not in task_by_id:
                raise AssertionError(f"{daily_set['id']} references missing task {task_id}")


def render_targets(corpus: dict[str, Any]) -> str:
    lines = [
        "# Grade 8 algebra: linear equations, linear functions, and systems",
        "# Generated from derivations/algebra_linear_practice.py",
        f"# Total targets: {corpus['total_tasks']}",
        "# Standards focus: 8.EE.B.5, 8.EE.C.7, 8.EE.C.8, 8.F.A.2, 8.F.A.3, 8.F.B.4",
        "",
    ]
    for task in corpus["tasks"]:
        lines.append(task["display"]["prompt"])
    return "\n".join(lines) + "\n"


def render_markdown(corpus: dict[str, Any]) -> str:
    task_by_id = _task_by_id(corpus)
    lines = [
        "# Grade 8 Algebra Summer Practice",
        "",
        "Focus: linear equations, linear functions, and systems.",
        f"Total problems: {corpus['total_tasks']}",
        f"Daily sets: {corpus['daily_set_count']} sets of {corpus['set_size']}",
        "",
        "## Skill Mix",
        "",
    ]
    for strand in corpus["strands"]:
        lines.append(f"- {strand['label']} ({', '.join(strand['standards'])})")
    lines.extend(["", "## Practice Sets", ""])
    for daily_set in corpus["daily_sets"]:
        lines.extend([f"### {daily_set['title']}", ""])
        for index, task_id in enumerate(daily_set["task_ids"], start=1):
            task = task_by_id[task_id]
            lines.append(f"{index}. {task['display']['prompt']}")
        lines.append("")

    lines.extend(["## Answer Key", ""])
    for daily_set in corpus["daily_sets"]:
        answers = []
        for index, task_id in enumerate(daily_set["task_ids"], start=1):
            answers.append(f"{index}. {task_by_id[task_id]['display']['answer']}")
        lines.append(f"### {daily_set['title']}")
        lines.append("; ".join(answers))
        lines.append("")
    return "\n".join(lines)


def write_outputs(
    corpus: dict[str, Any],
    json_path: Path,
    markdown_path: Path | None,
    targets_path: Path | None,
) -> None:
    verify_corpus(corpus)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(corpus))
    if targets_path is not None:
        targets_path.parent.mkdir(parents=True, exist_ok=True)
        targets_path.write_text(render_targets(corpus))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=240)
    parser.add_argument("--set-size", type=int, default=10)
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument("--markdown", default=str(DEFAULT_MD))
    parser.add_argument("--targets", default=str(DEFAULT_TARGETS))
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    corpus = build_corpus(total=args.total, set_size=args.set_size)
    markdown_path = None if args.json_only else Path(args.markdown)
    targets_path = None if args.json_only else Path(args.targets)
    write_outputs(corpus, Path(args.json), markdown_path, targets_path)
    print(json.dumps({
        "json": args.json,
        "markdown": None if args.json_only else args.markdown,
        "targets": None if args.json_only else args.targets,
        "total_tasks": corpus["total_tasks"],
        "daily_set_count": corpus["daily_set_count"],
        "strand_count": len(corpus["strands"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
