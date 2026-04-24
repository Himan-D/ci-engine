# SPDX-License-Identifier: MIT
# CI Engine - Pipeline parsing

import yaml
import re
from typing import Any
from itertools import product


class StepType:
    """Pipeline step types."""

    COMMAND = "command"
    WAIT = "wait"
    BLOCK = "block"
    TRIGGER = "trigger"
    WORKFLOW = "workflow"


class ReusableWorkflow:
    """Reusable workflow definition."""

    def __init__(
        self,
        name: str,
        steps: list[dict[str, Any]],
        env: dict[str, str] | None = None,
        inputs: dict[str, Any] | None = None,
    ):
        self.name = name
        self.steps = steps
        self.env = env or {}
        self.inputs = inputs or {}

    def instantiate(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Create steps with provided parameters."""
        result = []
        for step in self.steps:
            new_step = dict(step)
            for key, value in params.items():
                new_step = _expand_step_variables(new_step, key, value)
            result.append(new_step)
        return result


_workflow_registry: dict[str, ReusableWorkflow] = {}


def register_workflow(workflow: ReusableWorkflow):
    """Register a reusable workflow."""
    _workflow_registry[workflow.name] = workflow


def get_workflow(name: str) -> ReusableWorkflow | None:
    """Get a registered workflow by name."""
    return _workflow_registry.get(name)


def parse_workflow(pipeline: str) -> ReusableWorkflow | None:
    """Parse a reusable workflow definition."""
    try:
        data = yaml.safe_load(pipeline)
    except yaml.YAMLError:
        return None

    if not data:
        return None

    name = data.get("name", "unnamed")
    steps = data.get("steps", [])
    env = data.get("env", {})
    inputs = data.get("inputs", {})

    return ReusableWorkflow(name=name, steps=steps, env=env, inputs=inputs)


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
    - Wait steps (pause execution)
    - Block steps (manual approval)
    - Trigger steps (trigger another pipeline)

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
          - wait
          - block: "Deploy to production?"
          - command: "deploy.sh"
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


def _detect_step_type(step: dict[str, Any]) -> str:
    """Detect the type of step based on its structure."""
    if "command" in step and step["command"]:
        return StepType.COMMAND
    if step.get("wait") is not None:
        return StepType.WAIT
    if "block" in step or step.get("type") == "block":
        return StepType.BLOCK
    if "trigger" in step or step.get("type") == "trigger":
        return StepType.TRIGGER
    return StepType.COMMAND


def _expand_matrix_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand matrix variables into multiple jobs."""
    expanded = []

    for step in steps:
        step_type = _detect_step_type(step)

        if step_type in (StepType.WAIT, StepType.BLOCK, StepType.TRIGGER):
            normalized = _normalize_step(step, step_type)
            expanded.append(normalized)
            continue

        matrix = step.get("matrix")
        if not matrix:
            normalized = _normalize_step(step, step_type)
            expanded.append(normalized)
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


def _normalize_services(services: Any) -> list[dict[str, Any]]:
    """Normalize service definitions."""
    if not services:
        return []

    if isinstance(services, list):
        normalized = []
        for svc in services:
            if isinstance(svc, str):
                normalized.append({"name": svc, "image": svc})
            elif isinstance(svc, dict):
                normalized.append(
                    {
                        "name": svc.get("name", ""),
                        "image": svc.get("image", ""),
                        "env": svc.get("env", {}),
                        "ports": svc.get("ports", []),
                    }
                )
        return normalized

    return []


def _normalize_step(step: dict[str, Any], step_type: str) -> dict[str, Any]:
    """Normalize a step to have consistent structure."""
    normalized = dict(step)

    depends_on = step.get("depends_on")
    if depends_on:
        if isinstance(depends_on, str):
            normalized["depends_on"] = [depends_on]
        elif isinstance(depends_on, list):
            normalized["depends_on"] = depends_on
        else:
            normalized["depends_on"] = []

    # Handle cache configuration
    cache = step.get("cache")
    if cache:
        if isinstance(cache, dict):
            normalized["cache"] = {
                "key": cache.get("key", ""),
                "path": cache.get("path", ""),
                "enabled": True,
            }
        elif isinstance(cache, str):
            normalized["cache"] = {
                "key": cache,
                "path": "",
                "enabled": True,
            }
        else:
            normalized["cache"] = {"enabled": False}

    # Handle services configuration
    services = step.get("services")
    if services:
        normalized["services"] = _normalize_services(services)

    if step_type == StepType.WAIT:
        normalized["step_type"] = StepType.WAIT
        normalized["label"] = step.get("wait") or "Wait"
        normalized["wait_seconds"] = step.get("wait_seconds", step.get("seconds", 0))
        if not step.get("wait"):
            normalized["label"] = f"Wait {normalized['wait_seconds']}s"

    elif step_type == StepType.BLOCK:
        normalized["step_type"] = StepType.BLOCK
        block_field = step.get("block")
        if isinstance(block_field, str):
            normalized["label"] = block_field
        else:
            normalized["label"] = step.get("label", "Manual approval")
        normalized["blocking"] = True

    elif step_type == StepType.TRIGGER:
        normalized["step_type"] = StepType.TRIGGER
        normalized["label"] = step.get("label", "Trigger pipeline")
        normalized["trigger_pipeline"] = step.get("trigger")

    else:
        normalized["step_type"] = step_type

    return normalized


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


def _expand_step_variables(step: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    """Expand ${{ inputs.key }} in step fields."""
    result = dict(step)
    pattern = f"${{{{ inputs.{key}}}}}"

    for field in ["label", "command", "working_directory"]:
        if field in result and isinstance(result[field], str):
            result[field] = result[field].replace(pattern, str(value))

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
