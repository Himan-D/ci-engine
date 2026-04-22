# SPDX-License-Identifier: MIT
# CI Engine - Build Agent

import sys
import time
import json
import threading
import queue
import os
import requests
from typing import Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, Future
from enum import Enum


class JobState(str, Enum):
    """Job execution states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RunningJob:
    """Track a running job."""

    job_id: int
    future: Future
    label: str
    started_at: float
    workspace: str


class Agent:
    """Build agent that executes jobs from the CI server."""

    def __init__(
        self,
        server_url: str,
        name: str,
        tags: list[str] | None = None,
        skills: list[str] | None = None,
        use_websocket: bool = True,
        max_parallel_jobs: int = 1,
        workspace_prefix: str = "/tmp/ci-engine-workspace",
        max_memory_mb: int = 0,
        max_cpu_percent: int = 0,
    ):
        self.server_url = server_url.rstrip("/")
        self.name = name
        self.max_memory_mb = max_memory_mb
        self.max_cpu_percent = max_cpu_percent
        self.tags = tags or []
        self.skills = skills or []
        self.agent_id: Optional[int] = None
        self.use_websocket = use_websocket
        self.max_parallel_jobs = max_parallel_jobs
        self.workspace_prefix = workspace_prefix
        self.ws = None
        self.heartbeat_interval = 30
        self._job_queue: queue.Queue[int] = queue.Queue()
        self._executor: ThreadPoolExecutor | None = None
        self._running_jobs: dict[int, RunningJob] = {}
        self._lock = threading.Lock()
        self._resource_monitor_running = False

    def register(self) -> bool:
        """Register this agent with the CI server."""
        try:
            response = requests.post(
                f"{self.server_url}/api/agents/register",
                json={
                    "name": self.name,
                    "hostname": self._get_hostname(),
                    "tags": self.tags,
                    "skills": self.skills,
                },
                timeout=10,
            )
            if response.status_code == 200:
                self.agent_id = response.json().get("id")
                print(f"Registered as agent #{self.agent_id}")
                if self.skills:
                    print(f"Registered skills: {', '.join(self.skills)}")
                return True
        except requests.RequestException as e:
            print(f"Failed to register: {e}")
        return False

    def _get_hostname(self) -> str:
        """Get the hostname of this machine."""
        import socket

        return socket.gethostname()

    def send_heartbeat(self):
        """Send heartbeat to server to indicate agent is alive."""
        if not self.agent_id:
            return
        try:
            requests.post(
                f"{self.server_url}/api/agents/{self.agent_id}/heartbeat",
                timeout=5,
            )
        except requests.RequestException:
            pass

    def start_heartbeat(self):
        """Start background heartbeat thread."""

        def heartbeat_loop():
            while True:
                self.send_heartbeat()
                time.sleep(self.heartbeat_interval)

        thread = threading.Thread(target=heartbeat_loop, daemon=True)
        thread.start()

    def poll_for_job(self) -> Optional[dict]:
        """Poll for available jobs."""
        try:
            response = requests.get(
                f"{self.server_url}/api/builds",
                params={"status": "pending"},
                timeout=10,
            )
            if response.status_code == 200:
                builds = response.json()
                for build in builds:
                    for job in build.get("jobs", []):
                        if job.get("status") == "pending":
                            return job
        except requests.RequestException as e:
            print(f"Failed to poll for jobs: {e}")
        return None

    def claim_job(self, job_id: int) -> bool:
        """Claim a job to execute."""
        try:
            response = requests.post(
                f"{self.server_url}/api/jobs/{job_id}/claim",
                params={"agent_id": self.agent_id},
                timeout=10,
            )
            return response.status_code == 200
        except requests.RequestException as e:
            print(f"Failed to claim job: {e}")
        return False

    def connect_websocket(self, job_id: int) -> bool:
        """Connect to WebSocket for real-time log streaming."""
        if not self.use_websocket:
            return False
        try:
            ws_url = self.server_url.replace("http", "ws") + f"/ws/jobs/{job_id}/logs"
            import websocket

            self.ws = websocket.WebSocket()
            self.ws.connect(ws_url, timeout=5)
            return True
        except Exception as e:
            print(f"Failed to connect to WebSocket: {e}")
            return False

    def send_log_ws(self, job_id: int, stream: str, line: str):
        """Send log via WebSocket."""
        if self.ws:
            try:
                self.ws.send(
                    json.dumps(
                        {
                            "type": "log",
                            "job_id": job_id,
                            "stream": stream,
                            "line": line,
                            "timestamp": time.time(),
                        }
                    )
                )
                return True
            except Exception:
                pass
        return False

    def execute_job(self, job: dict) -> int:
        """Execute a job and return exit code.

        Uses Executor class for proper isolation, timeout handling, and container support.
        """
        import os as os_module
        import subprocess

        print(f"Executing job #{job['id']}: {job['label']}")
        print(f"Command: {job['command']}")

        job_id = job["id"]
        command = job.get("command", "")
        container_image = job.get("container_image")
        timeout_seconds = job.get("timeout_seconds", 3600)

        if self.use_websocket:
            self.connect_websocket(job_id)

        try:
            if container_image:
                print(f"Running in container: {container_image}")
                from ci_engine.core.container import execute_in_container

                workspace_dir = os_module.environ.get("CI_WORKSPACE", "/tmp/ci-engine-workspace")
                os_module.makedirs(workspace_dir, exist_ok=True)

                env_vars = {}
                env_var_str = job.get("env_vars", "")
                if env_var_str:
                    try:
                        env_vars = json.loads(env_var_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

                result = execute_in_container(
                    image=container_image,
                    command=command,
                    env_vars=env_vars,
                    timeout=timeout_seconds,
                    workspace=workspace_dir,
                    build_id=job.get("build_id", 0),
                )
                exit_code = result.exit_code
                stdout = result.stdout
                stderr = result.stderr
            else:
                from ci_engine.core.executor import Executor

                executor = Executor(
                    workspace=os_module.environ.get("CI_WORKSPACE", "/tmp/ci-engine-workspace")
                )

                env_vars = {}
                env_var_str = job.get("env_vars", "")
                if env_var_str:
                    try:
                        env_vars = json.loads(env_var_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

                exit_code, stdout, stderr = executor.execute(
                    command=command,
                    env=env_vars if env_vars else None,
                    timeout=timeout_seconds,
                )

            if stdout:
                if not self.send_log_ws(job_id, "stdout", stdout):
                    self._send_log(job_id, "stdout", stdout)
            if stderr:
                if not self.send_log_ws(job_id, "stderr", stderr):
                    self._send_log(job_id, "stderr", stderr)

            return exit_code

        except subprocess.TimeoutExpired:
            self.send_log_ws(job_id, "stderr", f"Job timed out after {timeout_seconds}s")
            self._send_log(job_id, "stderr", f"Job timed out after {timeout_seconds}s")
            return -1
        except ValueError as e:
            error_msg = f"Invalid command syntax: {e}"
            self.send_log_ws(job_id, "stderr", error_msg)
            self._send_log(job_id, "stderr", error_msg)
            return -1
        except Exception as e:
            error_msg = str(e)
            self.send_log_ws(job_id, "stderr", error_msg)
            self._send_log(job_id, "stderr", error_msg)
            return -1
        finally:
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
                self.ws = None

    def _send_log(self, job_id: int, stream: str, line: str):
        """Send log line to server via HTTP."""
        try:
            requests.post(
                f"{self.server_url}/api/jobs/{job_id}/log",
                json={"stream": stream, "line": line},
                timeout=5,
            )
        except requests.RequestException:
            pass

    def complete_job(self, job_id: int, exit_code: int):
        """Mark job as completed."""
        try:
            requests.post(
                f"{self.server_url}/api/jobs/{job_id}/complete",
                params={"exit_code": exit_code},
                timeout=10,
            )
        except requests.RequestException as e:
            print(f"Failed to complete job: {e}")

    def run(self):
        """Main agent loop."""
        if not self.register():
            print("Failed to register with server. Exiting.")
            sys.exit(1)

        self.start_heartbeat()

        if self.max_parallel_jobs > 1 or self.max_memory_mb > 0 or self.max_cpu_percent > 0:
            self._resource_monitor_running = True
            monitor_thread = threading.Thread(target=self._resource_monitor_loop, daemon=True)
            monitor_thread.start()

        if self.max_parallel_jobs > 1:
            self._executor = ThreadPoolExecutor(max_workers=self.max_parallel_jobs)
            print(
                f"Agent {self.name} ready. Running up to {self.max_parallel_jobs} jobs in parallel."
            )
            self._run_parallel()
        else:
            print(f"Agent {self.name} ready. Polling for jobs...")
            self._run_single()

    def _run_single(self):
        """Single job execution mode."""
        while True:
            job = self.poll_for_job()
            if job:
                if self.claim_job(job["id"]):
                    try:
                        requests.post(
                            f"{self.server_url}/api/jobs/{job['id']}/start",
                            timeout=10,
                        )
                    except requests.RequestException:
                        pass

                    exit_code = self.execute_job(job)
                    self.complete_job(job["id"], exit_code)
                else:
                    print("Failed to claim job")
            else:
                time.sleep(5)

    def _run_parallel(self):
        """Parallel job execution mode."""
        while True:
            if not self._executor:
                break

            available_slots = self.max_parallel_jobs - len(self._running_jobs)

            while available_slots > 0:
                job = self.poll_for_job()
                if not job:
                    break

                if self.claim_job(job["id"]):
                    try:
                        requests.post(
                            f"{self.server_url}/api/jobs/{job['id']}/start",
                            timeout=10,
                        )
                    except requests.RequestException:
                        pass

                    job_id = job["id"]
                    workspace = self._prepare_job_workspace(job_id)

                    future = self._executor.submit(self.execute_job_isolated, job, workspace)
                    self._running_jobs[job_id] = RunningJob(
                        job_id=job_id,
                        future=future,
                        label=job.get("label", f"job-{job_id}"),
                        started_at=time.time(),
                        workspace=workspace,
                    )
                    print(f"Started job {job_id} ({job.get('label')}) in parallel")
                    available_slots -= 1
                else:
                    break

            completed = []
            for job_id, running in self._running_jobs.items():
                if running.future.done():
                    try:
                        exit_code = running.future.result()
                        self.complete_job(job_id, exit_code)
                        print(f"Completed job {job_id} ({running.label}) - exit {exit_code}")
                    except Exception as e:
                        print(f"Job {job_id} ({running.label}) failed: {e}")
                        self.complete_job(job_id, -1)
                    completed.append(job_id)

            for job_id in completed:
                del self._running_jobs[job_id]
                self._cleanup_job_workspace(job_id)

            if self._running_jobs:
                time.sleep(0.5)
            else:
                time.sleep(2)

    def _resource_monitor_loop(self):
        """Monitor resource usage of running jobs."""
        import psutil

        while self._resource_monitor_running:
            for job_id, running in list(self._running_jobs.items()):
                if not running.future.done():
                    try:
                        process = psutil.Process(running.future.result().pid)
                        mem_mb = process.memory_info().rss / 1024 / 1024
                        cpu_percent = process.cpu_percent()

                        if self.max_memory_mb > 0 and mem_mb > self.max_memory_mb:
                            print(
                                f"Job {job_id} exceeded memory limit: {mem_mb:.1f}MB > {self.max_memory_mb}MB"
                            )
                            process.terminate()

                        if self.max_cpu_percent > 0 and cpu_percent > self.max_cpu_percent:
                            print(
                                f"Job {job_id} exceeded CPU limit: {cpu_percent:.1f}% > {self.max_cpu_percent}%"
                            )
                            process.terminate()
                    except Exception:
                        pass

            time.sleep(1)

    def _prepare_job_workspace(self, job_id: int) -> str:
        """Prepare isolated workspace for a job."""
        workspace = f"{self.workspace_prefix}/job-{job_id}"
        os.makedirs(workspace, exist_ok=True)
        return workspace

    def _cleanup_job_workspace(self, job_id: int):
        """Clean up job workspace."""
        import shutil

        workspace = f"{self.workspace_prefix}/job-{job_id}"
        try:
            if os.path.exists(workspace):
                shutil.rmtree(workspace)
        except Exception:
            pass

    def execute_job_isolated(self, job: dict, workspace: str) -> int:
        """Execute a job in an isolated workspace."""
        import subprocess

        job_id = job["id"]
        label = job.get("label", f"job-{job_id}")

        print(f"Executing job #{job_id}: {label} (workspace: {workspace})")

        command = job.get("command", "")
        container_image = job.get("container_image")
        timeout_seconds = job.get("timeout_seconds", 3600)

        ws = None
        if self.use_websocket:
            try:
                ws_url = self.server_url.replace("http", "ws") + f"/ws/jobs/{job_id}/logs"
                import websocket

                ws = websocket.WebSocket()
                ws.connect(ws_url, timeout=5)
            except Exception:
                pass

        def send_log(stream: str, line: str):
            if ws:
                try:
                    ws.send(
                        json.dumps(
                            {"type": "log", "job_id": job_id, "stream": stream, "line": line}
                        )
                    )
                except Exception:
                    pass
            self._send_log(job_id, stream, line)

        try:
            exit_code = 0
            stdout = ""
            stderr = ""

            if container_image:
                from ci_engine.core.container import execute_in_container

                env_vars = {}
                env_var_str = job.get("env_vars", "")
                if env_var_str:
                    try:
                        env_vars = json.loads(env_var_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

                result = execute_in_container(
                    image=container_image,
                    command=command,
                    env_vars=env_vars,
                    timeout=timeout_seconds,
                    workspace=workspace,
                    build_id=job.get("build_id", 0),
                )
                exit_code = result.exit_code
                stdout = result.stdout
                stderr = result.stderr
            else:
                from ci_engine.core.executor import Executor

                executor = Executor(workspace=workspace)

                env_vars = {}
                env_var_str = job.get("env_vars", "")
                if env_var_str:
                    try:
                        env_vars = json.loads(env_var_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

                exit_code, stdout, stderr = executor.execute(
                    command=command,
                    env=env_vars if env_vars else None,
                    timeout=timeout_seconds,
                )

            if stdout:
                send_log("stdout", stdout)
            if stderr:
                send_log("stderr", stderr)

            return exit_code

        except subprocess.TimeoutExpired:
            send_log("stderr", f"Job timed out after {timeout_seconds}s")
            return -1
        except ValueError as e:
            send_log("stderr", f"Invalid command syntax: {e}")
            return -1
        except Exception as e:
            send_log("stderr", str(e))
            return -1
        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="CI Engine Agent")
    parser.add_argument("--server", default="http://localhost:8000", help="Server URL")
    parser.add_argument("--name", required=True, help="Agent name")
    parser.add_argument("--tags", nargs="*", default=[], help="Agent tags")
    parser.add_argument("--no-ws", action="store_true", help="Disable WebSocket for log streaming")
    parser.add_argument(
        "--parallel-jobs",
        type=int,
        default=1,
        help="Maximum number of parallel jobs (default: 1)",
    )
    parser.add_argument(
        "--max-memory",
        type=int,
        default=0,
        help="Max memory per job in MB (0 = unlimited)",
    )
    parser.add_argument(
        "--max-cpu",
        type=int,
        default=0,
        help="Max CPU percentage per job (0 = unlimited)",
    )
    parser.add_argument(
        "--skills",
        nargs="*",
        default=[],
        help="Agent skills (e.g., docker kubernetes python)",
    )

    args = parser.parse_args()

    agent = Agent(
        args.server,
        args.name,
        args.tags,
        skills=args.skills,
        use_websocket=not args.no_ws,
        max_parallel_jobs=args.parallel_jobs,
        max_memory_mb=args.max_memory,
        max_cpu_percent=args.max_cpu,
    )
    agent.run()


if __name__ == "__main__":
    main()
