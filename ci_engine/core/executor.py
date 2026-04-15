# SPDX-License-Identifier: MIT
# CI Engine - Command executor

import subprocess
import os
from typing import Optional
from pathlib import Path


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
            result = subprocess.run(
                command,
                shell=True,
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
