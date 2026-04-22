# SPDX-License-Identifier: MIT
# CI Engine - Job scheduler

from typing import Optional
from datetime import datetime
from ci_engine.server.models import (
    Job,
    Agent,
    AgentSkill,
    JobStatus,
    AgentStatus,
    Build,
    BuildStatus,
)


class Scheduler:
    """Scheduler for distributing jobs to agents."""

    @staticmethod
    def find_available_agent(db, required_tags: Optional[str] = None) -> Optional[Agent]:
        """Find an available agent that matches the required tags."""
        query = db.query(Agent).filter(Agent.status == AgentStatus.IDLE)

        if required_tags:
            tags_list = [t.strip() for t in required_tags.split(",")]
            for tag in tags_list:
                if "*" in tag:
                    pattern = tag.replace("*", ".*")
                    agent_tags = (
                        db.query(Agent)
                        .filter(Agent.status == AgentStatus.IDLE, Agent.tags.regexp_match(pattern))
                        .first()
                    )
                    if agent_tags:
                        return agent_tags
                else:
                    query = query.filter(Agent.tags.contains(tag))

        return query.first()

    @staticmethod
    def find_agent_with_skills(db, required_skills: list[str]) -> Optional[Agent]:
        """Find an available agent that has all required skills."""
        if not required_skills:
            return Scheduler.find_available_agent(db, None)

        skill_requirements = []
        for s in required_skills:
            if ":" in s:
                name, level = s.split(":")
                skill_requirements.append((name.strip(), int(level.strip())))
            else:
                skill_requirements.append((s.strip(), 1))

        idle_agents = db.query(Agent).filter(Agent.status == AgentStatus.IDLE).all()

        for agent in idle_agents:
            agent_skills = {s.name: s.level for s in agent.agent_skills if s.enabled}

            matches = True
            for skill_name, min_level in skill_requirements:
                if skill_name not in agent_skills:
                    matches = False
                    break
                if agent_skills[skill_name] < min_level:
                    matches = False
                    break

            if matches:
                return agent

        return None

    @staticmethod
    def find_best_agent(db, job_id: int) -> Optional[Agent]:
        """Find best available agent for a job based on tags and skills."""
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None

        if job.required_skills:
            required_skills_list = [s.strip() for s in job.required_skills.split(",")]
            agent = Scheduler.find_agent_with_skills(db, required_skills_list)
            if agent:
                return agent

        if job.required_tags:
            return Scheduler.find_available_agent(db, job.required_tags)

        return Scheduler.find_available_agent(db, None)

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
        """Get the next pending job ordered by priority (highest first) then step_index."""
        query = db.query(Job).filter(Job.status == JobStatus.PENDING)

        if build_id:
            query = query.filter(Job.build_id == build_id)

        return query.order_by(Job.priority.desc(), Job.step_index).first()

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
