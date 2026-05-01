# SPDX-License-Identifier: MIT
# CI Engine - Built-in Agent Plugins

"""
Built-in plugins for common agent functionality.

These plugins provide common features like logging, metrics, caching, etc.
They can be used as-is or as templates for custom plugins.

Example usage:
    ```python
    from ci_engine.agent.builtins import LoggingPlugin, MetricsPlugin

    agent = CIEngineAgent(
        name="my-agent",
        plugins=[LoggingPlugin(), MetricsPlugin()],
    )
    ```
"""

import time
from typing import Optional
from dataclasses import dataclass

from ci_engine.agent.plugins import AgentPlugin, JobContext, JobResult


class LoggingPlugin(AgentPlugin):
    """Plugin that logs job execution to stdout.

    Provides timestamped logging for all job executions including:
    - Job start
    - Job completion
    - Job errors
    """

    name = "builtin-logging"
    version = "1.0.0"

    def pre_execute(self, context: JobContext) -> JobContext:
        """Log job start."""
        print(f"[{time.strftime('%H:%M:%S')}] [START] Job #{context.job_id}: {context.label}")
        return context

    def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
        """Log job completion."""
        status = "PASSED" if result.exit_code == 0 else "FAILED"
        print(
            f"[{time.strftime('%H:%M:%S')}] [{status}] Job #{context.job_id}: {context.label} (exit={result.exit_code}, duration={result.duration_ms}ms)"
        )
        return result

    def on_error(self, context: JobContext, error: Exception) -> None:
        """Log job error."""
        print(
            f"[{time.strftime('%H:%M:%S')}] [ERROR] Job #{context.job_id}: {context.label} - {error}"
        )


class MetricsPlugin(AgentPlugin):
    """Plugin that tracks job execution metrics.

    Collects and reports metrics including:
    - Total jobs executed
    - Jobs passed/failed
    - Average execution time
    - Jobs by label
    """

    name = "builtin-metrics"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.total_jobs = 0
        self.passed_jobs = 0
        self.failed_jobs = 0
        self.total_duration = 0
        self.jobs_by_label: dict[str, int] = {}
        self._start_time: Optional[float] = None

    def pre_execute(self, context: JobContext) -> JobContext:
        """Start timing the job."""
        self.total_jobs += 1
        self._start_time = time.time()
        return context

    def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
        """Record job metrics."""
        if result.exit_code == 0:
            self.passed_jobs += 1
        else:
            self.failed_jobs += 1

        self.total_duration += result.duration_ms

        label = context.label or f"job-{context.job_id}"
        self.jobs_by_label[label] = self.jobs_by_label.get(label, 0) + 1

        return result

    def get_stats(self) -> dict:
        """Get current metrics."""
        return {
            "total_jobs": self.total_jobs,
            "passed_jobs": self.passed_jobs,
            "failed_jobs": self.failed_jobs,
            "pass_rate": self.passed_jobs / self.total_jobs if self.total_jobs > 0 else 0,
            "avg_duration_ms": self.total_duration / self.total_jobs if self.total_jobs > 0 else 0,
            "jobs_by_label": self.jobs_by_label,
        }


@dataclass
class CacheEntry:
    """Cache entry for build artifacts."""

    key: str
    path: str
    created_at: float
    hits: int = 0


class CachePlugin(AgentPlugin):
    """Plugin that caches build dependencies and artifacts.

    This plugin can:
    - Cache npm/node_modules between builds
    - Cache pip packages
    - Cache build artifacts
    - Store/retrieve from local filesystem cache

    Usage:
        ```python
        cache_plugin = CachePlugin(cache_dir="/tmp/ci-engine-cache")
        cache_plugin.add_pattern("node_modules", "npm")
        cache_plugin.add_pattern("__pycache__", "python")
        ```
    """

    name = "builtin-cache"
    version = "1.0.0"

    def __init__(
        self,
        cache_dir: str = "/tmp/ci-engine-cache",
        ttl_seconds: int = 3600,
    ):
        super().__init__()
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._patterns: list[tuple[str, str]] = []
        self._hit_count = 0
        self._miss_count = 0

    def add_pattern(self, path_pattern: str, cache_type: str) -> None:
        """Add a cache pattern.

        Args:
            path_pattern: Path pattern to cache (e.g., "node_modules")
            cache_type: Type of cache (e.g., "npm", "pip", "build")
        """
        self._patterns.append((path_pattern, cache_type))

    def pre_execute(self, context: JobContext) -> JobContext:
        """Check cache before execution."""
        cache_key = self._get_cache_key(context)
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if time.time() - entry.created_at < self.ttl_seconds:
                entry.hits += 1
                self._hit_count += 1
                print(f"[CACHE] Hit for key: {cache_key}")
            else:
                del self._cache[cache_key]
                self._miss_count += 1
                print(f"[CACHE] Expired for key: {cache_key}")
        else:
            self._miss_count += 1
            print(f"[CACHE] Miss for key: {cache_key}")
        return context

    def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
        """Store build artifacts in cache after execution."""
        if result.exit_code == 0:
            cache_key = self._get_cache_key(context)
            self._cache[cache_key] = CacheEntry(
                key=cache_key,
                path=context.workspace,
                created_at=time.time(),
            )
            print(f"[CACHE] Stored for key: {cache_key}")
        return result

    def _get_cache_key(self, context: JobContext) -> str:
        """Generate cache key from job context."""
        return f"{context.build_id}-{context.label}-{context.agent_name}"

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "entries": len(self._cache),
            "hits": self._hit_count,
            "misses": self._miss_count,
            "hit_rate": self._hit_count / (self._hit_count + self._miss_count)
            if (self._hit_count + self._miss_count) > 0
            else 0,
        }


class EnvironmentPlugin(AgentPlugin):
    """Plugin that adds common environment variables to all jobs.

    Adds timestamps, build info, and other useful environment variables.
    """

    name = "builtin-environment"
    version = "1.0.0"

    def __init__(
        self,
        add_timestamp: bool = True,
        add_build_info: bool = True,
        add_agent_info: bool = True,
    ):
        super().__init__()
        self.add_timestamp = add_timestamp
        self.add_build_info = add_build_info
        self.add_agent_info = add_agent_info

    def pre_execute(self, context: JobContext) -> JobContext:
        """Add environment variables."""
        if self.add_timestamp:
            context.env_vars["CI_JOB_START_TIME"] = str(time.time())

        if self.add_build_info:
            context.env_vars["CI_BUILD_ID"] = str(context.build_id)
            context.env_vars["CI_JOB_ID"] = str(context.job_id)

        if self.add_agent_info:
            context.env_vars["CI_AGENT_NAME"] = context.agent_name
            context.env_vars["CI_AGENT_VERSION"] = "1.0.0"

        return context


class ValidationPlugin(AgentPlugin):
    """Plugin that validates job parameters before execution.

    Ensures jobs have required fields and valid configurations.
    """

    name = "builtin-validation"
    version = "1.0.0"

    def __init__(
        self,
        require_command: bool = True,
        max_timeout: int = 3600,
        allowed_images: list[str] | None = None,
    ):
        super().__init__()
        self.require_command = require_command
        self.max_timeout = max_timeout
        self.allowed_images = allowed_images or []

    def pre_execute(self, context: JobContext) -> JobContext:
        """Validate job context."""
        if self.require_command and not context.command:
            raise ValueError("Job command is required")

        if context.timeout_seconds > self.max_timeout:
            context.timeout_seconds = self.max_timeout

        if self.allowed_images and context.container_image:
            if context.container_image not in self.allowed_images:
                raise ValueError(f"Container image '{context.container_image}' not allowed")

        return context


class TimeoutPlugin(AgentPlugin):
    """Plugin that enforces job timeouts.

    Jobs that exceed the timeout will be terminated.
    """

    name = "builtin-timeout"
    version = "1.0.0"

    def __init__(self, default_timeout: int = 3600, kill_after: int = 30):
        super().__init__()
        self.default_timeout = default_timeout
        self.kill_after = kill_after

    def pre_execute(self, context: JobContext) -> JobContext:
        """Set timeout if not already set."""
        if context.timeout_seconds <= 0:
            context.timeout_seconds = self.default_timeout
        return context


def get_builtin_plugins() -> list[AgentPlugin]:
    """Get all built-in plugins as a list.

    Returns:
        List of built-in plugin instances
    """
    return [
        LoggingPlugin(),
        MetricsPlugin(),
        EnvironmentPlugin(),
        ValidationPlugin(),
        TimeoutPlugin(),
    ]


__all__ = [
    "LoggingPlugin",
    "MetricsPlugin",
    "CachePlugin",
    "EnvironmentPlugin",
    "ValidationPlugin",
    "TimeoutPlugin",
    "get_builtin_plugins",
]
