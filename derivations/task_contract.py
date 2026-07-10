#!/usr/bin/env python3
"""Typed, immutable task contracts for deterministic derivation acceptance.

Free-form prompt text is display data only. Correctness is defined by typed
givens and an exact expected-result union, protected by a canonical digest.
"""
from __future__ import annotations

import copy
import hashlib
import json
from fractions import Fraction
from typing import Any

from graph_contract import validate_graph_shape


TASK_CONTRACT_VERSION = "derivation_task.v1"
CORPUS_SCHEMA_VERSION = "grade8_algebra_linear_practice.v3"
TASK_TYPES = {
    "linear_equation",
    "slope",
    "linear_classification",
    "linear_function",
    "function_comparison",
    "linear_system",
}


class TaskContractError(ValueError):
    """A typed task contract is malformed or mathematically inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TaskContractError(message)


def _exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    _require(actual == expected, f"{path} keys must be {sorted(expected)}; got {sorted(actual)}")


def _legacy_fraction(value: Any, path: str) -> Fraction:
    _require(not isinstance(value, bool), f"{path} must be a rational number")
    _require(isinstance(value, (str, int)), f"{path} must be an integer or rational string")
    try:
        return Fraction(value)
    except Exception as exc:
        raise TaskContractError(f"{path} is not a rational number: {value!r}") from exc


def _rational_object(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def rational_from_legacy(value: Any, path: str = "value") -> dict[str, int]:
    return _rational_object(_legacy_fraction(value, path))


def _fraction(value: Any, path: str) -> Fraction:
    _require(isinstance(value, dict), f"{path} must be a rational object")
    _exact_keys(value, {"numerator", "denominator"}, path)
    numerator = value["numerator"]
    denominator = value["denominator"]
    _require(isinstance(numerator, int) and not isinstance(numerator, bool), f"{path}.numerator must be an integer")
    _require(isinstance(denominator, int) and not isinstance(denominator, bool), f"{path}.denominator must be an integer")
    _require(denominator > 0, f"{path}.denominator must be positive")
    fraction = Fraction(numerator, denominator)
    _require(
        numerator == fraction.numerator and denominator == fraction.denominator,
        f"{path} must be reduced with a positive denominator",
    )
    return fraction


def canonical_rational(value: Any, path: str = "value") -> dict[str, int]:
    return _rational_object(_fraction(value, path))


def _point(value: Any, path: str) -> dict[str, dict[str, int]]:
    _require(isinstance(value, dict), f"{path} must be an object")
    _exact_keys(value, {"x", "y"}, path)
    return {
        "x": canonical_rational(value["x"], f"{path}.x"),
        "y": canonical_rational(value["y"], f"{path}.y"),
    }


def _points(value: Any, path: str, *, minimum: int = 2) -> list[dict[str, dict[str, int]]]:
    _require(isinstance(value, list) and len(value) >= minimum, f"{path} must contain at least {minimum} points")
    return [_point(point, f"{path}[{index}]") for index, point in enumerate(value)]


def _canonical_payload(contract: dict[str, Any]) -> bytes:
    payload = {
        "schema_version": contract.get("schema_version"),
        "id": contract.get("id"),
        "task_type": contract.get("task_type"),
        "givens": contract.get("givens"),
        "expected": contract.get("expected"),
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def contract_digest(contract: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_payload(contract)).hexdigest()


def attach_contract_digest(contract: dict[str, Any]) -> dict[str, Any]:
    frozen = copy.deepcopy(contract)
    frozen["contract_digest"] = contract_digest(frozen)
    return frozen


def _legacy_points(points: list[list[int] | tuple[int, int]]) -> list[dict[str, dict[str, int]]]:
    return [
        {"x": rational_from_legacy(point[0]), "y": rational_from_legacy(point[1])}
        for point in points
    ]


def build_task_contract(problem: dict[str, Any]) -> dict[str, Any]:
    """Convert one deterministic corpus problem into ``task_contract.v1``."""
    task_type = problem.get("kind")
    _require(task_type in TASK_TYPES, f"unsupported task type: {task_type!r}")
    structured = problem.get("structured")
    _require(isinstance(structured, dict), "problem.structured must be an object")

    if task_type == "linear_equation":
        givens = {
            "variable": "x",
            "lhs": {
                "coefficient": rational_from_legacy(structured["lhs"]["x"]),
                "constant": rational_from_legacy(structured["lhs"]["constant"]),
            },
            "rhs": {
                "coefficient": rational_from_legacy(structured["rhs"]["x"]),
                "constant": rational_from_legacy(structured["rhs"]["constant"]),
            },
        }
        answer_kind = structured["answer_kind"]
        cardinality = {
            "one_solution": "one",
            "no_solution": "none",
            "infinitely_many_solutions": "infinite",
        }.get(answer_kind)
        _require(cardinality is not None, f"unknown linear-equation answer kind: {answer_kind!r}")
        values = []
        if cardinality == "one":
            values = [rational_from_legacy(structured["solution_value"])]
        expected = {
            "kind": "solution_set",
            "variable": "x",
            "cardinality": cardinality,
            "values": values,
        }
    elif task_type == "slope":
        givens = {"points": _legacy_points(structured["points"])}
        expected = {"kind": "rational", "value": rational_from_legacy(structured["slope"])}
    elif task_type == "linear_classification":
        givens = {"table": _legacy_points(structured["table"])}
        expected = {
            "kind": "classification",
            "value": "linear" if structured["is_linear"] else "nonlinear",
        }
    elif task_type == "linear_function":
        givens = {"points": _legacy_points(structured["points"])}
        expected = {
            "kind": "linear_function",
            "slope": rational_from_legacy(structured["slope"]),
            "intercept": rational_from_legacy(structured["intercept"]),
        }
    elif task_type == "function_comparison":
        function_a = structured["function_a"]
        function_b = structured["function_b"]
        givens = {
            "function_a": {
                "slope": rational_from_legacy(function_a["slope"]),
                "intercept": rational_from_legacy(function_a["intercept"]),
            },
            "function_b": {"table": _legacy_points(function_b["table"])},
        }
        expected = {
            "kind": "comparison",
            "relation": "greater_rate",
            "winner": structured["greater_rate"],
        }
    else:
        equations = structured["equations"]
        solution = structured["solution"]
        givens = {
            "variables": ["x", "y"],
            "equations": [
                {
                    "x": rational_from_legacy(equation["x"]),
                    "y": rational_from_legacy(equation["y"]),
                    "constant": rational_from_legacy(equation["constant"]),
                }
                for equation in equations
            ],
        }
        expected = {
            "kind": "ordered_pair",
            "values": {
                "x": rational_from_legacy(solution["x"]),
                "y": rational_from_legacy(solution["y"]),
            },
        }

    contract = {
        "schema_version": TASK_CONTRACT_VERSION,
        "id": problem["id"],
        "task_type": task_type,
        "display": {
            "prompt": problem["prompt"],
            "answer": problem["answer"],
        },
        "metadata": {
            "strand": problem["strand"],
            "strand_label": problem["strand_label"],
            "standards": list(problem["standards"]),
            "difficulty": problem["difficulty"],
        },
        "givens": givens,
        "expected": expected,
        "pedagogy": {"reference_steps": copy.deepcopy(problem["steps"])},
    }
    return attach_contract_digest(contract)


def _normalize_result(task_type: str, result: Any, path: str = "result") -> dict[str, Any]:
    _require(isinstance(result, dict), f"{path} must be an object")
    kind = result.get("kind")

    if task_type == "linear_equation":
        _exact_keys(result, {"kind", "variable", "cardinality", "values"}, path)
        _require(kind == "solution_set", f"{path}.kind must be 'solution_set'")
        _require(result["variable"] == "x", f"{path}.variable must be 'x'")
        cardinality = result["cardinality"]
        _require(
            isinstance(cardinality, str) and cardinality in {"one", "none", "infinite"},
            f"{path}.cardinality is invalid",
        )
        _require(isinstance(result["values"], list), f"{path}.values must be a list")
        values = [canonical_rational(value, f"{path}.values[{index}]") for index, value in enumerate(result["values"])]
        _require((cardinality == "one" and len(values) == 1) or (cardinality != "one" and not values),
                 f"{path}.values does not match cardinality {cardinality!r}")
        return {"kind": kind, "variable": "x", "cardinality": cardinality, "values": values}

    if task_type == "slope":
        _exact_keys(result, {"kind", "value"}, path)
        _require(kind == "rational", f"{path}.kind must be 'rational'")
        return {"kind": kind, "value": canonical_rational(result["value"], f"{path}.value")}

    if task_type == "linear_classification":
        _exact_keys(result, {"kind", "value"}, path)
        _require(kind == "classification", f"{path}.kind must be 'classification'")
        _require(
            isinstance(result["value"], str) and result["value"] in {"linear", "nonlinear"},
            f"{path}.value is invalid",
        )
        return {"kind": kind, "value": result["value"]}

    if task_type == "linear_function":
        _exact_keys(result, {"kind", "slope", "intercept"}, path)
        _require(kind == "linear_function", f"{path}.kind must be 'linear_function'")
        return {
            "kind": kind,
            "slope": canonical_rational(result["slope"], f"{path}.slope"),
            "intercept": canonical_rational(result["intercept"], f"{path}.intercept"),
        }

    if task_type == "function_comparison":
        _exact_keys(result, {"kind", "relation", "winner"}, path)
        _require(kind == "comparison", f"{path}.kind must be 'comparison'")
        _require(result["relation"] == "greater_rate", f"{path}.relation must be 'greater_rate'")
        _require(
            isinstance(result["winner"], str) and result["winner"] in {"A", "B", "tie"},
            f"{path}.winner is invalid",
        )
        return {
            "kind": kind,
            "relation": "greater_rate",
            "winner": result["winner"],
        }

    if task_type == "linear_system":
        _exact_keys(result, {"kind", "values"}, path)
        _require(kind == "ordered_pair", f"{path}.kind must be 'ordered_pair'")
        values = result["values"]
        _require(isinstance(values, dict), f"{path}.values must be an object")
        _exact_keys(values, {"x", "y"}, f"{path}.values")
        return {
            "kind": kind,
            "values": {
                "x": canonical_rational(values["x"], f"{path}.values.x"),
                "y": canonical_rational(values["y"], f"{path}.values.y"),
            },
        }

    raise TaskContractError(f"unsupported task type: {task_type!r}")


def _normalized_points(givens: dict[str, Any], key: str, *, minimum: int = 2) -> list[dict[str, dict[str, int]]]:
    _exact_keys(givens, {key}, "givens")
    return _points(givens[key], f"givens.{key}", minimum=minimum)


def _line_from_points(points: list[dict[str, dict[str, int]]], path: str) -> tuple[Fraction, Fraction]:
    first, second = points[0], points[1]
    x1, y1 = _fraction(first["x"], f"{path}[0].x"), _fraction(first["y"], f"{path}[0].y")
    x2, y2 = _fraction(second["x"], f"{path}[1].x"), _fraction(second["y"], f"{path}[1].y")
    _require(x1 != x2, f"{path} must contain distinct x coordinates")
    slope = (y2 - y1) / (x2 - x1)
    intercept = y1 - slope * x1
    for index, point in enumerate(points[2:], start=2):
        x = _fraction(point["x"], f"{path}[{index}].x")
        y = _fraction(point["y"], f"{path}[{index}].y")
        _require(slope * x + intercept == y, f"{path} does not describe one line")
    return slope, intercept


def _computed_expected(contract: dict[str, Any]) -> dict[str, Any]:
    task_type = contract["task_type"]
    givens = contract["givens"]
    _require(isinstance(givens, dict), "givens must be an object")

    if task_type == "linear_equation":
        _exact_keys(givens, {"variable", "lhs", "rhs"}, "givens")
        _require(givens["variable"] == "x", "givens.variable must be 'x'")
        lhs, rhs = givens["lhs"], givens["rhs"]
        _require(isinstance(lhs, dict) and isinstance(rhs, dict), "givens equation sides must be objects")
        _exact_keys(lhs, {"coefficient", "constant"}, "givens.lhs")
        _exact_keys(rhs, {"coefficient", "constant"}, "givens.rhs")
        a = _fraction(lhs["coefficient"], "givens.lhs.coefficient")
        b = _fraction(lhs["constant"], "givens.lhs.constant")
        c = _fraction(rhs["coefficient"], "givens.rhs.coefficient")
        d = _fraction(rhs["constant"], "givens.rhs.constant")
        if a == c and b == d:
            cardinality, values = "infinite", []
        elif a == c:
            cardinality, values = "none", []
        else:
            cardinality, values = "one", [_rational_object((d - b) / (a - c))]
        return {"kind": "solution_set", "variable": "x", "cardinality": cardinality, "values": values}

    if task_type == "slope":
        points = _normalized_points(givens, "points")
        slope, _intercept = _line_from_points(points, "givens.points")
        return {"kind": "rational", "value": _rational_object(slope)}

    if task_type == "linear_classification":
        points = _normalized_points(givens, "table", minimum=3)
        slopes: list[Fraction] = []
        for index, (first, second) in enumerate(zip(points, points[1:])):
            x1 = _fraction(first["x"], f"givens.table[{index}].x")
            y1 = _fraction(first["y"], f"givens.table[{index}].y")
            x2 = _fraction(second["x"], f"givens.table[{index + 1}].x")
            y2 = _fraction(second["y"], f"givens.table[{index + 1}].y")
            _require(x1 != x2, "givens.table must not repeat x coordinates")
            slopes.append((y2 - y1) / (x2 - x1))
        return {"kind": "classification", "value": "linear" if len(set(slopes)) == 1 else "nonlinear"}

    if task_type == "linear_function":
        points = _normalized_points(givens, "points")
        slope, intercept = _line_from_points(points, "givens.points")
        return {
            "kind": "linear_function",
            "slope": _rational_object(slope),
            "intercept": _rational_object(intercept),
        }

    if task_type == "function_comparison":
        _exact_keys(givens, {"function_a", "function_b"}, "givens")
        function_a, function_b = givens["function_a"], givens["function_b"]
        _require(isinstance(function_a, dict) and isinstance(function_b, dict), "functions must be objects")
        _exact_keys(function_a, {"slope", "intercept"}, "givens.function_a")
        _exact_keys(function_b, {"table"}, "givens.function_b")
        slope_a = _fraction(function_a["slope"], "givens.function_a.slope")
        _fraction(function_a["intercept"], "givens.function_a.intercept")
        points = _points(function_b["table"], "givens.function_b.table", minimum=2)
        slope_b, _intercept_b = _line_from_points(points, "givens.function_b.table")
        winner = "A" if slope_a > slope_b else "B" if slope_b > slope_a else "tie"
        return {
            "kind": "comparison",
            "relation": "greater_rate",
            "winner": winner,
        }

    if task_type == "linear_system":
        _exact_keys(givens, {"variables", "equations"}, "givens")
        _require(givens["variables"] == ["x", "y"], "givens.variables must be ['x', 'y']")
        equations = givens["equations"]
        _require(isinstance(equations, list) and len(equations) == 2, "givens.equations must contain exactly two equations")
        normalized = []
        for index, equation in enumerate(equations):
            _require(isinstance(equation, dict), f"givens.equations[{index}] must be an object")
            _exact_keys(equation, {"x", "y", "constant"}, f"givens.equations[{index}]")
            normalized.append(tuple(_fraction(equation[key], f"givens.equations[{index}].{key}") for key in ("x", "y", "constant")))
        (a1, b1, c1), (a2, b2, c2) = normalized
        determinant = a1 * b2 - a2 * b1
        _require(determinant != 0, "givens.equations must have one unique solution")
        x = (c1 * b2 - c2 * b1) / determinant
        y = (a1 * c2 - a2 * c1) / determinant
        return {"kind": "ordered_pair", "values": {"x": _rational_object(x), "y": _rational_object(y)}}

    raise TaskContractError(f"unsupported task type: {task_type!r}")


def validate_task_contract(contract: Any) -> None:
    _require(isinstance(contract, dict), "contract must be an object")
    _exact_keys(
        contract,
        {"schema_version", "id", "task_type", "display", "metadata", "givens", "expected", "pedagogy", "contract_digest"},
        "contract",
    )
    _require(contract["schema_version"] == TASK_CONTRACT_VERSION, f"schema_version must be {TASK_CONTRACT_VERSION!r}")
    _require(isinstance(contract["id"], str) and contract["id"], "id must be a non-empty string")
    _require(
        isinstance(contract["task_type"], str) and contract["task_type"] in TASK_TYPES,
        f"unsupported task_type: {contract['task_type']!r}",
    )

    display = contract["display"]
    _require(isinstance(display, dict), "display must be an object")
    _exact_keys(display, {"prompt", "answer"}, "display")
    _require(all(isinstance(display[key], str) and display[key] for key in display), "display strings must be non-empty")

    metadata = contract["metadata"]
    _require(isinstance(metadata, dict), "metadata must be an object")
    _exact_keys(metadata, {"strand", "strand_label", "standards", "difficulty"}, "metadata")
    _require(isinstance(metadata["strand"], str) and metadata["strand"], "metadata.strand must be non-empty")
    _require(isinstance(metadata["strand_label"], str) and metadata["strand_label"], "metadata.strand_label must be non-empty")
    _require(isinstance(metadata["standards"], list) and metadata["standards"], "metadata.standards must be a non-empty list")
    _require(all(isinstance(item, str) and item for item in metadata["standards"]), "metadata.standards entries must be strings")
    _require(
        isinstance(metadata["difficulty"], int)
        and not isinstance(metadata["difficulty"], bool)
        and metadata["difficulty"] > 0,
        "metadata.difficulty must be a positive integer",
    )

    pedagogy = contract["pedagogy"]
    _require(isinstance(pedagogy, dict), "pedagogy must be an object")
    _exact_keys(pedagogy, {"reference_steps"}, "pedagogy")
    steps = pedagogy["reference_steps"]
    _require(isinstance(steps, list) and steps, "pedagogy.reference_steps must be non-empty")
    for index, step in enumerate(steps):
        _require(isinstance(step, dict), f"pedagogy.reference_steps[{index}] must be an object")
        _exact_keys(step, {"action", "equation"}, f"pedagogy.reference_steps[{index}]")
        _require(all(isinstance(step[key], str) and step[key] for key in step), f"pedagogy.reference_steps[{index}] strings must be non-empty")

    declared = _normalize_result(contract["task_type"], contract["expected"], "expected")
    computed = _computed_expected(contract)
    _require(declared == computed, f"expected result does not follow from typed givens; declared={declared}, computed={computed}")
    _require(contract["contract_digest"] == contract_digest(contract), "contract_digest does not match immutable contract payload")


def result_matches(contract: dict[str, Any], result: Any) -> bool:
    validate_task_contract(contract)
    try:
        candidate = _normalize_result(contract["task_type"], result)
    except TaskContractError:
        return False
    expected = _normalize_result(contract["task_type"], contract["expected"], "expected")
    return candidate == expected


def evaluate_submission(contract: Any, graph: Any, trusted_digest: Any) -> dict[str, Any]:
    """Fail-closed acceptance bound to an external digest and terminal goal."""
    if not isinstance(trusted_digest, str) or not trusted_digest:
        return {"status": "ERROR", "reasons": ["trusted contract digest is required"]}
    try:
        validate_task_contract(contract)
    except TaskContractError as exc:
        return {"status": "ERROR", "reasons": [str(exc)]}
    if contract["contract_digest"] != trusted_digest:
        return {
            "status": "ERROR",
            "task_id": contract["id"],
            "reasons": ["contract digest does not match frozen manifest"],
        }
    if not isinstance(graph, dict):
        return {"status": "ERROR", "task_id": contract["id"], "reasons": ["graph must be an object"]}

    violations = validate_graph_shape(graph)
    if violations:
        return {"status": "FAIL", "task_id": contract["id"], "reasons": violations}

    goal_id = graph["goal_node"]
    goal_nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict) and node.get("id") == goal_id]
    if len(goal_nodes) != 1:
        return {"status": "FAIL", "task_id": contract["id"], "reasons": ["goal_node must resolve to exactly one node"]}
    if "result" not in goal_nodes[0]:
        return {"status": "FAIL", "task_id": contract["id"], "reasons": ["terminal goal_node has no typed result"]}
    if not result_matches(contract, goal_nodes[0]["result"]):
        return {"status": "FAIL", "task_id": contract["id"], "reasons": ["terminal goal result does not match expected result"]}
    return {
        "status": "PASS",
        "task_id": contract["id"],
        "contract_digest": contract["contract_digest"],
        "goal_node": goal_id,
        "reasons": [],
    }
