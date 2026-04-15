# SPDX-License-Identifier: MIT
# CI Engine - Job scheduler

from typing import Optional
from datetime import datetime
from ci_engine.server.models import Job, Agent, JobStatus, AgentStatus, Build, BuildStatus


class Scheduler:
    """Scheduler for distributing jobs to agents."""

    @staticmethod
    def find_available_agent(db, tags: Optional[list[str]] = None) -> Optional[Agent]:
        """Find an available agent that matches the required tags."""
        query = db.query(Agent).filter(Agent.status == AgentStatus.IDLE)

        if tags:
            for tag in tags:
                query = query.filter(Agent.tags.contains(tag))

        return query.first()

    @staticmethod
    def assign_job(db, job_id: int, agent_id: int) -> bool:
        """Assign a job to an agent."""
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or job.status != JobStatus.PENDING:
            return False

        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent or agent.status != AgentStatus.IDLE:
            return False

        job.agent_id = agent_id
        job.status = JobStatus.ASSIGNED
        agent.status = AgentStatus.BUSY
        db.commit()
        return True

    @staticmethod
    def get_next_pending_job(db, build_id: Optional[int] = None) -> Optional[Job]:
        """Get the next pending job."""
        query = db.query(Job).filter(Job.status == JobStatus.PENDING)

        if build_id:
            query = query.filter(Job.build_id == build_id)

        return query.order_by(Job.step_index).first()

    @staticmethod
    def should_retry_job(db, job: Job) -> bool:
        """Check if a failed job should be retried."""
        if job.status != JobStatus.FAILED:
            return False
        if job.retry_count >= job.max_retries:
            return False
        return True

    @staticmethod
    def retry_job(db, job: Job) -> Optional[Job]:
        """Retry a failed job if within retry limits."""
        if not Scheduler.should_retry_job(db, job):
            return None

        job.status = JobStatus.PENDING
        job.retry_count += 1
        job.started_at = None
        job.finished_at = None
        job.exit_code = None
        db.commit()
        return job

    @staticmethod
    def handle_job_timeout(db, job: Job) -> Optional[Job]:
        """Handle job timeout by marking as failed and retrying if possible."""
        if job.status != JobStatus.RUNNING:
            return None

        job.status = JobStatus.FAILED
        job.exit_code = -1
        job.finished_at = datetime.utcnow()

        if job.agent:
            job.agent.status = AgentStatus.IDLE

        db.commit()

        return Scheduler.retry_job(db, job)

    @staticmethod
    def update_build_status(db, build_id: int):
        """Update build status based on all job statuses."""
        jobs = db.query(Job).filter(Job.build_id == build_id).all()

        if not jobs:
            return

        pending = sum(1 for j in jobs if j.status == JobStatus.PENDING)
        running = sum(1 for j in jobs if j.status == JobStatus.RUNNING)
        failed = sum(1 for j in jobs if j.status == JobStatus.FAILED)
        blocked = sum(1 for j in jobs if j.status == JobStatus.BLOCKED)

        build = db.query(Build).filter(Build.id == build_id).first()
        if not build:
            return

        if failed > 0 and pending == 0 and running == 0 and blocked == 0:
            build.status = BuildStatus.FAILED
        elif pending == 0 and running == 0 and blocked == 0:
            build.status = BuildStatus.PASSED

        db.commit()
