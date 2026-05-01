# SPDX-License-Identifier: MIT
# CI Engine — Background task runner
#
# Runs inside the FastAPI lifespan as asyncio tasks.  Three loops:
#
#   Loop A — Agent Reaper (every 30 s)
#       Mark agents whose last_seen is stale as OFFLINE.
#       Re-queue any jobs that were RUNNING or ASSIGNED on those agents.
#
#   Loop B — Job Timeout Enforcer (every 60 s)
#       Find RUNNING jobs whose (started_at + timeout_seconds) < now.
#       Call Scheduler.handle_job_timeout() → FAILED + optional retry.
#
#   Loop C — Stale Claim Cleaner (every 30 s)
#       Re-queue ASSIGNED jobs that were never started within 60 s.
#       Uses ci_engine.core.locking.reset_stale_claims().
#
#   Loop D — Analytics Materializer (every 5 min)
#       Materialise BuildMetrics for completed builds that lack a record.
#       Refresh FlakynessRecords for recently-updated tests.
#
# Usage (in FastAPI lifespan):
#   runner = BackgroundTaskRunner()
#   runner.start()          # schedules asyncio tasks
#   yield
#   await runner.stop()     # cancels all tasks

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Tunable intervals (seconds)
AGENT_REAPER_INTERVAL = int(30)
JOB_TIMEOUT_INTERVAL  = int(60)
STALE_CLAIM_INTERVAL  = int(30)
ANALYTICS_INTERVAL    = int(300)   # 5 minutes

# How long without a heartbeat before an agent is considered offline
AGENT_OFFLINE_AFTER_SECONDS = int(90)


class BackgroundTaskRunner:
    """Manages the lifecycle of all background asyncio tasks."""

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        """Schedule all background loops. Must be called inside an async context."""
        self._tasks = [
            asyncio.create_task(self._loop_agent_reaper(),    name="agent_reaper"),
            asyncio.create_task(self._loop_job_timeout(),     name="job_timeout"),
            asyncio.create_task(self._loop_stale_claims(),    name="stale_claims"),
            asyncio.create_task(self._loop_analytics(),       name="analytics"),
        ]
        logger.info("BackgroundTaskRunner started (%d tasks)", len(self._tasks))

    async def stop(self) -> None:
        """Cancel all running background tasks gracefully."""
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("BackgroundTaskRunner stopped")

    # ------------------------------------------------------------------
    # Loop A — Agent Reaper
    # ------------------------------------------------------------------

    async def _loop_agent_reaper(self) -> None:
        while True:
            try:
                await asyncio.sleep(AGENT_REAPER_INTERVAL)
                await asyncio.get_event_loop().run_in_executor(None, _run_agent_reaper)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("agent_reaper error: %s", exc)

    # ------------------------------------------------------------------
    # Loop B — Job Timeout Enforcer
    # ------------------------------------------------------------------

    async def _loop_job_timeout(self) -> None:
        while True:
            try:
                await asyncio.sleep(JOB_TIMEOUT_INTERVAL)
                await asyncio.get_event_loop().run_in_executor(None, _run_job_timeout)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("job_timeout error: %s", exc)

    # ------------------------------------------------------------------
    # Loop C — Stale Claim Cleaner
    # ------------------------------------------------------------------

    async def _loop_stale_claims(self) -> None:
        while True:
            try:
                await asyncio.sleep(STALE_CLAIM_INTERVAL)
                await asyncio.get_event_loop().run_in_executor(None, _run_stale_claims)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("stale_claims error: %s", exc)

    # ------------------------------------------------------------------
    # Loop D — Analytics Materializer
    # ------------------------------------------------------------------

    async def _loop_analytics(self) -> None:
        while True:
            try:
                await asyncio.sleep(ANALYTICS_INTERVAL)
                await asyncio.get_event_loop().run_in_executor(None, _run_analytics)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("analytics error: %s", exc)


# ---------------------------------------------------------------------------
# Implementation functions (sync — run in threadpool executor)
# ---------------------------------------------------------------------------

def _run_agent_reaper() -> None:
    """Mark stale agents OFFLINE and re-queue their running jobs."""
    from ci_engine.server.db import SessionLocal
    from ci_engine.server.models import Agent, AgentStatus, Job, JobStatus

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=AGENT_OFFLINE_AFTER_SECONDS)

        stale_agents = (
            db.query(Agent)
            .filter(
                Agent.last_seen < cutoff,
                Agent.status != AgentStatus.OFFLINE,
            )
            .all()
        )

        for agent in stale_agents:
            logger.info("Reaping stale agent %s (last_seen=%s)", agent.name, agent.last_seen)
            agent.status = AgentStatus.OFFLINE

            # Re-queue all RUNNING or ASSIGNED jobs for this agent
            stuck_jobs = (
                db.query(Job)
                .filter(
                    Job.agent_id == agent.id,
                    Job.status.in_([JobStatus.RUNNING, JobStatus.ASSIGNED]),
                )
                .all()
            )
            for job in stuck_jobs:
                logger.warning(
                    "Re-queuing job %s (build=%s) from dead agent %s",
                    job.id, job.build_id, agent.name,
                )
                job.status = JobStatus.PENDING
                job.agent_id = None
                job.started_at = None

        if stale_agents:
            db.commit()

        # Clean up orphaned Docker containers for builds with no running jobs
        _cleanup_orphaned_containers(db)

    except Exception as exc:
        logger.error("_run_agent_reaper: %s", exc)
        db.rollback()
    finally:
        db.close()


def _run_job_timeout() -> None:
    """Fail jobs that exceeded their timeout_seconds budget."""
    from ci_engine.server.db import SessionLocal
    from ci_engine.server.models import Job, JobStatus
    from ci_engine.core.scheduler import Scheduler

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        running_jobs = db.query(Job).filter(Job.status == JobStatus.RUNNING).all()

        for job in running_jobs:
            if job.started_at is None:
                continue
            timeout = job.timeout_seconds or 3600
            # Ensure timezone-aware comparison
            started = job.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if now > started + timedelta(seconds=timeout):
                logger.warning(
                    "Job %s (build=%s label=%s) exceeded timeout (%ss) — marking failed",
                    job.id, job.build_id, job.label, timeout,
                )
                Scheduler.handle_job_timeout(db, job)

    except Exception as exc:
        logger.error("_run_job_timeout: %s", exc)
        db.rollback()
    finally:
        db.close()


def _run_stale_claims() -> None:
    """Re-queue jobs that were claimed but never started (crashed agent)."""
    from ci_engine.server.db import SessionLocal
    from ci_engine.core.locking import reset_stale_claims

    db = SessionLocal()
    try:
        n = reset_stale_claims(db)
        if n:
            logger.info("reset_stale_claims: re-queued %d stale job(s)", n)
    except Exception as exc:
        logger.error("_run_stale_claims: %s", exc)
    finally:
        db.close()


def _run_analytics() -> None:
    """Materialise BuildMetrics for recently-completed builds."""
    from ci_engine.server.db import SessionLocal
    from ci_engine.server.models import Build, BuildStatus
    from ci_engine.core.analytics import materialise_build_metrics, refresh_flakiness

    db = SessionLocal()
    try:
        # Find completed builds missing a BuildMetrics record (last 24 h)
        from ci_engine.server.models_extensions import BuildMetrics
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        completed = (
            db.query(Build)
            .filter(
                Build.status.in_([BuildStatus.PASSED, BuildStatus.FAILED]),
                Build.finished_at >= cutoff,
            )
            .all()
        )
        for build in completed:
            existing = db.query(BuildMetrics).filter(BuildMetrics.build_id == build.id).first()
            if not existing:
                materialise_build_metrics(db, build.id)

        refresh_flakiness(db)

    except Exception as exc:
        logger.error("_run_analytics: %s", exc)
    finally:
        db.close()


def _cleanup_orphaned_containers(db) -> None:
    """Kill Docker containers whose build jobs are no longer active."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=ci-engine-build-", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return

        from ci_engine.server.models import Job, JobStatus

        for container_name in result.stdout.strip().splitlines():
            # Container names: ci-engine-build-{build_id}-{uuid8}
            parts = container_name.split("-")
            if len(parts) < 4:
                continue
            try:
                build_id = int(parts[3])
            except (ValueError, IndexError):
                continue

            # Check if any job for this build is still active
            active = (
                db.query(Job)
                .filter(
                    Job.build_id == build_id,
                    Job.status.in_([JobStatus.RUNNING, JobStatus.ASSIGNED]),
                )
                .count()
            )
            if active == 0:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True, timeout=5,
                )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    except Exception as exc:
        logger.debug("_cleanup_orphaned_containers: %s", exc)
