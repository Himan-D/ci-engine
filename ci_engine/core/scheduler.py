# SPDX-License-Identifier: MIT
# CI Engine - Job scheduler

from typing import Optional
from datetime import datetime, timezone
from ci_engine.server.models import (
    Job,
    Agent,
    JobStatus,
    AgentStatus,
    Build,
    BuildStatus,
)


class Scheduler:
    """Scheduler for distributing jobs to agents."""

    @staticmethod
    def find_available_agent(
        db,
        required_tags: Optional[str] = None,
        queue: Optional[str] = None,
    ) -> Optional[Agent]:
        """Find an available agent that matches the required tags and queue."""
        query = db.query(Agent).filter(Agent.status == AgentStatus.IDLE)

        # Queue routing: if job specifies a queue, only agents on that queue
        if queue and queue != "default":
            queue_col = getattr(Agent, "queue", None)
            if queue_col is not None:
                query = query.filter(
                    (Agent.queue == queue) | (Agent.queue == None) | (Agent.queue == "default")  # noqa: E711
                )

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
        """Find best available agent for a job based on tags, skills, and queue."""
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None

        job_queue = getattr(job, "queue", "default") or "default"

        if job.required_skills:
            required_skills_list = [s.strip() for s in job.required_skills.split(",")]
            agent = Scheduler.find_agent_with_skills(db, required_skills_list)
            if agent:
                return agent

        if job.required_tags:
            return Scheduler.find_available_agent(db, job.required_tags, queue=job_queue)

        return Scheduler.find_available_agent(db, None, queue=job_queue)

    @staticmethod
    def _count_running_in_concurrency_group(db, group: str) -> int:
        """Count RUNNING jobs in a concurrency group across all builds."""
        return (
            db.query(Job)
            .filter(
                Job.concurrency_group == group,
                Job.status == JobStatus.RUNNING,
            )
            .count()
        )

    @staticmethod
    def get_runnable_jobs(db, build_id: int) -> list[Job]:
        """Get jobs that can run — dependencies satisfied and not blocked by concurrency."""
        jobs = db.query(Job).filter(Job.build_id == build_id).all()

        job_by_label = {job.label: job for job in jobs}
        job_by_index = {job.step_index: job for job in jobs}

        runnable = []

        for job in jobs:
            if job.status not in (JobStatus.PENDING, JobStatus.BLOCKED):
                continue

            depends_on = job.depends_on
            if depends_on:
                deps = [d.strip() for d in depends_on.split(",") if d.strip()]
                can_run = True

                for dep in deps:
                    dep_job = None

                    if dep.isdigit():
                        dep_idx = int(dep)
                        dep_job = job_by_index.get(dep_idx)
                    else:
                        dep_job = job_by_label.get(dep)

                    if dep_job is None:
                        continue

                    if dep_job.status not in (JobStatus.PASSED, JobStatus.SKIPPED):
                        can_run = False
                        break

                if not can_run:
                    continue

            # Concurrency group enforcement: skip if the group is at its limit
            cg = getattr(job, "concurrency_group", None)
            cg_limit = getattr(job, "concurrency", None)
            if cg and cg_limit:
                running_in_group = Scheduler._count_running_in_concurrency_group(db, cg)
                if running_in_group >= cg_limit:
                    continue  # leave PENDING; next poll will reconsider

            if job.status == JobStatus.BLOCKED:
                job.status = JobStatus.PENDING
            runnable.append(job)

        runnable.sort(key=lambda j: (-j.priority, j.step_index))
        return runnable

    @staticmethod
    def check_and_update_dependencies(db, build_id: int):
        """Update job statuses based on dependency outcomes.

        For each job that is still pending/blocked:
        - If ALL its dependencies are PASSED or SKIPPED → mark as PENDING (ready to run)
        - If ANY dependency is FAILED → mark as SKIPPED (cascade skip)

        This is called after every job completion so the state machine
        advances correctly without any external orchestrator.
        """
        jobs = db.query(Job).filter(Job.build_id == build_id).all()
        by_label = {j.label: j for j in jobs}
        by_index = {j.step_index: j for j in jobs}

        changed = False
        for job in jobs:
            if job.status not in (JobStatus.PENDING, JobStatus.BLOCKED):
                continue

            deps_raw = job.depends_on
            if not deps_raw:
                continue

            deps = [d.strip() for d in deps_raw.split(",") if d.strip()]
            if not deps:
                continue

            all_done = True
            any_failed = False

            for dep in deps:
                dep_job = by_label.get(dep)
                if dep_job is None and dep.isdigit():
                    dep_job = by_index.get(int(dep))
                if dep_job is None:
                    continue  # unknown dep — treat as satisfied

                # A FAILED dep with continue_on_error=True or soft_fail=True is treated as PASSED
                dep_coe = bool(getattr(dep_job, "continue_on_error", False))
                dep_soft = bool(getattr(dep_job, "soft_fail", False))
                if dep_job.status == JobStatus.FAILED and not dep_coe and not dep_soft:
                    any_failed = True
                    break
                terminal = (
                    JobStatus.PASSED, JobStatus.SKIPPED, JobStatus.FAILED, JobStatus.SOFT_FAILED
                )
                if dep_job.status not in terminal:
                    all_done = False

            if any_failed:
                # Cascade skip — a hard-failed dependency blocks downstream
                job.status = JobStatus.SKIPPED
                job.finished_at = datetime.now(timezone.utc)
                changed = True
            elif all_done:
                # Check if any non-coe dep was skipped — cascade skip those too
                any_skipped = False
                for dep in deps:
                    dep_job = by_label.get(dep)
                    if dep_job is None and dep.isdigit():
                        dep_job = by_index.get(int(dep))
                    dep_coe = bool(getattr(dep_job, "continue_on_error", False)) if dep_job else False
                    if dep_job and dep_job.status == JobStatus.SKIPPED and not dep_coe:
                        any_skipped = True
                        break

                if any_skipped:
                    job.status = JobStatus.SKIPPED
                    job.finished_at = datetime.now(timezone.utc)
                    changed = True
                elif job.status == JobStatus.BLOCKED:
                    # Dependencies all finished — unblock this job
                    job.status = JobStatus.PENDING
                    changed = True

        if changed:
            db.commit()

        Scheduler.update_build_status(db, build_id)

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
        job.finished_at = datetime.now(timezone.utc)

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

        pending  = sum(1 for j in jobs if j.status == JobStatus.PENDING)
        running  = sum(1 for j in jobs if j.status == JobStatus.RUNNING)
        assigned = sum(1 for j in jobs if j.status == JobStatus.ASSIGNED)
        blocked  = sum(1 for j in jobs if j.status == JobStatus.BLOCKED)

        build = db.query(Build).filter(Build.id == build_id).first()
        if not build:
            return

        # Build is still active if any jobs are running/pending/assigned,
        # OR if there are blocked wait nodes still waiting for approval.
        active = pending + running + assigned + blocked

        if active == 0:
            # All jobs terminal: determine pass/fail
            # continue_on_error and soft_fail failures don't fail the build
            hard_failures = sum(
                1 for j in jobs
                if j.status == JobStatus.FAILED
                and not bool(getattr(j, "continue_on_error", False))
                and not bool(getattr(j, "soft_fail", False))
            )
            if hard_failures > 0:
                build.status = BuildStatus.FAILED
            else:
                build.status = BuildStatus.PASSED
        elif build.status == BuildStatus.PENDING:
            build.status = BuildStatus.RUNNING

        db.commit()
