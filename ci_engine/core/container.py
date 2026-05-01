# SPDX-License-Identifier: MIT
# CI Engine - Container Isolation (Docker Executor)

import os
import subprocess
import uuid
from typing import Optional, Dict
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
class ContainerSecurityPolicy:
    """Security constraints applied to a job container.

    Defaults match a hardened CI profile: no privilege escalation, all
    capabilities dropped, read-only root filesystem, limited PIDs.
    Pipelines may relax specific settings via the ``security:`` DSL block.
    """
    allow_privilege_escalation: bool = False
    drop_all_capabilities: bool = True
    read_only_rootfs: bool = True
    # "builtin" → use bundled seccomp.json; None → no seccomp; path → custom
    seccomp_profile: Optional[str] = "builtin"
    pids_limit: int = 256
    # "none" = no network (default); "bridge" = standard Docker bridge
    network_mode: str = "bridge"
    # Extra tmpfs mounts beyond the default /tmp (e.g. /home/user/.cache)
    extra_tmpfs: Optional[list] = None

    @classmethod
    def from_pipeline(cls, security_dict: Optional[dict]) -> "ContainerSecurityPolicy":
        """Parse a pipeline ``security:`` block into a policy object."""
        if not security_dict:
            return cls()
        return cls(
            allow_privilege_escalation=security_dict.get("allow_privilege_escalation", False),
            drop_all_capabilities=security_dict.get("drop_all_capabilities", True),
            read_only_rootfs=security_dict.get("read_only_rootfs", True),
            seccomp_profile=security_dict.get("seccomp", "builtin"),
            pids_limit=int(security_dict.get("pids_limit", 256)),
            network_mode=security_dict.get("network", "bridge"),
            extra_tmpfs=security_dict.get("extra_tmpfs"),
        )


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
    security: Optional[ContainerSecurityPolicy] = None
    build_id: int = 0   # for container label


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
        """Build the docker run command with security hardening."""
        sec: ContainerSecurityPolicy = config.security or ContainerSecurityPolicy()

        cmd = [
            self.runtime.value, "run",
            "--name", container_name,
            "--rm",
            "-w", config.workdir,
            # Label for orphan cleanup
            "--label", f"ci-engine-build-id={getattr(config, 'build_id', 0)}",
        ]

        # Network
        network = sec.network_mode or config.network_mode or "bridge"
        cmd.extend(["--network", network])

        # Resource limits
        if config.cpu_limit:
            cmd.extend(["--cpus", config.cpu_limit])
        if config.memory_limit:
            cmd.extend(["--memory", config.memory_limit])

        # PID limit
        cmd.extend(["--pids-limit", str(sec.pids_limit)])

        # Security options
        if not sec.allow_privilege_escalation:
            cmd.extend(["--security-opt", "no-new-privileges:true"])

        if sec.drop_all_capabilities:
            cmd.extend(["--cap-drop", "ALL"])
            # Network operations need NET_BIND_SERVICE when network is enabled
            if network not in ("none", ""):
                cmd.extend(["--cap-add", "NET_BIND_SERVICE"])

        # Seccomp profile
        if sec.seccomp_profile == "builtin":
            profile_path = os.path.join(os.path.dirname(__file__), "seccomp.json")
            if os.path.exists(profile_path):
                cmd.extend(["--security-opt", f"seccomp={profile_path}"])
        elif sec.seccomp_profile and sec.seccomp_profile != "unconfined":
            if os.path.exists(sec.seccomp_profile):
                cmd.extend(["--security-opt", f"seccomp={sec.seccomp_profile}"])
        elif sec.seccomp_profile == "unconfined":
            cmd.extend(["--security-opt", "seccomp=unconfined"])

        # Read-only root filesystem + writable /tmp tmpfs
        if sec.read_only_rootfs:
            cmd.append("--read-only")
            cmd.extend(["--tmpfs", "/tmp:size=512m,mode=1777"])
            # Node.js npm cache often lands in ~/.npm
            cmd.extend(["--tmpfs", "/root/.npm:size=256m,mode=0700"])

        # Extra tmpfs mounts requested by the pipeline
        for extra in (sec.extra_tmpfs or []):
            cmd.extend(["--tmpfs", extra])

        # Volumes
        if config.volumes:
            for vol in [f"{workspace_dir}:{config.workdir}"] + config.volumes:
                cmd.extend(["-v", vol])
        else:
            cmd.extend(["-v", f"{workspace_dir}:{config.workdir}"])

        # Environment variables
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
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout cleaning up container {container_name}")
        except FileNotFoundError:
            logger.debug("Runtime not available for cleanup")
        except Exception as e:
            logger.warning(f"Failed to clean up container {container_name}: {e}")


@dataclass
class ServiceConfig:
    """Configuration for a service container (sidecar)."""

    name: str
    image: str
    env_vars: Optional[Dict[str, str]] = None
    ports: Optional[list[str]] = None
    healthcheck: Optional[str] = None


class ServiceContainerManager:
    """Manages service containers for build jobs.

    Supports starting PostgreSQL, Redis, MySQL, and other services
    alongside build jobs.

    Usage:
        manager = ServiceContainerManager()

        # Start services before job
        services = [
            ServiceConfig(name="db", image="postgres:15", env_vars={"POSTGRES_PASSWORD": "test"}),
            ServiceConfig(name="cache", image="redis:7"),
        ]
        await manager.start_services(services, build_id=123)

        # Get connection info
        db_url = manager.get_connection_url("db", "postgres")
        # -> postgresql://postgres:test@localhost:5432

        # After job completes
        await manager.stop_services()
    """

    def __init__(self, runtime: ContainerRuntime = ContainerRuntime.DOCKER):
        self.runtime = runtime
        self._active_services: Dict[str, str] = {}  # name -> container_id

    async def start_services(
        self,
        services: list[ServiceConfig],
        build_id: int,
    ) -> Dict[str, str]:
        """Start service containers.

        Args:
            services: List of service configurations
            build_id: Build ID for container naming

        Returns:
            Dict mapping service name to container ID
        """
        results = {}

        for svc in services:
            container_name = f"ci-engine-svc-{build_id}-{svc.name}"

            try:
                cmd = [
                    self.runtime.value,
                    "run",
                    "--name",
                    container_name,
                    "--rm",
                    "-d",  # Detached mode
                ]

                # Add environment variables
                if svc.env_vars:
                    for key, value in svc.env_vars.items():
                        cmd.extend(["-e", f"{key}={value}"])

                # Add port mappings
                if svc.ports:
                    for port in svc.ports:
                        cmd.extend(["-p", port])

                cmd.append(svc.image)

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if result.returncode == 0:
                    self._active_services[svc.name] = container_name
                    results[svc.name] = container_name
                    logger.info(f"Started service {svc.name} in container {container_name}")
                else:
                    logger.error(f"Failed to start service {svc.name}: {result.stderr}")

            except Exception as e:
                logger.error(f"Error starting service {svc.name}: {e}")

        return results

    def get_connection_url(
        self,
        service_name: str,
        service_type: str = "postgres",
    ) -> Optional[str]:
        """Get connection URL for a service.

        Args:
            service_name: Name of the service
            service_type: Type of service (postgres, redis, mysql, mongo)

        Returns:
            Connection URL string, or None if service not found
        """
        if service_name not in self._active_services:
            return None

        # Get port mappings from running container
        try:
            cmd = [
                self.runtime.value,
                "port",
                self._active_services[service_name],
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            port_mappings = {}
            for line in result.stdout.strip().split("\n"):
                if ":" in line:
                    host_port, container_port = line.split(":")
                    port_mappings[container_port] = host_port

            # Determine default port and return connection URL
            ports = {
                "postgres": ("5432", "postgresql", "postgres", "test"),
                "redis": ("6379", "redis", "", ""),
                "mysql": ("3306", "mysql", "root", "test"),
                "mongo": ("27017", "mongodb", "root", "test"),
            }

            if service_type not in ports:
                return None

            default_port, scheme, user, password = ports[service_type]
            host_port = port_mappings.get(default_port, default_port)

            if service_type == "redis":
                return f"redis://localhost:{host_port}"
            elif service_type == "mongo":
                return f"mongodb://{user}:{password}@localhost:{host_port}"
            else:
                return f"{scheme}://{user}:{password}@localhost:{host_port}"

        except Exception as e:
            logger.error(f"Error getting connection URL for {service_name}: {e}")
            return None

    async def stop_services(self) -> None:
        """Stop all active service containers."""
        for service_name, container_id in self._active_services.items():
            try:
                subprocess.run(
                    [self.runtime.value, "rm", "-f", container_id],
                    capture_output=True,
                    timeout=10,
                )
                logger.info(f"Stopped service container {container_id}")
            except Exception as e:
                logger.error(f"Error stopping service {service_name}: {e}")

        self._active_services.clear()

    def get_service_ip(self, service_name: str) -> Optional[str]:
        """Get the IP address of a service container.

        Args:
            service_name: Name of the service

        Returns:
            IP address, or None if service not found
        """
        if service_name not in self._active_services:
            return None

        try:
            cmd = [
                self.runtime.value,
                "inspect",
                "-f",
                "{{.NetworkSettings.IPAddress}}",
                self._active_services[service_name],
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

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
