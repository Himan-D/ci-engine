# SPDX-License-Identifier: MIT
# CI Engine - Auto-scaling service

import os
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from ci_engine.server.models import Agent, AgentStatus, Job, JobStatus, Build, BuildStatus


class ScalingConfig:
    """Configuration for auto-scaling."""

    MIN_AGENTS = int(os.environ.get("CI_ENGINE_MIN_AGENTS", "1"))
    MAX_AGENTS = int(os.environ.get("CI_ENGINE_MAX_AGENTS", "10"))

    SCALE_UP_THRESHOLD = int(os.environ.get("CI_ENGINE_SCALE_UP_THRESHOLD", "3"))
    SCALE_DOWN_THRESHOLD = int(os.environ.get("CI_ENGINE_SCALE_DOWN_THRESHOLD", "0"))

    SCALE_UP_COOLDOWN_SECONDS = int(os.environ.get("CI_ENGINE_SCALE_UP_COOLDOWN", "60"))
    SCALE_DOWN_COOLDOWN_SECONDS = int(os.environ.get("CI_ENGINE_SCALE_DOWN_COOLDOWN", "300"))

    JOB_QUEUE_THRESHOLD = int(os.environ.get("CI_ENGINE_JOB_QUEUE_THRESHOLD", "5"))


class ScalingTrigger:
    """Represents a scaling action that should be taken."""

    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    NO_CHANGE = "no_change"

    def __init__(self, action: str, reason: str, priority: int = 0):
        self.action = action
        self.reason = reason
        self.priority = priority
        self.timestamp = datetime.utcnow()


class AutoScaler:
    """Auto-scaling service for CI agents."""

    def __init__(self, db: Session):
        self.db = db
        self.config = ScalingConfig()
        self.last_scale_up: Optional[datetime] = None
        self.last_scale_down: Optional[datetime] = None

    def get_current_state(self) -> dict:
        """Get current agent and job state."""
        total_agents = self.db.query(Agent).count()
        idle_agents = self.db.query(Agent).filter(Agent.status == AgentStatus.IDLE).count()
        busy_agents = self.db.query(Agent).filter(Agent.status == AgentStatus.BUSY).count()
        offline_agents = self.db.query(Agent).filter(Agent.status == AgentStatus.OFFLINE).count()

        pending_jobs = self.db.query(Job).filter(Job.status == JobStatus.PENDING).count()
        running_jobs = self.db.query(Job).filter(Job.status == JobStatus.RUNNING).count()

        builds_running = self.db.query(Build).filter(Build.status == BuildStatus.RUNNING).count()

        return {
            "agents": {
                "total": total_agents,
                "idle": idle_agents,
                "busy": busy_agents,
                "offline": offline_agents,
            },
            "jobs": {
                "pending": pending_jobs,
                "running": running_jobs,
            },
            "builds": {
                "running": builds_running,
            },
        }

    def evaluate_scale_up(self, state: dict) -> bool:
        """Evaluate if we should scale up."""
        pending_jobs = state["jobs"]["pending"]
        idle_agents = state["agents"]["idle"]

        if self.last_scale_up:
            cooldown = (datetime.utcnow() - self.last_scale_up).total_seconds()
            if cooldown < self.config.SCALE_UP_COOLDOWN_SECONDS:
                return False

        if pending_jobs >= self.config.SCALE_UP_THRESHOLD and idle_agents == 0:
            return True

        if pending_jobs > self.config.JOB_QUEUE_THRESHOLD and idle_agents < 2:
            return True

        return False

    def evaluate_scale_down(self, state: dict) -> bool:
        """Evaluate if we should scale down."""
        pending_jobs = state["jobs"]["pending"]
        busy_agents = state["agents"]["busy"]
        running_jobs = state["jobs"]["running"]

        if self.last_scale_down:
            cooldown = (datetime.utcnow() - self.last_scale_down).total_seconds()
            if cooldown < self.config.SCALE_DOWN_COOLDOWN_SECONDS:
                return False

        if busy_agents == 0 and pending_jobs == 0 and running_jobs == 0:
            return True

        return False

    def evaluate(self) -> ScalingTrigger:
        """Evaluate the current state and return a scaling decision."""
        state = self.get_current_state()

        total_agents = state["agents"]["total"]

        if total_agents < self.config.MIN_AGENTS:
            return ScalingTrigger(
                ScalingTrigger.SCALE_UP,
                f"Below minimum agents ({total_agents} < {self.config.MIN_AGENTS})",
                priority=100,
            )

        if total_agents > self.config.MAX_AGENTS:
            return ScalingTrigger(
                ScalingTrigger.SCALE_DOWN,
                f"Above maximum agents ({total_agents} > {self.config.MAX_AGENTS})",
                priority=100,
            )

        if self.evaluate_scale_up(state):
            self.last_scale_up = datetime.utcnow()
            return ScalingTrigger(
                ScalingTrigger.SCALE_UP,
                f"High job queue ({state['jobs']['pending']} pending jobs, {state['agents']['idle']} idle agents)",
                priority=50,
            )

        if self.evaluate_scale_down(state):
            self.last_scale_down = datetime.utcnow()
            return ScalingTrigger(
                ScalingTrigger.SCALE_DOWN,
                f"No active jobs ({state['jobs']['pending']} pending, {state['jobs']['running']} running)",
                priority=10,
            )

        return ScalingTrigger(
            ScalingTrigger.NO_CHANGE,
            "Agent count is optimal",
            priority=0,
        )

    def get_recommendation(self) -> dict:
        """Get scaling recommendation without executing."""
        state = self.get_current_state()
        trigger = self.evaluate()

        return {
            "current_state": state,
            "recommendation": trigger.action,
            "reason": trigger.reason,
            "config": {
                "min_agents": self.config.MIN_AGENTS,
                "max_agents": self.config.MAX_AGENTS,
                "scale_up_threshold": self.config.SCALE_UP_THRESHOLD,
                "scale_down_threshold": self.config.SCALE_DOWN_THRESHOLD,
                "job_queue_threshold": self.config.JOB_QUEUE_THRESHOLD,
            },
            "last_scale_up": self.last_scale_up.isoformat() if self.last_scale_up else None,
            "last_scale_down": self.last_scale_down.isoformat() if self.last_scale_down else None,
        }


def check_and_trigger_scaling(db: Session) -> dict:
    """Check current state and return scaling recommendation."""
    scaler = AutoScaler(db)
    return scaler.get_recommendation()
