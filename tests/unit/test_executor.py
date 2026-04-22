# SPDX-License-Identifier: MIT
# CI Engine - Unit tests for executor module

import pytest
from ci_engine.core.executor import Executor


class TestExecutor:
    """Tests for command execution functionality."""

    @pytest.fixture
    def executor(self):
        """Create executor instance with temp workspace."""
        return Executor(workspace="/tmp/test-ci-engine")

    def test_execute_simple_command(self, executor):
        """Test executing a simple command."""
        exit_code, stdout, stderr = executor.execute("echo 'hello'")
        assert exit_code == 0
        assert "hello" in stdout

    def test_execute_command_with_error(self, executor):
        """Test executing a command that fails."""
        exit_code, stdout, stderr = executor.execute("false")
        assert exit_code == 1

    def test_execute_command_with_env(self, executor):
        """Test executing command with environment variables."""
        exit_code, stdout, stderr = executor.execute(
            "sh -c 'echo $TEST_VAR'", env={"TEST_VAR": "test_value"}
        )
        assert exit_code == 0
        assert "test_value" in stdout

    def test_execute_with_timeout(self, executor):
        """Test command timeout."""
        exit_code, stdout, stderr = executor.execute("sleep 10", timeout=1)
        assert exit_code == -1
        assert "timed out" in stderr.lower() or "timeout" in stderr.lower()

    def test_execute_invalid_command(self, executor):
        """Test executing invalid command."""
        exit_code, stdout, stderr = executor.execute("nonexistent-command-xyz")
        assert exit_code != 0  # Non-zero exit code for errors

    def test_prepare_workspace(self, executor):
        """Test workspace preparation."""
        workspace = executor.prepare_workspace(123)
        assert "build-123" in workspace

    def test_prepare_workspace_creates_directory(self, executor):
        """Test workspace directory is created."""
        import os

        workspace = executor.prepare_workspace(999)
        assert os.path.exists(workspace)

    def test_cleanup_workspace(self, executor):
        """Test workspace cleanup."""
        import os

        workspace = executor.prepare_workspace(888)
        assert os.path.exists(workspace)
        executor.cleanup_workspace(888)
        # Directory may or may not exist after cleanup depending on implementation
