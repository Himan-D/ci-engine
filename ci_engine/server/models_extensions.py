# SPDX-License-Identifier: MIT
# CI Engine — Extended DB models for advanced features
#
# Models added here (each in its own section):
#   • AgentToken        — scoped per-agent capability token (Feature 10)
#   • EnvironmentApproval — manual approval gate for protected envs (Feature 8)
#   • TestRun           — individual test-case results (Feature 7)
#   • FlakynessRecord   — computed flakiness score per test (Feature 7)
#   • BuildMetrics      — materialized build analytics (Feature 9)
#   • RepositoryMetrics — per-repo daily aggregate (Feature 9)
#
# All models share the same Base from models.py so init_db() / create_all()
# picks them up automatically.

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from ci_engine.server.models import Base


# ---------------------------------------------------------------------------
# Feature 10 — Agent Token (capability-scoped)
# ---------------------------------------------------------------------------

class AgentToken(Base):
    """Scoped API token issued to an agent on registration.

    The ``allowed_endpoints`` column stores a JSON list of fnmatch patterns,
    e.g. ``["/api/jobs/*/claim", "/api/agents/*/heartbeat"]``.
    Only requests whose path matches one of these patterns are allowed.
    """

    __tablename__ = "agent_tokens"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    token_hash = Column(String(256), unique=True, nullable=False)
    allowed_endpoints = Column(Text, nullable=False)  # JSON list of fnmatch patterns
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)
    revoked = Column(Boolean, default=False)
    last_used = Column(DateTime, nullable=True)

    def get_allowed_endpoints(self) -> list[str]:
        try:
            return json.loads(self.allowed_endpoints)
        except Exception:
            return []


# Default endpoint patterns allowed for agent tokens
AGENT_ALLOWED_ENDPOINTS: list[str] = [
    "/api/jobs/*/claim",
    "/api/jobs/*/start",
    "/api/jobs/*/complete",
    "/api/jobs/*/logs",
    "/api/jobs/*/log",
    "/api/jobs/*",          # GET job details for cancellation check
    "/api/builds/*",        # GET build details
    "/api/agents/*/heartbeat",
    "/api/agents/register",
    "/health",
    "/health/deep",
]


# ---------------------------------------------------------------------------
# Feature 8 — Environment Protection
# ---------------------------------------------------------------------------

class EnvironmentApproval(Base):
    """Manual approval record for a protected environment deployment.

    When a job targets a protected environment (``requires_approval=True``),
    the job is created in BLOCKED state and an ``EnvironmentApproval`` is
    inserted.  The job unblocks only after this record reaches APPROVED.
    """

    __tablename__ = "environment_approvals"

    id = Column(Integer, primary_key=True)
    build_id = Column(Integer, ForeignKey("builds.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, unique=True)
    environment_name = Column(String(100), nullable=False)
    requested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(100), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejected_by = Column(String(100), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    # pending / approved / rejected / expired
    status = Column(String(20), default="pending")
    expires_at = Column(DateTime, nullable=True)


# Pydantic
class EnvironmentApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    build_id: int
    job_id: int
    environment_name: str
    requested_at: datetime
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejection_reason: Optional[str] = None
    status: str
    expires_at: Optional[datetime] = None


class ApproveRequest(BaseModel):
    approved_by: str
    comment: Optional[str] = None


class RejectRequest(BaseModel):
    rejected_by: str
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Feature 7 — Test Result Ingestion
# ---------------------------------------------------------------------------

class TestRun(Base):
    """One test-case result from a single job execution."""

    __tablename__ = "test_runs"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    build_id = Column(Integer, ForeignKey("builds.id"), nullable=False, index=True)
    repository = Column(String(500), nullable=True, index=True)
    test_name = Column(String(500), nullable=False)
    test_suite = Column(String(500), nullable=True)
    # passed / failed / skipped / errored
    status = Column(String(20), nullable=False)
    duration_ms = Column(Float, nullable=True)
    failure_message = Column(Text, nullable=True)
    failure_type = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class FlakynessRecord(Base):
    """Computed flakiness score per test (refreshed by background task)."""

    __tablename__ = "flakiness_records"
    __table_args__ = (UniqueConstraint("repository", "test_suite", "test_name"),)

    id = Column(Integer, primary_key=True)
    repository = Column(String(500), nullable=True)
    test_suite = Column(String(500), nullable=True)
    test_name = Column(String(500), nullable=False)
    total_runs = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    pass_count = Column(Integer, default=0)
    # 0.0 = never fails, 1.0 = always fails; flaky = between 0.1 and 0.9
    flakiness_score = Column(Float, default=0.0)
    quarantined = Column(Boolean, default=False)
    first_seen = Column(DateTime, nullable=True)
    last_seen = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# Pydantic
class TestRunCreate(BaseModel):
    test_name: str
    test_suite: Optional[str] = None
    status: str  # passed / failed / skipped / errored
    duration_ms: Optional[float] = None
    failure_message: Optional[str] = None
    failure_type: Optional[str] = None


class TestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    build_id: int
    repository: Optional[str]
    test_name: str
    test_suite: Optional[str]
    status: str
    duration_ms: Optional[float]
    failure_message: Optional[str]
    created_at: datetime


class FlakynessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repository: Optional[str]
    test_suite: Optional[str]
    test_name: str
    total_runs: int
    failure_count: int
    pass_count: int
    flakiness_score: float
    quarantined: bool
    last_seen: Optional[datetime]


# ---------------------------------------------------------------------------
# Feature 9 — Build Analytics
# ---------------------------------------------------------------------------

class BuildMetrics(Base):
    """Materialized metrics for a single build (written after completion)."""

    __tablename__ = "build_metrics"
    __table_args__ = (UniqueConstraint("build_id"),)

    id = Column(Integer, primary_key=True)
    build_id = Column(Integer, ForeignKey("builds.id"), nullable=False, index=True)
    repository = Column(String(500), nullable=True, index=True)
    branch = Column(String(100), nullable=True)
    status = Column(String(20), nullable=True)
    # Time from build.created_at → first job.started_at (ms)
    queue_wait_ms = Column(Float, nullable=True)
    # Time from build.created_at → build.finished_at (ms)
    total_duration_ms = Column(Float, nullable=True)
    job_count = Column(Integer, default=0)
    failed_job_count = Column(Integer, default=0)
    # Sum of each job's duration (ms); measures agent resource consumption
    agent_minutes_consumed = Column(Float, default=0.0)
    # True if any job was retried due to flakiness (non-AI retry)
    is_flaky_build = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RepositoryMetrics(Base):
    """Aggregated daily metrics per repository."""

    __tablename__ = "repository_metrics"
    __table_args__ = (UniqueConstraint("repository", "date"),)

    id = Column(Integer, primary_key=True)
    repository = Column(String(500), nullable=False, index=True)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    total_builds = Column(Integer, default=0)
    passed_builds = Column(Integer, default=0)
    failed_builds = Column(Integer, default=0)
    avg_duration_ms = Column(Float, nullable=True)
    p95_duration_ms = Column(Float, nullable=True)
    total_agent_minutes = Column(Float, default=0.0)
    # Mean time to recovery (ms): avg time from failure → next success
    mttr_ms = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# Pydantic
class BuildMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    build_id: int
    repository: Optional[str]
    branch: Optional[str]
    status: Optional[str]
    queue_wait_ms: Optional[float]
    total_duration_ms: Optional[float]
    job_count: int
    failed_job_count: int
    agent_minutes_consumed: float
    is_flaky_build: bool
    created_at: datetime


class RepositoryMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    repository: str
    date: str
    total_builds: int
    passed_builds: int
    failed_builds: int
    avg_duration_ms: Optional[float]
    p95_duration_ms: Optional[float]
    total_agent_minutes: float
    mttr_ms: Optional[float]
