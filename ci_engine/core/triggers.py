# SPDX-License-Identifier: MIT
# CI Engine - Pipeline Triggers (Scheduled Builds)

import croniter
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from pydantic import BaseModel, ConfigDict

from ci_engine.server.models import Base


class TriggerStatus(str):
    """Trigger status."""

    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class PipelineTrigger(Base):
    """Pipeline trigger model."""

    __tablename__ = "pipeline_triggers"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    pipeline = Column(Text, nullable=False)
    branch = Column(String(100), default="main")
    cron_expression = Column(String(100), nullable=False)
    status = Column(String(20), default=TriggerStatus.ACTIVE)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by = Column(Integer, nullable=True)
    enabled = Column(Boolean, default=True)


class PipelineTriggerCreate(BaseModel):
    """Schema for creating pipeline trigger."""

    name: str
    pipeline: str
    branch: str = "main"
    cron_expression: str
    enabled: bool = True


class PipelineTriggerResponse(BaseModel):
    """Schema for pipeline trigger response."""

    id: int
    name: str
    pipeline: str
    branch: str
    cron_expression: str
    status: str
    last_run: Optional[datetime]
    next_run: Optional[datetime]
    created_at: datetime
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


class TriggerScheduler:
    """Scheduler for pipeline triggers."""

    def __init__(self):
        self._triggers = {}

    def add_trigger(self, trigger_id: int, cron_expr: str) -> bool:
        """Add a trigger to the scheduler."""
        try:
            cron = croniter.croniter(cron_expr)
            self._triggers[trigger_id] = cron
            return True
        except Exception:
            return False

    def remove_trigger(self, trigger_id: int):
        """Remove a trigger from the scheduler."""
        self._triggers.pop(trigger_id, None)

    def get_next_run(self, trigger_id: int) -> Optional[datetime]:
        """Get next run time for a trigger."""
        cron = self._triggers.get(trigger_id)
        if cron:
            return cron.get_next(datetime)
        return None

    def should_run(self, trigger_id: int, current_time: datetime = None) -> bool:
        """Check if trigger should run now."""
        current_time = current_time or datetime.now(timezone.utc)
        cron = self._triggers.get(trigger_id)

        if not cron:
            return False

        next_run = cron.get_next(datetime)
        return next_run <= current_time + timedelta(seconds=1)


scheduler = TriggerScheduler()


def create_trigger(
    name: str,
    pipeline: str,
    branch: str,
    cron_expression: str,
    db,
    created_by: Optional[int] = None,
    enabled: bool = True,
) -> PipelineTrigger:
    """Create a new pipeline trigger."""
    trigger = PipelineTrigger(
        name=name,
        pipeline=pipeline,
        branch=branch,
        cron_expression=cron_expression,
        status=TriggerStatus.ACTIVE if enabled else TriggerStatus.PAUSED,
        created_by=created_by,
        enabled=enabled,
    )

    if enabled:
        scheduler.add_trigger(trigger.id, cron_expression)
        trigger.next_run = scheduler.get_next_run(trigger.id)

    db.add(trigger)
    db.commit()
    db.refresh(trigger)

    return trigger


def update_trigger(
    trigger_id: int,
    db,
    name: Optional[str] = None,
    pipeline: Optional[str] = None,
    branch: Optional[str] = None,
    cron_expression: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Optional[PipelineTrigger]:
    """Update an existing pipeline trigger."""
    trigger = db.query(PipelineTrigger).filter(PipelineTrigger.id == trigger_id).first()
    if not trigger:
        return None

    if name is not None:
        trigger.name = name
    if pipeline is not None:
        trigger.pipeline = pipeline
    if branch is not None:
        trigger.branch = branch
    if cron_expression is not None:
        trigger.cron_expression = cron_expression
        if trigger.enabled:
            scheduler.add_trigger(trigger.id, cron_expression)
            trigger.next_run = scheduler.get_next_run(trigger.id)
    if enabled is not None:
        trigger.enabled = enabled
        trigger.status = TriggerStatus.ACTIVE if enabled else TriggerStatus.PAUSED
        if enabled:
            scheduler.add_trigger(trigger.id, trigger.cron_expression)
            trigger.next_run = scheduler.get_next_run(trigger.id)
        else:
            scheduler.remove_trigger(trigger.id)
            trigger.next_run = None

    db.commit()
    db.refresh(trigger)
    return trigger


def delete_trigger(trigger_id: int, db) -> bool:
    """Delete a pipeline trigger."""
    trigger = db.query(PipelineTrigger).filter(PipelineTrigger.id == trigger_id).first()
    if not trigger:
        return False

    scheduler.remove_trigger(trigger_id)
    db.delete(trigger)
    db.commit()
    return True


def get_pending_triggers(db) -> list[PipelineTrigger]:
    """Get all triggers that should run now."""
    triggers = db.query(PipelineTrigger).filter(PipelineTrigger.enabled).all()

    pending = []
    for trigger in triggers:
        if trigger.id not in scheduler._triggers:
            scheduler.add_trigger(trigger.id, trigger.cron_expression)
            trigger.next_run = scheduler.get_next_run(trigger.id)
            db.commit()

        if scheduler.should_run(trigger.id):
            pending.append(trigger)

    return pending


def check_and_run_triggers(db):
    """Check and execute pending triggers."""
    import logging

    logger = logging.getLogger(__name__)
    pending = get_pending_triggers(db)

    for trigger in pending:
        try:
            from ci_engine.server.models import Build, BuildStatus
            from ci_engine.core.pipeline import parse_pipeline

            build = Build(
                pipeline=trigger.pipeline,
                branch=trigger.branch,
                status=BuildStatus.PENDING,
            )
            db.add(build)
            db.commit()
            db.refresh(build)

            steps = parse_pipeline(trigger.pipeline)
            from ci_engine.server.models import Job, JobStatus

            for i, step in enumerate(steps):
                job = Job(
                    build_id=build.id,
                    step_index=i,
                    label=step.get("label", f"Step {i}"),
                    command=step.get("command", ""),
                    status=JobStatus.PENDING,
                )
                db.add(job)

            trigger.last_run = datetime.now(timezone.utc)
            trigger.next_run = scheduler.get_next_run(trigger.id)
            db.commit()

        except Exception as e:
            logger.warning(f"Failed to run trigger {trigger.id}: {e}")

    return len(pending)
