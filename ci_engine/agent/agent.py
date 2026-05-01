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
        version: str = "1.0.0",
        plugins: list | None = None,
        middleware: list | None = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.name = name
        self.max_memory_mb = max_memory_mb
        self.max_cpu_percent = max_cpu_percent
        self.tags = tags or []
        self.skills = skills or []
        self.version = version
        self.agent_id: Optional[int] = None
        self.use_websocket = use_websocket
        self.max_parallel_jobs = max_parallel_jobs
        self.workspace_prefix = workspace_prefix
        self.ws = None
        self.heartbeat_interval = 30
        self._job_queue: queue.Queue[int] = queue.Queue()
        self._executor: ThreadPoolExecutor | None = None
        self._running_jobs: dict[int, RunningJob] = {}
        self._job_pids: dict[int, int] = {}  # job_id → subprocess PID for resource monitor
        self._lock = threading.Lock()
        self._resource_monitor_running = False

        # Plugin system
        self._plugins = plugins or []
        self._middleware = None
        if middleware:
            from ci_engine.agent.middleware import MiddlewareChain

            self._middleware = MiddlewareChain()
            for mw in middleware:
                self._middleware.add(mw)

        # Register plugins with this agent
        for plugin in self._plugins:
            plugin.on_register(self)

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
                    "version": self.version,
                },
                timeout=10,
            )
            if response.status_code == 200:
                self.agent_id = response.json().get("id")
                print(f"Registered as agent #{self.agent_id} (version {self.version})")
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
                f"{self.server_url}/api/jobs/pending",
                timeout=10,
            )
            if response.status_code == 200:
                jobs = response.json()
                if jobs:
                    return jobs[0]
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
        """Execute a job with real-time log streaming.

        Streams stdout/stderr line-by-line to the server WebSocket and HTTP
        log endpoint as the process runs — no buffering until completion.
        """
        import os as os_module
        from datetime import datetime, timezone

        print(f"Executing job #{job['id']}: {job['label']}")
        print(f"Command: {job['command']}")

        job_id = job["id"]
        command = job.get("command", "")
        container_image = job.get("container_image")
        timeout_seconds = job.get("timeout_seconds", 3600)

        # Plugin system
        from ci_engine.agent.plugins import JobContext, JobResult, HookDispatcher

        context = JobContext.from_job(job)
        context.agent_name = self.name
        context.agent_id = self.agent_id

        if self._middleware:
            job = self._middleware.process_pre(job)

        dispatcher = HookDispatcher(self._plugins)
        context = dispatcher.dispatch_pre_execute(context)
        job["command"] = context.command
        job["env_vars"] = context.env_vars
        job["container_image"] = context.container_image
        job["timeout_seconds"] = context.timeout_seconds
        command = context.command
        container_image = context.container_image
        timeout_seconds = context.timeout_seconds

        # pre_checkout hook — fired before workspace is set up / git clone
        context = dispatcher.dispatch_pre_checkout(context)

        if self.use_websocket:
            self.connect_websocket(job_id)

        start_time = datetime.now(timezone.utc)
        exit_code = -1

        def send_line(stream: str, line: str):
            """Send a single log line via WS + HTTP fallback."""
            if not self.send_log_ws(job_id, stream, line):
                self._send_log(job_id, stream, line)
            else:
                # Also persist to DB via HTTP so logs survive WS disconnect
                self._send_log(job_id, stream, line)

        try:
            # Per-build isolated workspace so concurrent builds don't clobber each other
            build_info = job.get("build", {})
            repository = build_info.get("repository") if build_info else None
            build_id = job.get("build_id", 0)
            base_workspace = os_module.environ.get("CI_WORKSPACE", "/tmp/ci-engine-workspace")
            workspace_dir = os_module.path.join(base_workspace, f"build-{build_id}")
            os_module.makedirs(workspace_dir, exist_ok=True)

            # Only clone if the repository is a real URL (not a label like "org/repo")
            is_clonable = repository and (
                repository.startswith("http://")
                or repository.startswith("https://")
                or repository.startswith("git@")
                or repository.startswith("ssh://")
                or repository.startswith("git://")
            )
            if is_clonable:
                from ci_engine.agent.git import clone_repository, GitCloneError

                send_line("stdout", f"==> Cloning {repository}")
                branch = build_info.get("branch", "main")
                commit = build_info.get("commit")
                ref = commit or branch or "main"
                depth = build_info.get("clone_depth")

                try:
                    clone_repository(
                        repo_url=repository,
                        target_dir=workspace_dir,
                        ref=ref,
                        depth=depth,
                    )
                    send_line("stdout", f"==> Cloned {ref}")
                except GitCloneError as e:
                    send_line("stderr", f"Clone failed: {e}")
                    return 1
                except FileNotFoundError:
                    send_line("stderr", "Git not installed on agent")
                    return 1

            # post_checkout hook — fired after workspace / git clone is ready
            context = dispatcher.dispatch_post_checkout(context)

            # pre_command hook — last chance to modify command/env before execution
            context = dispatcher.dispatch_pre_command(context)
            command = context.command  # allow hooks to rewrite the command

            # Build env: merge job env_vars over process environment
            env_vars: dict[str, str] = {}
            raw_env = job.get("env_vars") or {}
            if isinstance(raw_env, str):
                try:
                    raw_env = json.loads(raw_env)
                except Exception:
                    raw_env = {}
            if isinstance(raw_env, dict):
                env_vars.update({str(k): str(v) for k, v in raw_env.items()})

            # Inject standard CI environment variables
            env_vars.setdefault("CI", "true")
            env_vars.setdefault("CI_ENGINE", "true")
            env_vars.setdefault("BUILD_ID", str(job.get("build_id", "")))
            env_vars.setdefault("JOB_ID", str(job_id))
            env_vars.setdefault("JOB_LABEL", job.get("label", ""))

            if container_image:
                send_line("stdout", f"==> Running in container: {container_image}")
                from ci_engine.core.container import execute_in_container

                result = execute_in_container(
                    image=container_image,
                    command=command,
                    env_vars=env_vars,
                    timeout=timeout_seconds,
                    workspace=workspace_dir,
                    build_id=job.get("build_id", 0),
                )
                exit_code = result.exit_code
                # Container output arrives all at once — stream line by line
                for line in result.stdout.splitlines():
                    send_line("stdout", line)
                for line in result.stderr.splitlines():
                    send_line("stderr", line)
            else:
                from ci_engine.core.executor import Executor

                executor = Executor(workspace=workspace_dir)

                send_line("stdout", f"$ {command}")

                # Real-time streaming via generator
                gen = executor.execute_streaming(
                    command=command,
                    env=env_vars if env_vars else None,
                    timeout=timeout_seconds,
                )
                try:
                    while True:
                        stream, line = next(gen)
                        send_line(stream, line)
                        # Periodically check for cancellation
                        if self._check_job_cancelled(job_id):
                            send_line("stderr", "Job cancelled")
                            exit_code = -1
                            break
                except StopIteration as e:
                    exit_code = e.value if e.value is not None else -1

            return exit_code

        except Exception as e:
            send_line("stderr", f"Agent error: {e}")
            exit_code = -1
            return exit_code
        finally:
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            result_obj = JobResult.from_result(exit_code, "", "", timeout_seconds > 0, duration_ms)
            # post_command fires immediately after command, before post_execute plugins
            result_obj = dispatcher.dispatch_post_command(context, result_obj)
            dispatcher.dispatch_post_execute(context, result_obj)

            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
                self.ws = None

    def _send_log(self, job_id: int, stream: str, line: str):
        """Persist a single log line to the server database via HTTP."""
        try:
            requests.post(
                f"{self.server_url}/api/jobs/{job_id}/log",
                params={"stream": stream, "line": line},
                timeout=3,
            )
        except requests.RequestException:
            pass

    def _check_job_cancelled(self, job_id: int) -> bool:
        """Check if this job has been cancelled server-side."""
        try:
            response = requests.get(
                f"{self.server_url}/api/jobs/{job_id}",
                timeout=3,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("status") in ("canceled", "cancelled")
        except requests.RequestException:
            pass
        return False

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

    # ------------------------------------------------------------------
    # Buildkite-compatible agent helpers
    # ------------------------------------------------------------------

    def annotate(
        self,
        build_id: int,
        body_html: str,
        style: str = "info",
        context: str = "default",
        job_id: Optional[int] = None,
    ) -> bool:
        """Post or update a build annotation.

        Equivalent to ``buildkite-agent annotate``.

        Args:
            build_id: The build to annotate.
            body_html: HTML body of the annotation.
            style: Visual style — ``success``, ``warning``, ``error``, or ``info``.
            context: Unique key for this annotation (upserted by context).
            job_id: Optional job that created this annotation.

        Returns:
            True on success, False on error.
        """
        try:
            resp = requests.post(
                f"{self.server_url}/api/builds/{build_id}/annotations",
                json={
                    "context": context,
                    "body_html": body_html,
                    "style": style,
                    "created_by_job_id": job_id,
                },
                timeout=10,
            )
            return resp.status_code in (200, 201)
        except requests.RequestException as exc:
            print(f"annotate() failed: {exc}")
            return False

    def metadata_set(self, build_id: int, key: str, value: str, job_id: Optional[int] = None) -> bool:
        """Set a build metadata key-value pair.

        Equivalent to ``buildkite-agent meta-data set KEY VALUE``.
        """
        try:
            resp = requests.post(
                f"{self.server_url}/api/builds/{build_id}/metadata/{key}",
                json={"value": value, "set_by_job_id": job_id},
                timeout=10,
            )
            return resp.status_code in (200, 201)
        except requests.RequestException as exc:
            print(f"metadata_set() failed: {exc}")
            return False

    def metadata_get(self, build_id: int, key: str) -> Optional[str]:
        """Get a build metadata value by key.

        Equivalent to ``buildkite-agent meta-data get KEY``.
        Returns None if the key is not set or on network error.
        """
        try:
            resp = requests.get(
                f"{self.server_url}/api/builds/{build_id}/metadata/{key}",
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("value")
        except requests.RequestException as exc:
            print(f"metadata_get() failed: {exc}")
        return None

    def pipeline_upload(self, build_id: int, pipeline_yaml: str) -> dict:
        """Dynamically append steps to the current build.

        Equivalent to ``buildkite-agent pipeline upload``.

        Args:
            build_id: The running build to append steps to.
            pipeline_yaml: YAML string defining the new steps.

        Returns:
            Dict with ``jobs_added`` and ``job_ids`` on success, or ``{}`` on error.
        """
        try:
            resp = requests.post(
                f"{self.server_url}/api/builds/{build_id}/pipeline-upload",
                json={"pipeline_yaml": pipeline_yaml},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException as exc:
            print(f"pipeline_upload() failed: {exc}")
        return {}

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
        """Monitor resource usage of running jobs and enforce limits."""
        try:
            import psutil
        except ImportError:
            return  # psutil not available — skip monitoring

        while self._resource_monitor_running:
            for job_id, running in list(self._running_jobs.items()):
                if running.future.done():
                    continue

                # Check server-side cancellation
                if self._check_job_cancelled(job_id):
                    print(f"Job {job_id} cancelled — terminating process")
                    pid = self._job_pids.get(job_id)
                    if pid:
                        try:
                            proc = psutil.Process(pid)
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except psutil.TimeoutExpired:
                                proc.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    continue

                # Enforce memory/CPU limits if configured
                if self.max_memory_mb <= 0 and self.max_cpu_percent <= 0:
                    continue

                pid = self._job_pids.get(job_id)
                if not pid:
                    continue

                try:
                    proc = psutil.Process(pid)
                    if self.max_memory_mb > 0:
                        mem_mb = proc.memory_info().rss / 1024 / 1024
                        if mem_mb > self.max_memory_mb:
                            print(
                                f"Job {job_id} exceeded memory limit: "
                                f"{mem_mb:.1f}MB > {self.max_memory_mb}MB — terminating"
                            )
                            proc.terminate()

                    if self.max_cpu_percent > 0:
                        cpu = proc.cpu_percent(interval=0.1)
                        if cpu > self.max_cpu_percent:
                            print(
                                f"Job {job_id} exceeded CPU limit: "
                                f"{cpu:.1f}% > {self.max_cpu_percent}% — terminating"
                            )
                            proc.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
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
        """Execute a job in an isolated workspace with real-time log streaming."""
        job_id = job["id"]
        label = job.get("label", f"job-{job_id}")

        print(f"Executing job #{job_id}: {label} (workspace: {workspace})")

        command = job.get("command", "")
        container_image = job.get("container_image")
        timeout_seconds = job.get("timeout_seconds", 3600)

        # Connect WebSocket for live streaming
        ws = None
        if self.use_websocket:
            try:
                ws_url = self.server_url.replace("http", "ws") + f"/ws/jobs/{job_id}/logs"
                import websocket as _ws_lib

                ws = _ws_lib.WebSocket()
                ws.connect(ws_url, timeout=5)
            except Exception:
                pass

        def send_line(stream: str, line: str):
            if ws:
                try:
                    ws.send(json.dumps({
                        "type": "log", "job_id": job_id, "stream": stream, "line": line,
                    }))
                except Exception:
                    pass
            # Always persist to DB
            self._send_log(job_id, stream, line)

        # Build env vars
        env_vars: dict[str, str] = {}
        raw_env = job.get("env_vars") or {}
        if isinstance(raw_env, str):
            try:
                raw_env = json.loads(raw_env)
            except Exception:
                raw_env = {}
        if isinstance(raw_env, dict):
            env_vars.update({str(k): str(v) for k, v in raw_env.items()})

        env_vars.setdefault("CI", "true")
        env_vars.setdefault("CI_ENGINE", "true")
        env_vars.setdefault("BUILD_ID", str(job.get("build_id", "")))
        env_vars.setdefault("JOB_ID", str(job_id))

        exit_code = -1
        try:
            if container_image:
                from ci_engine.core.container import execute_in_container

                send_line("stdout", f"==> Container: {container_image}")
                result = execute_in_container(
                    image=container_image,
                    command=command,
                    env_vars=env_vars,
                    timeout=timeout_seconds,
                    workspace=workspace,
                    build_id=job.get("build_id", 0),
                )
                exit_code = result.exit_code
                for line in result.stdout.splitlines():
                    send_line("stdout", line)
                for line in result.stderr.splitlines():
                    send_line("stderr", line)
            else:
                from ci_engine.core.executor import Executor

                executor = Executor(workspace=workspace)
                send_line("stdout", f"$ {command}")

                gen = executor.execute_streaming(
                    command=command,
                    env=env_vars if env_vars else None,
                    timeout=timeout_seconds,
                )
                try:
                    while True:
                        stream, line = next(gen)
                        send_line(stream, line)
                        if self._check_job_cancelled(job_id):
                            send_line("stderr", "Job cancelled")
                            exit_code = -1
                            break
                except StopIteration as e:
                    exit_code = e.value if e.value is not None else -1

            return exit_code

        except Exception as e:
            send_line("stderr", f"Agent error: {e}")
            return -1
        finally:
            with self._lock:
                self._job_pids.pop(job_id, None)
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
    parser.add_argument(
        "--auto-detect-skills",
        action="store_true",
        help="Auto-detect installed skills on this machine",
    )
    parser.add_argument(
        "--force-detect",
        action="store_true",
        help="Force re-detection even if cached",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Filter skills by category (e.g., build, test, deploy)",
    )
    parser.add_argument(
        "--list-skills",
        action="store_true",
        help="List all available skills and exit",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear skill cache before detection",
    )
    parser.add_argument(
        "--ai-auto-fix",
        action="store_true",
        default=None,
        help="Enable AI-powered autonomous job self-healing (requires CI_ENGINE_ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--no-ai-auto-fix",
        action="store_true",
        help="Disable AI auto-fix even if API key is set (analysis-only mode)",
    )

    args = parser.parse_args()

    if args.clear_cache:
        from ci_engine.agent.skills import SkillCache

        SkillCache.clear()
        print("Skill cache cleared.")

    if args.list_skills:
        from ci_engine.agent.skills import list_all_skills

        skills = list_all_skills()
        category_filter = args.category

        print(f"\n=== Available Skills ({skills['total']}) ===\n")

        if category_filter:
            cat_skills = [s for s in skills["skills"] if s["category"] == category_filter]
            info = skills["categories"].get(
                category_filter, {"display_name": category_filter.title()}
            )
            print(f"\n## {info['display_name']} ({len(cat_skills)} skills)")
            for s in cat_skills:
                custom_tag = " [CUSTOM]" if s.get("custom") else ""
                print(f"  - {s['name']}: {s['description']}{custom_tag}")
        else:
            for category, info in skills["categories"].items():
                cat_skills = [s for s in skills["skills"] if s["category"] == category]
                print(f"\n## {info['display_name']} ({len(cat_skills)} skills)")
                for s in cat_skills:
                    custom_tag = " [CUSTOM]" if s.get("custom") else ""
                    print(f"  - {s['name']}: {s['description']}{custom_tag}")
        return

    if args.auto_detect_skills:
        from ci_engine.agent.skills import auto_detect_skills

        print("Detecting installed skills...")
        detected = auto_detect_skills(force=args.force_detect or args.clear_cache)
        print(f"\nDetected {detected['summary']['total_installed']} skills:\n")

        category_filter = args.category
        if category_filter:
            if category_filter in detected["summary"]["by_category"]:
                info = detected["summary"]["by_category"][category_filter]
                print(f"  {category_filter}: {', '.join(info['skills'])}")
        else:
            for cat, info in detected["summary"]["by_category"].items():
                if info["installed"] > 0:
                    print(f"  {cat}: {', '.join(info['skills'])}")

        health = detected["summary"].get("health", {})
        if health.get("unhealthy", 0) > 0:
            print(f"\n⚠️  {health['unhealthy']} skills marked as unhealthy")

        args.skills = [s["name"] for s in detected["skills"]]

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

    # Wire up AI self-healing plugin if an API key is available
    import os as _os
    if _os.environ.get("CI_ENGINE_ANTHROPIC_API_KEY"):
        from ci_engine.agent.ai_healing import AIHealingPlugin

        auto_fix = not args.no_ai_auto_fix
        if args.ai_auto_fix is not None:
            auto_fix = bool(args.ai_auto_fix)
        healing = AIHealingPlugin(
            server_url=args.server,
            auto_fix=auto_fix,
            token=_os.environ.get("CI_ENGINE_AGENT_TOKEN", ""),
        )
        agent._plugins.append(healing)
        print(f"AI self-healing enabled (auto_fix={auto_fix})")

    agent.run()


if __name__ == "__main__":
    main()
