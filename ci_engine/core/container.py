# SPDX-License-Identifier: MIT
# CI Engine - Container Isolation (Docker Executor)

import os
import json
import subprocess
import uuid
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

from ci_engine.core.logging import get_logger

logger = get_logger("ci_engine.container")


class ContainerRuntime(str, Enum):
    """Supported container runtimes."""

    DOCKER = "docker"
    PODMAN = "podman"
    CONTAINERD = "containerd"


@dataclass
class ContainerConfig:
    """Configuration for a containerized job execution."""

    image: str
    command: str
    workdir: str = "/workspace"
    env_vars: Optional[Dict[str, str]] = None
    cpu_limit: Optional[str] = None
    memory_limit: Optional[str] = None
    network_mode: str = "bridge"
    user: Optional[str] = None
    volumes: Optional[list] = None
    timeout_seconds: int = 3600


@dataclass
class ContainerResult:
    """Result of a containerized command execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    container_id: str


class DockerExecutor:
    """Execute build commands inside Docker containers."""

    def __init__(self, runtime: ContainerRuntime = ContainerRuntime.DOCKER):
        self.runtime = runtime
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if Docker/Podman is available on this system."""
        if self._available is not None:
            return self._available

        try:
            cmd = ["docker", "info"]
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            self._available = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            try:
                cmd = ["podman", "info"]
                result = subprocess.run(cmd, capture_output=True, timeout=5)
                self._available = result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError):
                self._available = False

        return self._available

    def execute(
        self, config: ContainerConfig, workspace_dir: str, build_id: int
    ) -> ContainerResult:
        """Execute a command inside a container."""
        if not self.is_available():
            return self._execute_locally(config, workspace_dir)

        container_name = f"ci-engine-build-{build_id}-{uuid.uuid4().hex[:8]}"

        try:
            result = subprocess.run(
                self._build_run_command(config, container_name, workspace_dir),
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
            )
            return ContainerResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=result.returncode == -1,
                container_id=container_name,
            )
        except subprocess.TimeoutExpired:
            self._cleanup_container(container_name)
            return ContainerResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {config.timeout_seconds} seconds",
                timed_out=True,
                container_id=container_name,
            )
        finally:
            self._cleanup_container(container_name)

    def _build_run_command(
        self, config: ContainerConfig, container_name: str, workspace_dir: str
    ) -> list:
        """Build the docker run command."""
        cmd = [self.runtime.value, "run", "--name", container_name, "--rm", "-w", config.workdir]
        if config.network_mode:
            cmd.extend(["--network", config.network_mode])
        if config.cpu_limit:
            cmd.extend(["--cpus", config.cpu_limit])
        if config.memory_limit:
            cmd.extend(["--memory", config.memory_limit])
        if config.volumes:
            for vol in [f"{workspace_dir}:{config.workdir}"] + config.volumes:
                cmd.extend(["-v", vol])
        else:
            cmd.extend(["-v", f"{workspace_dir}:{config.workdir}"])
        if config.env_vars:
            for key, value in config.env_vars.items():
                cmd.extend(["-e", f"{key}={value}"])
        cmd.append(config.image)
        cmd.extend(["/bin/sh", "-c", config.command])
        return cmd

    def _execute_locally(self, config: ContainerConfig, workspace_dir: str) -> ContainerResult:
        """Fallback to local execution."""
        import shlex

        exec_env = os.environ.copy()
        if config.env_vars:
            exec_env.update(config.env_vars)

        try:
            result = subprocess.run(
                shlex.split(config.command),
                shell=False,
                cwd=workspace_dir,
                env=exec_env,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
            )
            return ContainerResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=False,
                container_id="local",
            )
        except subprocess.TimeoutExpired:
            return ContainerResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {config.timeout_seconds} seconds",
                timed_out=True,
                container_id="local",
            )

    def _cleanup_container(self, container_name: str) -> None:
        """Clean up a container."""
        try:
            subprocess.run(
                [self.runtime.value, "rm", "-f", container_name], capture_output=True, timeout=10
            )
        except Exception:
            pass

    def pull_image(self, image: str) -> bool:
        """Pull a container image."""
        try:
            result = subprocess.run(
                [self.runtime.value, "pull", image], capture_output=True, timeout=300
            )
            return result.returncode == 0
        except Exception:
            return False


def get_default_image() -> str:
    """Get the default container image for builds."""
    return os.environ.get("CI_ENGINE_DEFAULT_IMAGE", "ubuntu:22.04")


def parse_container_requirements(step: dict) -> Optional[ContainerConfig]:
    """Parse container requirements from a pipeline step."""
    container_spec = step.get("container")
    if not container_spec:
        return None

    if isinstance(container_spec, str):
        container_spec = {"image": container_spec}

    return ContainerConfig(
        image=container_spec.get("image", get_default_image()),
        command=step.get("command", ""),
        workdir=container_spec.get("workdir", "/workspace"),
        env_vars=container_spec.get("env"),
        cpu_limit=container_spec.get("cpu"),
        memory_limit=container_spec.get("memory"),
        network_mode=container_spec.get("network", "bridge"),
        user=container_spec.get("user"),
        volumes=container_spec.get("volumes"),
        timeout_seconds=step.get("timeout", 3600),
    )


_docker_executor: Optional[DockerExecutor] = None


def get_docker_executor() -> DockerExecutor:
    """Get the global DockerExecutor instance."""
    global _docker_executor
    if _docker_executor is None:
        runtime_str = os.environ.get("CI_CONTAINER_RUNTIME", "docker")
        try:
            runtime = ContainerRuntime(runtime_str.lower())
        except ValueError:
            runtime = ContainerRuntime.DOCKER
        _docker_executor = DockerExecutor(runtime=runtime)
    return _docker_executor


def execute_in_container(
    image: str,
    command: str,
    env_vars: Optional[Dict[str, str]] = None,
    cpu_limit: Optional[str] = None,
    memory_limit: Optional[str] = None,
    timeout: int = 3600,
    workspace: str = "/tmp/ci-engine-workspace",
    build_id: int = 0,
) -> ContainerResult:
    """Convenience function to execute a command in a container."""
    config = ContainerConfig(
        image=image,
        command=command,
        workdir="/workspace",
        env_vars=env_vars,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        timeout_seconds=timeout,
    )
    executor = get_docker_executor()
    return executor.execute(config, workspace, build_id)


__all__ = [
    "DockerExecutor",
    "ContainerConfig",
    "ContainerResult",
    "ContainerRuntime",
    "parse_container_requirements",
    "execute_in_container",
    "get_docker_executor",
    "get_default_image",
]
