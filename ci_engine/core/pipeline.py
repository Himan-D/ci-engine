# SPDX-License-Identifier: MIT
# CI Engine - Pipeline parsing

import yaml
from typing import Any


def parse_pipeline(pipeline: str) -> list[dict[str, Any]]:
    """Parse a pipeline definition from YAML string.

    Supports:
    - Simple steps with command
    - Steps with label and command
    - Plugins and env vars

    Example:
        steps:
          - label: "Build"
            command: "make build"
          - label: "Test"
            command: "make test"
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
            return steps

    return []


def parse_pipeline_file(path: str) -> list[dict[str, Any]]:
    """Parse a pipeline from a file."""
    try:
        with open(path, "r") as f:
            return parse_pipeline(f.read())
    except (FileNotFoundError, IOError):
        return []
