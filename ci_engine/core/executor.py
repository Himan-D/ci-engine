# SPDX-License-Identifier: MIT
# CI Engine - Command executor

import subprocess
import os
import shlex
from typing import Optional
from pathlib import Path
from dataclasses import dataclass
from enum import Enum


class ExecutionStatus(str, Enum):
    """Status of command execution."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class ExecutionResult:
    """Result of command execution."""

    status: ExecutionStatus
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class Executor:
    """Execute build commands in isolated environments."""

    def __init__(self, workspace: str = "/tmp/ci-engine-workspace"):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        command: str,
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
        timeout: Optional[int] = 3600,
    ) -> tuple[int, str, str]:
        """Execute a command and return (exit_code, stdout, stderr)."""
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)

        work_dir = cwd or str(self.workspace)

        try:
            cmd_args = shlex.split(command)
        except ValueError as e:
            return -1, "", f"Invalid command syntax: {e}"

        try:
            result = subprocess.run(
                cmd_args,
                cwd=work_dir,
                env=exec_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout} seconds"

        except Exception as e:
            return -1, "", str(e)

    def execute_with_result(
        self,
        command: str,
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
        timeout: Optional[int] = 3600,
    ) -> ExecutionResult:
        """Execute a command and return detailed result."""
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)

        work_dir = cwd or str(self.workspace)

        try:
            cmd_args = shlex.split(command)
        except ValueError as e:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                exit_code=-1,
                stdout="",
                stderr=f"Invalid command syntax: {e}",
                timed_out=False,
            )

        try:
            result = subprocess.run(
                cmd_args,
                cwd=work_dir,
                env=exec_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS
                if result.returncode == 0
                else ExecutionStatus.FAILED,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=False,
            )

        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
                timed_out=True,
            )

        except Exception as e:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                timed_out=False,
            )

    def cleanup_workspace(self, build_id: int):
        """Clean up workspace for a specific build."""
        build_dir = self.workspace / f"build-{build_id}"
        if build_dir.exists():
            import shutil

            shutil.rmtree(build_dir)

    def prepare_workspace(self, build_id: int) -> str:
        """Prepare workspace directory for a build."""
        build_dir = self.workspace / f"build-{build_id}"
        build_dir.mkdir(parents=True, exist_ok=True)
        return str(build_dir)
