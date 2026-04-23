# SPDX-License-Identifier: MIT
# Tests for Agent Plugin System

import pytest

from ci_engine.agent.plugins import (
    AgentPlugin,
    JobContext,
    JobResult,
    PluginRegistry,
    HookDispatcher,
    create_plugin,
)
from ci_engine.agent.middleware import (
    AgentMiddleware,
    MiddlewareChain,
    MiddlewareOrder,
    MiddlewareContext,
    TransformMiddleware,
)


class TestJobContext:
    """Tests for JobContext."""

    def test_create_from_job_dict(self):
        """Test creating JobContext from job dict."""
        job = {
            "id": 123,
            "command": "echo hello",
            "label": "Test Job",
            "build_id": 456,
            "env_vars": '{"KEY": "value"}',
            "container_image": "node:18",
            "timeout_seconds": 300,
        }
        context = JobContext.from_job(job)

        assert context.job_id == 123
        assert context.command == "echo hello"
        assert context.label == "Test Job"
        assert context.build_id == 456
        assert context.env_vars == {"KEY": "value"}
        assert context.container_image == "node:18"
        assert context.timeout_seconds == 300

    def test_create_from_job_dict_no_env(self):
        """Test creating JobContext from job dict without env_vars."""
        job = {"id": 1, "command": "test"}
        context = JobContext.from_job(job)

        assert context.job_id == 1
        assert context.env_vars == {}


class TestJobResult:
    """Tests for JobResult."""

    def test_create_from_result(self):
        """Test creating JobResult from execution."""
        result = JobResult.from_result(0, "output", "error", False, 100)

        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.stderr == "error"
        assert result.timed_out == False
        assert result.duration_ms == 100


class TestPluginRegistry:
    """Tests for PluginRegistry."""

    def setup_method(self):
        """Clear registry before each test."""
        PluginRegistry.clear()

    def test_register_plugin(self):
        """Test registering a plugin."""

        class TestPlugin(AgentPlugin):
            name = "test-plugin"

        plugin = TestPlugin()
        PluginRegistry.register(plugin)

        assert len(PluginRegistry.get_plugins()) == 1
        assert PluginRegistry.get_plugin("test-plugin") is plugin

    def test_unregister_plugin(self):
        """Test unregistering a plugin."""

        class TestPlugin(AgentPlugin):
            name = "test-plugin"

        plugin = TestPlugin()
        PluginRegistry.register(plugin)
        assert PluginRegistry.unregister("test-plugin") == True
        assert len(PluginRegistry.get_plugins()) == 0

    def test_duplicate_registration_raises(self):
        """Test that duplicate registration raises error."""

        class TestPlugin(AgentPlugin):
            name = "test-plugin"

        plugin1 = TestPlugin()
        plugin2 = TestPlugin()
        PluginRegistry.register(plugin1)

        with pytest.raises(ValueError):
            PluginRegistry.register(plugin2)


class TestAgentPlugin:
    """Tests for AgentPlugin."""

    def test_plugin_default_enabled(self):
        """Test plugin is enabled by default."""

        class TestPlugin(AgentPlugin):
            name = "test"

        plugin = TestPlugin()
        assert plugin.enabled == True

    def test_plugin_can_disable(self):
        """Test plugin can be disabled."""

        class TestPlugin(AgentPlugin):
            name = "test"

        plugin = TestPlugin()
        plugin.enabled = False
        assert plugin.enabled == False


class TestHookDispatcher:
    """Tests for HookDispatcher."""

    def test_dispatch_pre_execute(self):
        """Test dispatching pre_execute hooks."""

        class TestPlugin(AgentPlugin):
            name = "test"

            def pre_execute(self, context):
                context.env_vars["added"] = "value"
                return context

        dispatcher = HookDispatcher([TestPlugin()])
        context = JobContext(job_id=1, command="test")

        result = dispatcher.dispatch_pre_execute(context)

        assert result.env_vars["added"] == "value"

    def test_dispatch_post_execute(self):
        """Test dispatching post_execute hooks."""

        class TestPlugin(AgentPlugin):
            name = "test"

            def post_execute(self, context, result):
                result.stdout = "modified"
                return result

        dispatcher = HookDispatcher([TestPlugin()])
        context = JobContext(job_id=1, command="test")
        result = JobResult(exit_code=0, stdout="original", stderr="")

        new_result = dispatcher.dispatch_post_execute(context, result)

        assert new_result.stdout == "modified"


class TestCreatePlugin:
    """Tests for create_plugin factory."""

    def test_create_simple_plugin(self):
        """Test creating a simple plugin."""

        def pre_hook(context):
            context.env_vars["pre"] = "added"
            return context

        plugin = create_plugin("my-plugin", "1.0.0", pre_execute=pre_hook)

        assert plugin.name == "my-plugin"
        assert plugin.version == "1.0.0"

        context = JobContext(job_id=1, command="test")
        result = plugin.pre_execute(context)

        assert result.env_vars["pre"] == "added"


class TestMiddlewareChain:
    """Tests for MiddlewareChain."""

    def test_add_middleware(self):
        """Test adding middleware to chain."""

        class TestMiddleware(AgentMiddleware):
            name = "test-mw"

            def pre_process(self, context):
                context.job["modified"] = True
                return context

        chain = MiddlewareChain()
        chain.add(TestMiddleware())

        job = {"id": 1}
        result = chain.process_pre(job)

        assert result["modified"] == True

    def test_middleware_order(self):
        """Test middleware executes in order."""

        class FirstMiddleware(AgentMiddleware):
            name = "first"
            order = MiddlewareOrder.FIRST

            def pre_process(self, context):
                context.job["order"] = context.job.get("order", []) + ["first"]
                return context

        class LastMiddleware(AgentMiddleware):
            name = "last"
            order = MiddlewareOrder.LAST

            def pre_process(self, context):
                context.job["order"] = context.job.get("order", []) + ["last"]
                return context

        class NormalMiddleware(AgentMiddleware):
            name = "normal"
            order = MiddlewareOrder.NORMAL

            def pre_process(self, context):
                context.job["order"] = context.job.get("order", []) + ["normal"]
                return context

        chain = MiddlewareChain()
        chain.add(LastMiddleware())
        chain.add(FirstMiddleware())
        chain.add(NormalMiddleware())

        job = {"id": 1}
        result = chain.process_pre(job)

        assert result["order"] == ["first", "normal", "last"]


class TestTransformMiddleware:
    """Tests for TransformMiddleware."""

    def test_transform_job(self):
        """Test transforming job."""

        class UppercaseMiddleware(TransformMiddleware):
            name = "uppercase"

            def transform_job(self, job):
                job["command"] = job.get("command", "").upper()
                return job

        middleware = UppercaseMiddleware()
        job = {"command": "echo hello"}

        context = MiddlewareContext(job=job)
        result = middleware.pre_process(context)

        assert result.job["command"] == "ECHO HELLO"

    def test_transform_result(self):
        """Test transforming result."""

        class WrapMiddleware(TransformMiddleware):
            name = "wrap"

            def transform_result(self, job, result):
                exit_code, stdout, stderr = result
                return (exit_code, f"[{stdout}]", f"[{stderr}]")

        middleware = WrapMiddleware()
        job = {"id": 1}
        result = (0, "output", "error")

        context = MiddlewareContext(job=job, result=result)
        new_result = middleware.post_process(context)

        assert new_result.result == (0, "[output]", "[error]")


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up after tests."""
    yield
    PluginRegistry.clear()
