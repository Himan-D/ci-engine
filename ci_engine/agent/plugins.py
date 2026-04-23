# SPDX-License-Identifier: MIT
# CI Engine - Agent Plugin System

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional, Any
from datetime import datetime, timezone


@dataclass
class JobContext:
    """Job execution context passed to plugins."""

    job_id: int
    command: str
    env_vars: dict[str, str] = field(default_factory=dict)
    container_image: Optional[str] = None
    timeout_seconds: int = 3600
    label: str = ""
    build_id: int = 0
    workspace: str = "/tmp/ci-engine-workspace"
    agent_name: str = ""
    agent_id: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_job(cls, job: dict) -> "JobContext":
        """Create context from job dict."""
        env_vars = {}
        env_var_str = job.get("env_vars", "")
        if env_var_str:
            try:
                import json

                env_vars = json.loads(env_var_str)
            except Exception:
                pass

        return cls(
            job_id=job.get("id", 0),
            command=job.get("command", ""),
            env_vars=env_vars,
            container_image=job.get("container_image"),
            timeout_seconds=job.get("timeout_seconds", 3600),
            label=job.get("label", ""),
            build_id=job.get("build_id", 0),
            workspace=job.get("workspace", "/tmp/ci-engine-workspace"),
            agent_name=job.get("agent_name", ""),
            agent_id=job.get("agent_id"),
        )


@dataclass
class JobResult:
    """Result of job execution."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_ms: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_result(
        cls, exit_code: int, stdout: str, stderr: str, timed_out: bool = False, duration_ms: int = 0
    ) -> "JobResult":
        """Create result from execution data."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_ms=duration_ms,
            started_at=now,
            finished_at=now,
        )


class AgentPlugin(ABC):
    """Base class for agent plugins.

    To create a plugin, subclass this and implement the hooks you need:

    ```python
    class MyPlugin(AgentPlugin):
        name = "my-plugin"
        version = "1.0.0"

        def pre_execute(self, context: JobContext) -> JobContext:
            # Modify job before execution
            context.env_vars["MY_VAR"] = "value"
            return context

        def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
            # Process result after execution
            if result.exit_code == 0:
                print(f"Job {context.job_id} succeeded!")
            return result
    ```
    """

    name: str = "base-plugin"
    version: str = "1.0.0"

    def __init__(self):
        self._enabled = True
        self._agent = None

    @property
    def enabled(self) -> bool:
        """Check if plugin is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable plugin."""
        self._enabled = value

    def on_register(self, agent: Any) -> None:
        """Called when plugin is registered with an agent.

        Args:
            agent: The agent instance
        """
        self._agent = agent

    def on_unregister(self) -> None:
        """Called when plugin is unregistered from an agent."""
        self._agent = None

    def pre_execute(self, context: JobContext) -> JobContext:
        """Called before job execution.

        Use this hook to:
        - Modify environment variables
        - Change command to execute
        - Set up workspace
        - Validate job parameters

        Args:
            context: Job execution context

        Returns:
            Modified job context
        """
        return context

    def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
        """Called after job execution.

        Use this hook to:
        - Process results
        - Send notifications
        - Upload artifacts
        - Clean up resources

        Args:
            context: Job execution context
            result: Job execution result

        Returns:
            Modified job result
        """
        return result

    def on_error(self, context: JobContext, error: Exception) -> None:
        """Called when job execution fails.

        Args:
            context: Job execution context
            error: The exception that occurred
        """
        pass

    def on_heartbeat(self, agent: Any) -> None:
        """Called on each heartbeat.

        Args:
            agent: The agent instance
        """
        pass

    def on_shutdown(self) -> None:
        """Called when agent is shutting down."""
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, version={self.version})"


class PluginRegistry:
    """Registry for agent plugins.

    Tracks all registered plugins and provides utilities for plugin management.
    """

    _plugins: list[AgentPlugin] = []
    _plugin_by_name: dict[str, AgentPlugin] = {}

    @classmethod
    def register(cls, plugin: AgentPlugin) -> None:
        """Register a plugin.

        Args:
            plugin: Plugin instance to register
        """
        if plugin.name in cls._plugin_by_name:
            raise ValueError(f"Plugin '{plugin.name}' is already registered")

        cls._plugins.append(plugin)
        cls._plugin_by_name[plugin.name] = plugin

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Unregister a plugin by name.

        Args:
            name: Plugin name

        Returns:
            True if plugin was found and removed
        """
        if name not in cls._plugin_by_name:
            return False

        plugin = cls._plugin_by_name.pop(name)
        cls._plugins.remove(plugin)
        return True

    @classmethod
    def get_plugins(cls) -> list[AgentPlugin]:
        """Get all registered plugins."""
        return cls._plugins.copy()

    @classmethod
    def get_plugin(cls, name: str) -> Optional[AgentPlugin]:
        """Get a plugin by name."""
        return cls._plugin_by_name.get(name)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered plugins."""
        cls._plugins.clear()
        cls._plugin_by_name.clear()

    @classmethod
    def list_names(cls) -> list[str]:
        """Get names of all registered plugins."""
        return list(cls._plugin_by_name.keys())


class HookDispatcher:
    """Dispatches hooks to registered plugins."""

    def __init__(self, plugins: list[AgentPlugin] | None = None):
        self._plugins = plugins or []

    def add_plugin(self, plugin: AgentPlugin) -> None:
        """Add a plugin to this dispatcher."""
        self._plugins.append(plugin)

    def dispatch_pre_execute(self, context: JobContext) -> JobContext:
        """Dispatch pre_execute hooks to all plugins."""
        for plugin in self._plugins:
            if plugin.enabled:
                try:
                    context = plugin.pre_execute(context)
                except Exception as e:
                    plugin.on_error(context, e)
        return context

    def dispatch_post_execute(self, context: JobContext, result: JobResult) -> JobResult:
        """Dispatch post_execute hooks to all plugins."""
        for plugin in self._plugins:
            if plugin.enabled:
                try:
                    result = plugin.post_execute(context, result)
                except Exception as e:
                    plugin.on_error(context, e)
        return result

    def dispatch_on_error(self, context: JobContext, error: Exception) -> None:
        """Dispatch on_error hooks to all plugins."""
        for plugin in self._plugins:
            if plugin.enabled:
                try:
                    plugin.on_error(context, error)
                except Exception:
                    pass


def create_plugin(
    name: str,
    version: str = "1.0.0",
    pre_execute: Optional[callable] = None,
    post_execute: Optional[callable] = None,
    on_error: Optional[callable] = None,
) -> AgentPlugin:
    """Factory function to create a simple plugin.

    Args:
        name: Plugin name
        version: Plugin version
        pre_execute: Optional pre-execute hook
        post_execute: Optional post-execute hook
        on_error: Optional error handler

    Returns:
        A configured plugin instance
    """

    plugin_name = name
    plugin_version = version

    class SimplePlugin(AgentPlugin):
        name = plugin_name
        version = plugin_version

        def pre_execute(self, context: JobContext) -> JobContext:
            if pre_execute:
                return pre_execute(context)
            return context

        def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
            if post_execute:
                return post_execute(context, result)
            return result

        def on_error(self, context: JobContext, error: Exception) -> None:
            if on_error:
                on_error(context, error)

    return SimplePlugin()
