# SPDX-License-Identifier: MIT
# CI Engine - Pipeline parsing

import yaml
from typing import Any


def parse_pipeline(pipeline: str) -> list[dict[str, Any]]:
    """Parse a pipeline definition from YAML string.

    Supports:
    - Simple steps with command
    - Steps with label and command
    - Environment variables (list or dict format)
    - Working directory
    - Timeout
    - Retry count

    Example:
        steps:
          - label: "Build"
            command: "make build"
            env:
              DEBUG: "true"
            working_directory: /app
            timeout: 600
            retry: 2
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
        return data

    if isinstance(data, dict):
        steps = data.get("steps", [])
        if isinstance(steps, list):
            return _normalize_steps(steps)

    return []


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
