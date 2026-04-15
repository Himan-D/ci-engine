# SPDX-License-Identifier: MIT
# CI Engine - Build Agent

import sys
import time
import requests
from typing import Optional


class Agent:
    """Build agent that executes jobs from the CI server."""

    def __init__(self, server_url: str, name: str, tags: list[str] | None = None):
        self.server_url = server_url.rstrip("/")
        self.name = name
        self.tags = tags or []
        self.agent_id: Optional[int] = None

    def register(self) -> bool:
        """Register this agent with the CI server."""
        try:
            response = requests.post(
                f"{self.server_url}/api/agents/register",
                json={
                    "name": self.name,
                    "hostname": self._get_hostname(),
                    "tags": self.tags,
                },
                timeout=10,
            )
            if response.status_code == 200:
                self.agent_id = response.json().get("id")
                print(f"Registered as agent #{self.agent_id}")
                return True
        except requests.RequestException as e:
            print(f"Failed to register: {e}")
        return False

    def _get_hostname(self) -> str:
        """Get the hostname of this machine."""
        import socket

        return socket.gethostname()

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

    def execute_job(self, job: dict) -> int:
        """Execute a job and return exit code."""
        import subprocess

        print(f"Executing job #{job['id']}: {job['label']}")
        print(f"Command: {job['command']}")

        try:
            result = subprocess.run(
                job["command"],
                shell=True,
                capture_output=True,
                text=True,
                timeout=3600,
            )
            exit_code = result.returncode

            self._send_log(job["id"], "stdout", result.stdout)
            if result.stderr:
                self._send_log(job["id"], "stderr", result.stderr)

            return exit_code

        except subprocess.TimeoutExpired:
            self._send_log(job["id"], "stderr", "Job timed out after 1 hour")
            return -1
        except Exception as e:
            self._send_log(job["id"], "stderr", str(e))
            return -1

    def _send_log(self, job_id: int, stream: str, line: str):
        """Send log line to server."""
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

        print(f"Agent {self.name} ready. Polling for jobs...")

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


def main():
    import argparse

    parser = argparse.ArgumentParser(description="CI Engine Agent")
    parser.add_argument("--server", default="http://localhost:8000", help="Server URL")
    parser.add_argument("--name", required=True, help="Agent name")
    parser.add_argument("--tags", nargs="*", default=[], help="Agent tags")

    args = parser.parse_args()

    agent = Agent(args.server, args.name, args.tags)
    agent.run()


if __name__ == "__main__":
    main()
