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
    - Timeout / timeout-minutes (GitHub Actions compatible)
    - Retry count
    - Matrix expansion
    - Conditional steps with if: (supports failure(), success(), always())
    - continue-on-error: true/false
    - depends_on: step dependency graph
    - Wait steps (pause execution)
    - Block steps (manual approval)
    - Trigger steps (trigger another pipeline)
    - outputs: step output variables
    - services: sidecar containers (postgres, redis, etc.)

    Example (GitHub Actions-compatible subset):
        env:
          NODE_VERSION: "18"

        steps:
          - label: "Install"
            command: "npm ci"
            timeout-minutes: 10
            env:
              CI: "true"
          - label: "Test"
            command: "npm test"
            depends_on: Install
            continue-on-error: false
          - label: "Deploy"
            command: "npm run deploy"
            if: "{{ branch }} == 'main'"
            depends_on: Test
          - label: "Notify"
            command: "curl -X POST $SLACK_URL"
            if: failure()
            continue-on-error: true
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
        env = {}
        if data and isinstance(data[0], dict):
            env = data[0].get("env", {})
        return _normalize_and_evaluate(steps, env)

    if isinstance(data, dict):
        steps = data.get("steps", [])
        global_env = data.get("env", {})
        if isinstance(global_env, list):
            global_env = _list_env_to_dict(global_env)
        if isinstance(steps, list):
            # Inject global env into each step
            for step in steps:
                if isinstance(step, dict):
                    step_env = step.get("env", {})
                    if isinstance(step_env, list):
                        step_env = _list_env_to_dict(step_env)
                    merged = {**global_env, **step_env}
                    if merged:
                        step["env"] = merged
            steps = _expand_matrix_steps(steps)
            return _normalize_and_evaluate(steps, global_env)

    return []


def _list_env_to_dict(env_list: list) -> dict[str, str]:
    """Convert env list format [KEY=VAL, ...] to dict."""
    result = {}
    for item in env_list:
        if isinstance(item, str) and "=" in item:
            k, _, v = item.partition("=")
            result[k.strip()] = v.strip()
        elif isinstance(item, dict):
            result.update(item)
    return result


def _normalize_and_evaluate(
    steps: list[dict[str, Any]], env: dict[str, str]
) -> list[dict[str, Any]]:
    """Normalize steps and evaluate conditionals."""
    return _evaluate_conditionals(steps, env)


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
    """Expand matrix variables AND parallelism into multiple jobs."""
    import uuid
    expanded = []

    for step in steps:
        if isinstance(step, str):
            # bare string like "make build"
            expanded.append(_normalize_step({"command": step}, StepType.COMMAND))
            continue

        step_type = _detect_step_type(step)

        if step_type in (StepType.WAIT, StepType.BLOCK, StepType.TRIGGER):
            normalized = _normalize_step(step, step_type)
            expanded.append(normalized)
            continue

        # Parallelism: N identical jobs sharing a group id
        parallelism = step.get("parallelism")
        if parallelism and isinstance(parallelism, int) and parallelism > 1:
            group_id = str(uuid.uuid4())[:8]
            base_label = step.get("label") or step.get("name") or "Job"
            for idx in range(1, parallelism + 1):
                new_step = dict(step)
                new_step["label"] = f"{base_label} [{idx}/{parallelism}]"
                new_step["parallel_group_id"] = group_id
                new_step["parallel_index"] = idx
                new_step["parallel_total"] = parallelism
                # Inject standard env vars for the command to use
                env = dict(new_step.get("env") or {})
                env["CI_ENGINE_PARALLEL_JOB"] = str(idx - 1)   # 0-indexed (matches Buildkite)
                env["CI_ENGINE_PARALLEL_JOB_COUNT"] = str(parallelism)
                new_step["env"] = env
                del new_step["parallelism"]
                expanded.append(_normalize_step(new_step, step_type))
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
            new_step["label"] = _expand_template(new_step.get("label", ""), matrix_vars, {})
            new_step["command"] = _expand_template(new_step.get("command", ""), matrix_vars, {})
            del new_step["matrix"]
            expanded.append(_normalize_step(new_step, step_type))

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

    # Normalize depends_on
    depends_on = step.get("depends_on") or step.get("needs")
    if depends_on:
        if isinstance(depends_on, str):
            # Split comma-separated: "Test, Lint" → ["Test", "Lint"]
            parts = [d.strip() for d in depends_on.split(",") if d.strip()]
            normalized["depends_on"] = parts
        elif isinstance(depends_on, list):
            normalized["depends_on"] = [str(d).strip() for d in depends_on]
        else:
            normalized["depends_on"] = []
    else:
        normalized["depends_on"] = []

    # Normalize timeout — support both timeout (seconds) and timeout-minutes (GHA style)
    if "timeout-minutes" in step:
        normalized["timeout"] = int(step["timeout-minutes"]) * 60
    elif "timeout_minutes" in step:
        normalized["timeout"] = int(step["timeout_minutes"]) * 60

    # Normalize retry
    retry = step.get("retry") or step.get("retries", 0)
    normalized["retry"] = int(retry) if retry else 0

    # Normalize continue-on-error (GHA style and underscore style)
    coe = step.get("continue-on-error") or step.get("continue_on_error", False)
    normalized["continue_on_error"] = bool(coe)

    # Soft fail — step failure does not fail the build
    # Accepts: soft_fail: true  OR  soft_fail: [{exit_status: 1}]
    soft_fail_raw = step.get("soft_fail", step.get("soft-fail", False))
    if isinstance(soft_fail_raw, list):
        # [{exit_status: N}] form — treat any match as soft-fail for now
        normalized["soft_fail"] = len(soft_fail_raw) > 0
    else:
        normalized["soft_fail"] = bool(soft_fail_raw)

    # Concurrency groups (serialize jobs across builds)
    concurrency_raw = step.get("concurrency")
    if concurrency_raw is not None:
        try:
            normalized["concurrency"] = int(concurrency_raw)
        except (TypeError, ValueError):
            pass
    concurrency_group = step.get("concurrency_group") or step.get("concurrency-group")
    if concurrency_group:
        normalized["concurrency_group"] = str(concurrency_group)

    # Queue routing
    agents_block = step.get("agents") or {}
    if isinstance(agents_block, dict):
        queue = agents_block.get("queue") or step.get("queue")
    else:
        queue = step.get("queue")
    if queue:
        normalized["queue"] = str(queue)
    else:
        normalized.setdefault("queue", "default")

    # Preserve parallel group fields if already set (from parallelism expansion)
    for pgf in ("parallel_group_id", "parallel_index", "parallel_total"):
        if pgf in step:
            normalized[pgf] = step[pgf]

    # Normalize env
    env = step.get("env", {})
    if isinstance(env, list):
        env = _list_env_to_dict(env)
    normalized["env"] = env or {}

    # Normalize outputs definition (keys the step can set)
    outputs = step.get("outputs", [])
    if isinstance(outputs, str):
        outputs = [outputs]
    normalized["outputs"] = outputs or []

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
        normalized["node_type"] = StepType.WAIT
        normalized["label"] = step.get("wait") or step.get("label") or "Wait"
        normalized["wait_seconds"] = step.get("wait_seconds", step.get("seconds", 0))
        if not step.get("wait") and not step.get("label"):
            normalized["label"] = f"Wait {normalized['wait_seconds']}s"

    elif step_type == StepType.BLOCK:
        normalized["step_type"] = StepType.BLOCK
        normalized["node_type"] = StepType.BLOCK
        block_field = step.get("block")
        if isinstance(block_field, str):
            normalized["label"] = block_field
        else:
            normalized["label"] = step.get("label", "Manual approval")
        normalized["blocking"] = True

    elif step_type == StepType.TRIGGER:
        normalized["step_type"] = StepType.TRIGGER
        normalized["node_type"] = StepType.TRIGGER
        normalized["label"] = step.get("label", "Trigger pipeline")
        normalized["trigger_pipeline"] = step.get("trigger")

    else:
        normalized["step_type"] = step_type
        # Keep an explicitly set node_type (e.g. node_type: wait on a command-looking step)
        explicit_node_type = step.get("node_type") or step.get("type")
        if explicit_node_type and explicit_node_type != StepType.COMMAND:
            normalized["node_type"] = explicit_node_type
        else:
            normalized["node_type"] = step_type  # "command"

    return normalized


def _evaluate_conditionals(
    steps: list[dict[str, Any]], env: dict[str, str]
) -> list[dict[str, Any]]:
    """Evaluate 'if' conditions and mark steps to skip.

    Supports:
    - failure() — step runs only if a previous step failed
    - success() — step runs only if all previous steps succeeded (default)
    - always() — step always runs regardless of previous results
    - {{ env.VAR }} == 'value' — expression comparisons
    - {{ branch }} == 'main' — branch comparisons
    """
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
            skipped["skip_condition"] = str(condition)
            result.append(skipped)

    return result


def expand_runtime_expressions(
    text: str,
    env_vars: dict[str, str],
    step_outputs: dict[str, dict[str, str]] | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Expand ${{ env.VAR }}, ${{ steps.id.outputs.key }}, ${{ github.* }} expressions.

    This is called at runtime (not parse time) so it has access to actual
    values including step outputs from prior steps.
    """
    if not text:
        return text

    ctx = context or {}
    outputs = step_outputs or {}

    def replace_expr(match: re.Match) -> str:
        inner = match.group(1).strip()

        # env.VAR
        if inner.startswith("env."):
            key = inner[4:]
            return env_vars.get(key, os.environ.get(key, ""))

        # steps.STEP_ID.outputs.KEY
        m = re.match(r"steps\.(\w+)\.outputs\.(\w+)", inner)
        if m:
            step_id, output_key = m.group(1), m.group(2)
            return outputs.get(step_id, {}).get(output_key, "")

        # github.* context
        if inner.startswith("github."):
            key = inner[7:]
            return str(ctx.get("github", {}).get(key, ""))

        # secrets.VAR — resolved before passing to agent so secrets don't appear in logs
        if inner.startswith("secrets."):
            key = inner[8:]
            return env_vars.get(key, "")

        # runner.os, runner.arch
        if inner.startswith("runner."):
            key = inner[7:]
            runner_ctx = {"os": "Linux", "arch": "X64", "temp": "/tmp"}
            return runner_ctx.get(key, "")

        return match.group(0)  # unknown — leave as-is

    import os
    return re.sub(r"\$\{\{\s*([^}]+)\s*\}\}", replace_expr, text)


def _expand_step_variables(step: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    """Expand ${{ inputs.key }} in step fields."""
    result = dict(step)
    pattern = f"${{{{ inputs.{key}}}}}"

    for field in ["label", "command", "working_directory"]:
        if field in result and isinstance(result[field], str):
            result[field] = result[field].replace(pattern, str(value))

    return result


def _evaluate_expression(condition: Any, vars_dict: dict) -> bool:
    """Evaluate a condition expression.

    Supported forms:
    - failure()    → True if any previous step failed (context-dependent at runtime)
    - success()    → True if all previous steps succeeded
    - always()     → True unconditionally
    - {{ env.VAR }} == 'value'
    - {{ branch }} == 'main'
    """
    if not isinstance(condition, str):
        return bool(condition)

    condition = condition.strip()

    # Built-in status check functions — at parse time we cannot know whether
    # previous steps failed, so we keep the step and let the scheduler decide.
    # We mark it with a special skip_condition prefix so the scheduler handles it.
    if re.match(r"^failure\(\s*\)$", condition, re.IGNORECASE):
        return True  # keep the step; scheduler enforces failure() semantics
    if re.match(r"^success\(\s*\)$", condition, re.IGNORECASE):
        return True  # keep the step; scheduler enforces success() semantics
    if re.match(r"^always\(\s*\)$", condition, re.IGNORECASE):
        return True

    # Expand {{ var }} references
    expanded = condition
    for var_ref in re.findall(r"\{\{[^}]+\}\}", condition):
        inner = var_ref[2:-2].strip()
        value = _get_variable_value(inner, vars_dict)
        expanded = expanded.replace(var_ref, repr(value))

    # Also expand ${{ var }} references
    for var_ref in re.findall(r"\$\{\{[^}]+\}\}", condition):
        inner = var_ref[3:-2].strip()
        value = _get_variable_value(inner, vars_dict)
        expanded = expanded.replace(var_ref, repr(value))

    try:
        result = eval(expanded, {"__builtins__": {}}, {})  # noqa: S307
        return bool(result)
    except Exception:
        return True  # unknown condition → keep the step


def _get_variable_value(var_path: str, vars_dict: dict) -> Any:
    """Get variable value from path like 'matrix.os' or 'env.BRANCH'."""
    parts = var_path.split(".")
    if not parts:
        return None

    if parts[0] == "matrix" and len(parts) > 1:
        return vars_dict.get("matrix_vars", {}).get(parts[1])
    elif parts[0] == "env" and len(parts) > 1:
        return vars_dict.get("env", {}).get(parts[1])
    elif parts[0] == "github" and len(parts) > 1:
        return vars_dict.get("github", {}).get(parts[1], "")
    elif parts[0] == "branch":
        return vars_dict.get("branch", "main")

    return vars_dict.get(var_path, "")


def _expand_template(template: str, matrix_vars: dict, env_vars: dict) -> str:
    """Expand {{.variable}} patterns in template string."""
    if not template:
        return template

    result = template
    for key, value in matrix_vars.items():
        result = result.replace(f"{{{{.matrix.{key}}}}}", str(value))
        result = result.replace(f"{{{{ matrix.{key} }}}}", str(value))

    for key, value in env_vars.items():
        result = result.replace(f"{{{{.env.{key}}}}}", str(value))
        result = result.replace(f"{{{{ env.{key} }}}}", str(value))

    return result


# Keep old name as alias
_expand_variables = _expand_template


def parse_pipeline_file(path: str) -> list[dict[str, Any]]:
    """Parse a pipeline from a file."""
    try:
        with open(path, "r") as f:
            return parse_pipeline(f.read())
    except (FileNotFoundError, IOError):
        return []
