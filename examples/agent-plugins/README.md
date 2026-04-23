# CI Engine - Example Agent Plugins

This directory contains example plugins demonstrating the agent plugin system.

## Quick Start

```python
from ci_engine.agent.sdk import CIEngineAgent
from basic_plugin import MyBasicPlugin

agent = CIEngineAgent(
    name="my-agent",
    server_url="http://localhost:8000",
    plugins=[MyBasicPlugin()],
)
agent.run()
```

## Examples

| Plugin | Description |
|--------|-------------|
| `basic_plugin.py` | Simple plugin with timestamps |
| `slack_notify.py` | Slack notification on job completion |
| `cache_plugin.py` | Build artifact caching |
| `metrics_plugin.py` | Prometheus metrics |
| `env_transform.py` | Environment variable transformation |

## Creating Your Own Plugin

```python
from ci_engine.agent.sdk import CIEnginePlugin, JobContext, JobResult

class MyPlugin(CIEnginePlugin):
    name = "my-custom-plugin"
    version = "1.0.0"

    def pre_execute(self, context: JobContext) -> JobContext:
        # Modify job before execution
        context.env_vars["MY_VAR"] = "value"
        return context

    def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
        # Process result after execution
        print(f"Job {context.job_id} finished with exit code {result.exit_code}")
        return result
```

## Plugin Lifecycle

1. **Registration** - Plugin is registered with the agent
2. **on_register()** - Called when agent registers with server
3. **pre_execute()** - Called before each job execution
4. **post_execute()** - Called after each job execution
5. **on_error()** - Called if job execution fails
6. **on_heartbeat()** - Called on each heartbeat
7. **on_shutdown()** - Called when agent shuts down

## Middleware Example

```python
from ci_engine.agent.sdk import CIEngineMiddleware, MiddlewareOrder, MiddlewareContext

class MyMiddleware(CIEngineMiddleware):
    name = "my-middleware"
    order = MiddlewareOrder.NORMAL

    def pre_process(self, context: MiddlewareContext) -> MiddlewareContext:
        context.job["env_vars"]["EXTRA_VAR"] = "added"
        return context
```