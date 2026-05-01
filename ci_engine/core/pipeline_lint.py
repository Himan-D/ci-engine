# SPDX-License-Identifier: MIT
# CI Engine — Pipeline YAML linter
#
# Validates a pipeline definition before submission:
#   • YAML parse errors
#   • Unknown depends_on references
#   • Cyclic dependencies (Kahn's algorithm)
#   • Empty / missing commands on non-wait steps
#   • Duplicate step labels
#
# Injection prevention:
#   PIPELINE_TRUST_MODE env var controls what happens when a webhook fires
#   for a PR from an untrusted fork:
#
#   full                — current behaviour (no restriction)
#   protected_branches_only — only branches matching PROTECTED_BRANCH_PATTERNS
#   base_ref_only       — always use the base-branch pipeline YAML for PRs

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class LintError:
    step: Optional[str]
    code: str
    message: str


@dataclass
class LintResult:
    valid: bool
    errors: list[LintError] = field(default_factory=list)
    warnings: list[LintError] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": [{"step": e.step, "code": e.code, "message": e.message} for e in self.errors],
            "warnings": [{"step": w.step, "code": w.code, "message": w.message} for w in self.warnings],
        }


# ---------------------------------------------------------------------------
# Core linter
# ---------------------------------------------------------------------------

class PipelineLinter:
    """Stateless pipeline linter — create once, call `lint()` many times."""

    # Maximum steps to lint (matrix-pre-expansion limit)
    MAX_STEPS = 500

    def lint(self, pipeline_yaml: str) -> LintResult:
        result = LintResult(valid=True)

        # 1. Parse YAML
        try:
            data = yaml.safe_load(pipeline_yaml)
        except yaml.YAMLError as exc:
            result.valid = False
            result.errors.append(LintError(None, "YAML_PARSE_ERROR", str(exc)))
            return result

        if not data:
            result.errors.append(LintError(None, "EMPTY_PIPELINE", "Pipeline is empty"))
            result.valid = False
            return result

        steps = data.get("steps") or []
        if not isinstance(steps, list):
            result.errors.append(LintError(None, "INVALID_STEPS", "steps must be a list"))
            result.valid = False
            return result

        if len(steps) > self.MAX_STEPS:
            result.warnings.append(LintError(
                None, "TOO_MANY_STEPS",
                f"Pipeline has {len(steps)} steps; linting first {self.MAX_STEPS}",
            ))
            steps = steps[:self.MAX_STEPS]

        # 2. Gather labels
        labels: set[str] = set()
        duplicate_labels: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                continue
            label = step.get("label") or step.get("name") or ""
            if label:
                if label in labels:
                    duplicate_labels.add(label)
                labels.add(label)

        for dup in sorted(duplicate_labels):
            result.warnings.append(LintError(dup, "DUPLICATE_LABEL", f"Step label '{dup}' appears more than once"))

        # 3. Validate each step
        step_node_types = {}
        adj: dict[str, list[str]] = {lbl: [] for lbl in labels}

        for step in steps:
            if not isinstance(step, dict):
                continue
            label = step.get("label") or step.get("name") or "<unnamed>"
            node_type = step.get("node_type") or step.get("step_type") or "command"
            if node_type in ("block", "manual", "approval", "gate"):
                node_type = "wait"
            step_node_types[label] = node_type

            # Command check
            if node_type not in ("wait", "block") and not step.get("command"):
                result.warnings.append(LintError(
                    label, "MISSING_COMMAND",
                    f"Step '{label}' has no command (will use 'echo done' fallback)",
                ))

            # depends_on references
            deps_raw = step.get("depends_on") or []
            if isinstance(deps_raw, str):
                deps_raw = [d.strip() for d in deps_raw.split(",") if d.strip()]
            for dep in deps_raw:
                if dep not in labels:
                    result.errors.append(LintError(
                        label, "UNKNOWN_DEP",
                        f"Step '{label}' depends_on '{dep}' which does not exist",
                    ))
                    result.valid = False
                else:
                    adj[label].append(dep)

        # 4. Cycle detection (Kahn's algorithm on the dependency graph)
        cycle_labels = self._find_cycles(labels, adj)
        for lbl in cycle_labels:
            result.errors.append(LintError(
                lbl, "CYCLE",
                f"Dependency cycle detected involving step '{lbl}'",
            ))
            result.valid = False

        return result

    @staticmethod
    def _find_cycles(labels: set[str], adj: dict[str, list[str]]) -> list[str]:
        """Return labels that are part of a dependency cycle using Kahn's algorithm."""
        # in-degree: number of steps that THIS step must wait for
        in_degree = {lbl: 0 for lbl in labels}
        for lbl, deps in adj.items():
            for dep in deps:
                in_degree[lbl] = in_degree.get(lbl, 0) + 1

        queue = [lbl for lbl, deg in in_degree.items() if deg == 0]
        visited = 0

        while queue:
            node = queue.pop(0)
            visited += 1
            # Reduce in-degree of nodes that depend on this one
            for lbl, deps in adj.items():
                if node in deps:
                    in_degree[lbl] -= 1
                    if in_degree[lbl] == 0:
                        queue.append(lbl)

        # Any label not visited is part of a cycle
        if visited == len(labels):
            return []
        return [lbl for lbl, deg in in_degree.items() if deg > 0]


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

_linter = PipelineLinter()


def lint_pipeline(pipeline_yaml: str) -> LintResult:
    """Lint a pipeline YAML string. Returns a LintResult."""
    return _linter.lint(pipeline_yaml)


# ---------------------------------------------------------------------------
# Trust mode helpers
# ---------------------------------------------------------------------------

TRUST_MODE_FULL = "full"
TRUST_MODE_PROTECTED = "protected_branches_only"
TRUST_MODE_BASE_REF = "base_ref_only"


def get_trust_mode() -> str:
    return os.environ.get("PIPELINE_TRUST_MODE", TRUST_MODE_FULL).lower()


def get_protected_branch_patterns() -> list[str]:
    """Comma-separated glob patterns for trusted branches."""
    raw = os.environ.get("PROTECTED_BRANCH_PATTERNS", "main,master,release/*,hotfix/*")
    return [p.strip() for p in raw.split(",") if p.strip()]


def is_trusted_ref(ref: str) -> bool:
    """Return True if *ref* (branch name) is considered trusted."""
    import fnmatch
    patterns = get_protected_branch_patterns()
    return any(fnmatch.fnmatch(ref, p) for p in patterns)


def should_use_base_pipeline(event_type: str, is_fork: bool, head_ref: str) -> bool:
    """Decide whether to use the base-branch pipeline instead of the PR branch pipeline.

    Args:
        event_type: 'push' or 'pull_request'
        is_fork: True when the PR comes from a fork
        head_ref: The branch/ref being built

    Returns:
        True → fetch pipeline from base branch (safe)
        False → use the submitted pipeline as-is
    """
    mode = get_trust_mode()
    if mode == TRUST_MODE_FULL:
        return False
    if mode == TRUST_MODE_BASE_REF and event_type == "pull_request" and is_fork:
        return True
    if mode == TRUST_MODE_PROTECTED and not is_trusted_ref(head_ref):
        return True
    return False
