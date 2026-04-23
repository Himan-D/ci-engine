# SPDX-License-Identifier: MIT
# CI Engine - Agent SDK

"""
CI Engine Agent SDK

A user-friendly Python SDK for building custom CI agents with plugin support.

Example usage:

```python
from ci_engine.agent.sdk import CIEngineAgent, CIEnginePlugin

# Define a custom plugin
class MyPlugin(CIEnginePlugin):
    name = "my-plugin"

    def pre_execute(self, context):
        context.env_vars["MY_VAR"] = "custom-value"
        return context

# Create and run agent
agent = CIEngineAgent(
    name="custom-agent",
    server_url="http://localhost:8000",
    plugins=[MyPlugin()],
)
agent.run()
```

For more complex use cases, see examples/agent-plugins/
"""

from typing import Optional, Any

from ci_engine.agent.plugins import (
    AgentPlugin as CIEnginePlugin,
    PluginRegistry,
    JobContext,
    JobResult,
    create_plugin as create_ci_plugin,
)
from ci_engine.agent.middleware import (
    AgentMiddleware as CIEngineMiddleware,
    MiddlewareChain,
    MiddlewareManager,
    MiddlewareOrder,
    MiddlewareContext,
    TransformMiddleware,
    FilterMiddleware,
    ValidationMiddleware,
)


class CIEngineAgent:
    """User-friendly agent wrapper with plugin and middleware support.

    This is the main entry point for the Agent SDK. Use this class to create
    custom agents with plugin support.

    Args:
        name: Agent name (must be unique)
        server_url: CI Engine server URL
        plugins: List of plugins to use
        middleware: List of middleware to use
        tags: Agent tags for job matching
        skills: Agent skills for job matching
        max_parallel_jobs: Maximum jobs to run in parallel
        use_websocket: Use WebSocket for log streaming

    Example:
        ```python
        from ci_engine.agent.sdk import CIEngineAgent, CIEnginePlugin

        class SlackNotifyPlugin(CIEnginePlugin):
            name = "slack-notify"

            def post_execute(self, context, result):
                if result.exit_code == 0:
                    send_slack_message("Build passed!")
                else:
                    send_slack_message("Build failed!")
                return result

        agent = CIEngineAgent(
            name="my-agent",
            plugins=[SlackNotifyPlugin()],
        )
        agent.run()
        ```
    """

    def __init__(
        self,
        name: str,
        server_url: str = "http://localhost:8000",
        plugins: list[CIEnginePlugin] | None = None,
        middleware: list[CIEngineMiddleware] | None = None,
        tags: list[str] | None = None,
        skills: list[str] | None = None,
        max_parallel_jobs: int = 1,
        use_websocket: bool = True,
        version: str = "1.0.0",
    ):
        self.name = name
        self.server_url = server_url
        self.tags = tags or []
        self.skills = skills or []
        self.max_parallel_jobs = max_parallel_jobs
        self.use_websocket = use_websocket
        self.version = version

        # Initialize plugin system
        self._plugins = plugins or []
        self._middleware = middleware or []

        # Register all plugins
        for plugin in self._plugins:
            PluginRegistry.register(plugin)

    def run(self) -> None:
        """Start the agent.

        This creates a core Agent instance with plugin support and runs it.
        The agent will register with the server and start polling for jobs.
        """
        from ci_engine.agent.agent import Agent

        # Convert SDK agent to core agent
        core_agent = Agent(
            server_url=self.server_url,
            name=self.name,
            tags=self.tags,
            skills=self.skills,
            max_parallel_jobs=self.max_parallel_jobs,
            use_websocket=self.use_websocket,
            version=self.version,
            plugins=self._plugins,
            middleware=self._middleware,
        )

        # Notify plugins of registration
        for plugin in self._plugins:
            plugin.on_register(core_agent)

        print(f"Starting CI Engine Agent SDK (version {self.version})")
        print(f"Plugins loaded: {len(self._plugins)}")

        core_agent.run()


def create_agent(
    name: str,
    server_url: str = "http://localhost:8000",
    **kwargs,
) -> CIEngineAgent:
    """Factory function to create a CI Engine agent.

    This is a convenience function equivalent to CIEngineAgent(...).

    Args:
        name: Agent name
        server_url: Server URL
        **kwargs: Additional arguments passed to CIEngineAgent

    Returns:
        CIEngineAgent instance
    """
    return CIEngineAgent(name=name, server_url=server_url, **kwargs)


# Re-export commonly used classes for convenience
__all__ = [
    # Core classes
    "CIEngineAgent",
    "CIEnginePlugin",
    "CIEngineMiddleware",
    # Plugin utilities
    "PluginRegistry",
    "create_ci_plugin",
    "create_plugin",
    # Job data classes
    "JobContext",
    "JobResult",
    # Middleware utilities
    "MiddlewareChain",
    "MiddlewareManager",
    "MiddlewareOrder",
    "MiddlewareContext",
    "TransformMiddleware",
    "FilterMiddleware",
    "ValidationMiddleware",
    # Factory function
    "create_agent",
]


# For backwards compatibility, also expose the old names
create_plugin = create_ci_plugin
AgentPlugin = CIEnginePlugin
Middleware = CIEngineMiddleware
