# SPDX-License-Identifier: MIT
# Basic Agent Plugin Example

import time

from ci_engine.agent.sdk import CIEnginePlugin, JobContext, JobResult


class MyBasicPlugin(CIEnginePlugin):
    """A basic plugin that adds timestamps to output.

    This is a simple example demonstrating the plugin interface.
    It logs the start and end of each job with timestamps.
    """

    name = "example-basic"
    version = "1.0.0"

    def pre_execute(self, context: JobContext) -> JobContext:
        """Called before job execution."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [PLUGIN] Starting job #{context.job_id}: {context.label}")
        return context

    def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
        """Called after job execution."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        status = "PASSED" if result.exit_code == 0 else "FAILED"
        print(
            f"[{timestamp}] [PLUGIN] Job #{context.job_id} {status} (exit={result.exit_code}, {result.duration_ms}ms)"
        )
        return result


class PrefixOutputPlugin(CIEnginePlugin):
    """Plugin that prefixes all output with job label."""

    name = "example-prefix"
    version = "1.0.0"

    def __init__(self, prefix: str = "[JOB]"):
        super().__init__()
        self.prefix = prefix

    def pre_execute(self, context: JobContext) -> JobContext:
        """Add prefix to command output."""
        context.env_vars["OUTPUT_PREFIX"] = self.prefix
        return context


if __name__ == "__main__":
    # Test the plugin
    plugin = MyBasicPlugin()
    print(f"Plugin: {plugin.name} v{plugin.version}")

    # Simulate execution
    context = JobContext(
        job_id=1,
        command="echo hello",
        label="Test Job",
        build_id=1,
    )
    print("\nPre-execute:")
    context = plugin.pre_execute(context)

    result = JobResult(exit_code=0, stdout="hello\n", stderr="", duration_ms=100)
    print("\nPost-execute:")
    result = plugin.post_execute(context, result)
    print(f"\nFinal exit code: {result.exit_code}")
