# SPDX-License-Identifier: MIT
# CI Engine - Pipeline parsing

import yaml
import re
from typing import Any
from itertools import product


def parse_pipeline(pipeline: str) -> list[dict[str, Any]]:
    """Parse a pipeline definition from YAML string.

    Supports:
    - Simple steps with command
    - Steps with label and command
    - Environment variables (list or dict format)
    - Working directory
    - Timeout
    - Retry count
    - Matrix expansion
    - Conditional steps (if:)

    Example:
        steps:
          - label: "Build"
            command: "make build"
            env:
              DEBUG: "true"
            working_directory: /app
            timeout: 600
            retry: 2
          - label: "Test {{.matrix.os}}"
            command: "pytest"
            matrix:
              os: [linux, windows]
              node: [14, 16]
            if: "{{.branch}} == 'main'"
    """
    if not pipeline.strip():
        return []

    try:
        data = yaml.safe_load(pipeline)
    except yaml.YAMLError:
        return []

    if not data:
        return []

    if isinstance(data, list):
        steps = _expand_matrix_steps(data)
        return _evaluate_conditionals(steps, data.get("env", {}))

    if isinstance(data, dict):
        steps = data.get("steps", [])
        if isinstance(steps, list):
            steps = _expand_matrix_steps(steps)
            return _evaluate_conditionals(steps, data.get("env", {}))

    return []


def _expand_matrix_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand matrix variables into multiple jobs."""
    expanded = []

    for step in steps:
        matrix = step.get("matrix")
        if not matrix:
            expanded.append(step)
            continue

        keys = list(matrix.keys())
        values = [matrix[k] if isinstance(matrix[k], list) else [matrix[k]] for k in keys]

        for combo in product(*values):
            matrix_vars = dict(zip(keys, combo))
            new_step = dict(step)
            new_step["matrix_vars"] = matrix_vars
            new_step["label"] = _expand_variables(new_step.get("label", ""), matrix_vars, {})
            new_step["command"] = _expand_variables(new_step.get("command", ""), matrix_vars, {})
            del new_step["matrix"]
            expanded.append(new_step)

    return expanded


def _evaluate_conditionals(
    steps: list[dict[str, Any]], env: dict[str, str]
) -> list[dict[str, Any]]:
    """Evaluate 'if' conditions and mark steps to skip."""
    result = []

    for step in steps:
        condition = step.get("if")
        if not condition:
            result.append(step)
            continue

        vars_dict = {"env": env}
        if "matrix_vars" in step:
            vars_dict.update(step["matrix_vars"])

        if _evaluate_expression(condition, vars_dict):
            result.append(step)
        else:
            skipped = dict(step)
            skipped["skip_condition"] = condition
            result.append(skipped)

    return result


def _evaluate_expression(condition: str, vars_dict: dict) -> bool:
    """Evaluate a simple expression with variables."""
    try:
        condition = condition.strip()

        for var_ref in re.findall(r"\{\{[^}]+\}\}", condition):
            inner = var_ref[2:-2].strip()
            value = _get_variable_value(inner, vars_dict)
            condition = condition.replace(var_ref, repr(value))

        result = eval(condition, {"__builtins__": {}}, {})
        return bool(result)
    except Exception:
        return True


def _get_variable_value(var_path: str, vars_dict: dict) -> Any:
    """Get variable value from path like 'matrix.os' or 'env.BRANCH'."""
    parts = var_path.split(".")
    if not parts:
        return None

    if parts[0] == "matrix" and len(parts) > 1:
        return vars_dict.get("matrix_vars", {}).get(parts[1])
    elif parts[0] == "env" and len(parts) > 1:
        return vars_dict.get("env", {}).get(parts[1])
    elif parts[0] == "branch":
        return vars_dict.get("branch", "main")

    return vars_dict.get(var_path, "")


def _expand_variables(template: str, matrix_vars: dict, env_vars: dict) -> str:
    """Expand {{.variable}} patterns in template string."""
    if not template:
        return template

    result = template
    for key, value in matrix_vars.items():
        result = result.replace(f"{{{{.matrix.{key}}}}}", str(value))

    for key, value in env_vars.items():
        result = result.replace(f"{{{{.env.{key}}}}}", str(value))

    return result


def _normalize_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize step format for consistent access."""
    normalized = []
    for step in steps:
        normalized_step = dict(step)
        normalized.append(normalized_step)
    return normalized


def parse_pipeline_file(path: str) -> list[dict[str, Any]]:
    """Parse a pipeline from a file."""
    try:
        with open(path, "r") as f:
            return parse_pipeline(f.read())
    except (FileNotFoundError, IOError):
        return []
