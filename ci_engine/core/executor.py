# SPDX-License-Identifier: MIT
# CI Engine - Command executor

import subprocess
import os
import re
import shlex
from typing import Optional, Generator
from pathlib import Path
from dataclasses import dataclass
from enum import Enum


class ExecutionStatus(str, Enum):
    """Status of command execution."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


class CommandInjectionError(ValueError):
    """Raised when command contains potentially dangerous patterns."""

    pass


class CommandSanitizer:
    """Sanitize shell commands to prevent injection attacks.

    Commands run inside Docker/Podman containers which provide the primary
    isolation boundary. This sanitizer only blocks truly dangerous patterns
    (null bytes, uncontrolled env substitution into the *host* argument list)
    while allowing normal shell operators (&&, ||, ;, pipes, redirects) which
    are executed inside the container via `bash -c`.
    """

    # Patterns that are dangerous regardless of container context — these
    # would allow escaping the argument list or corrupting process state on
    # the host before the container even starts.
    DANGEROUS_PATTERNS = [
        (r"\x00", "Null byte injection"),
        (r"\r", "Carriage return injection"),
    ]

    @classmethod
    def sanitize(cls, command: str) -> str:
        """Sanitize a command string to prevent injection.

        The command will be executed as `bash -c <command>` inside a container,
        so shell operators (&&, ||, ;, |, $(), ${}) are intentionally allowed —
        they are normal CI syntax. Only truly unsafe patterns are rejected.
        """
        for pattern, description in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                raise CommandInjectionError(
                    f"Command contains dangerous pattern: {description}."
                )

        return command.strip()

    @classmethod
    def validate_safe(cls, command: str) -> tuple[bool, Optional[str]]:
        """Validate a command without raising an exception."""
        try:
            cls.sanitize(command)
            return True, None
        except CommandInjectionError as e:
            return False, str(e)


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

    @staticmethod
    def _build_cmd_args(command: str) -> list[str]:
        """Build subprocess argument list from a command string.

        If the command contains shell operators (&&, ||, ;, |, $(), ${}, ``)
        it is wrapped in `bash -c` so the shell can interpret them. Otherwise
        it is split with shlex for direct exec — safer and slightly faster.
        """
        SHELL_OPERATORS = ("&&", "||", ";", "|", "$(", "${", "`", "\n", ">", "<", ">>")
        if any(op in command for op in SHELL_OPERATORS):
            return ["bash", "-c", command]
        try:
            return shlex.split(command)
        except ValueError:
            # Malformed quoting — fall back to bash -c so the shell error
            # surfaces to the user as a build failure, not an agent crash.
            return ["bash", "-c", command]

    def execute_streaming(
        self,
        command: str,
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
        timeout: Optional[int] = 3600,
    ) -> Generator[tuple[str, str], None, int]:
        """Execute a command and yield (stream, line) tuples in real time.

        Yields each line of stdout/stderr as it is produced so callers can
        stream logs to the browser without waiting for the process to finish.

        Returns the exit code via StopIteration.value when the generator
        is exhausted.

        Usage:
            gen = executor.execute_streaming(cmd)
            exit_code = None
            try:
                while True:
                    stream, line = next(gen)
                    handle_log(stream, line)
            except StopIteration as e:
                exit_code = e.value
        """
        import threading

        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)

        work_dir = cwd or str(self.workspace)

        try:
            sanitized = CommandSanitizer.sanitize(command)
        except CommandInjectionError as e:
            yield ("stderr", f"Command rejected: {e}")
            return -1

        try:
            proc = subprocess.Popen(
                self._build_cmd_args(sanitized),
                cwd=work_dir,
                env=exec_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # line-buffered
            )
        except Exception as e:
            yield ("stderr", str(e))
            return -1

        # Use a queue to merge stdout/stderr preserving arrival order
        import queue as _queue

        line_queue: _queue.Queue = _queue.Queue()
        done_count = [0]

        def _reader(stream, label):
            try:
                for line in stream:
                    line_queue.put((label, line.rstrip("\n")))
            finally:
                done_count[0] += 1
                line_queue.put(None)  # sentinel

        t_out = threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True)
        t_err = threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True)
        t_out.start()
        t_err.start()

        import time
        deadline = time.monotonic() + (timeout or 3600)
        sentinels_seen = 0

        try:
            while sentinels_seen < 2:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    proc.kill()
                    yield ("stderr", f"Command timed out after {timeout} seconds")
                    proc.wait()
                    return -1

                try:
                    item = line_queue.get(timeout=min(remaining, 0.5))
                except _queue.Empty:
                    continue

                if item is None:
                    sentinels_seen += 1
                    continue

                stream, line = item
                if line:  # skip empty lines to reduce noise
                    yield (stream, line)
        finally:
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        return proc.returncode

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
            sanitized = CommandSanitizer.sanitize(command)
        except CommandInjectionError as e:
            return -1, "", f"Command rejected: {e}"

        try:
            result = subprocess.run(
                self._build_cmd_args(sanitized),
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
            result = subprocess.run(
                self._build_cmd_args(command),
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
