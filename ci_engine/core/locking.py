# SPDX-License-Identifier: MIT
# CI Engine — Atomic job-claiming with SELECT FOR UPDATE SKIP LOCKED
#
# Problem solved: without a row-level lock, N agents polling simultaneously
# can all observe a PENDING job and claim it, leading to double-execution.
#
# Strategy:
#   • PostgreSQL → SELECT … FOR UPDATE SKIP LOCKED (native, zero overhead)
#   • SQLite     → BEGIN EXCLUSIVE transaction (application-level serialisation)
#
# The public API is a single function: claim_job_atomic(db, job_id, agent_id).
# Returns True when the claim succeeds, False when another agent got there first.

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ci_engine.server.models import Agent, AgentStatus, Job, JobStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dialect detection (cached at module load time)
# ---------------------------------------------------------------------------

_IS_POSTGRES: Optional[bool] = None


def _is_postgres(db: Session) -> bool:
    global _IS_POSTGRES
    if _IS_POSTGRES is None:
        dialect = db.bind.dialect.name if db.bind else ""  # type: ignore[union-attr]
        _IS_POSTGRES = dialect.startswith("postgresql")
    return _IS_POSTGRES


# ---------------------------------------------------------------------------
# Core: atomic claim
# ---------------------------------------------------------------------------

def claim_job_atomic(db: Session, job_id: int, agent_id: int) -> bool:
    """Atomically claim *job_id* for *agent_id*.

    Returns True when the claim succeeded; False when the job was already
    taken by another agent (race condition resolved — caller should move on).

    The caller must NOT wrap this in an outer transaction that holds other
    row-locks, to avoid deadlocks.
    """
    now = datetime.now(timezone.utc)

    try:
        if _is_postgres(db):
            return _claim_postgres(db, job_id, agent_id, now)
        else:
            return _claim_sqlite(db, job_id, agent_id, now)
    except Exception as exc:
        logger.warning("claim_job_atomic failed for job=%s agent=%s: %s", job_id, agent_id, exc)
        db.rollback()
        return False


def _claim_postgres(db: Session, job_id: int, agent_id: int, now: datetime) -> bool:
    """PostgreSQL path: SELECT … FOR UPDATE SKIP LOCKED."""
    # Raw SQL for the lock; SQLAlchemy ORM doesn't expose SKIP LOCKED cleanly
    # via the standard with_for_update() on individual row queries pre-2.0.
    result = db.execute(
        text(
            "SELECT id, status FROM jobs "
            "WHERE id = :job_id AND status = 'pending' "
            "FOR UPDATE SKIP LOCKED"
        ),
        {"job_id": job_id},
    ).fetchone()

    if result is None:
        # Another agent grabbed the lock or the job is no longer pending
        db.rollback()
        return False

    # Safe to update — we hold the exclusive row lock
    db.execute(
        text(
            "UPDATE jobs SET status='assigned', agent_id=:agent_id, claimed_at=:now "
            "WHERE id=:job_id"
        ),
        {"agent_id": agent_id, "job_id": job_id, "now": now},
    )
    db.execute(
        text("UPDATE agents SET status='busy' WHERE id=:agent_id"),
        {"agent_id": agent_id},
    )
    db.commit()
    return True


def _claim_sqlite(db: Session, job_id: int, agent_id: int, now: datetime) -> bool:
    """SQLite path: BEGIN EXCLUSIVE + ORM update.

    SQLite does not support SELECT … FOR UPDATE.  Instead we open an
    exclusive transaction which serialises all writers for the duration.
    WAL mode is already enabled in db.py so readers are unaffected.
    """
    try:
        # Escalate to an exclusive write-lock for the rest of this transaction.
        # SQLite WAL: readers are never blocked; other writers queue here.
        db.execute(text("BEGIN EXCLUSIVE"))
    except Exception:
        # Already inside a transaction; fall back to ORM-level check-then-set
        # (less safe but functionally correct for low-concurrency dev setups).
        pass

    job = db.query(Job).filter(Job.id == job_id, Job.status == JobStatus.PENDING).first()
    if job is None:
        db.rollback()
        return False

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        db.rollback()
        return False

    job.status = JobStatus.ASSIGNED
    job.agent_id = agent_id
    job.claimed_at = now  # type: ignore[attr-defined]
    agent.status = AgentStatus.BUSY
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Stale-claim cleanup helper (called by background reaper)
# ---------------------------------------------------------------------------

STALE_CLAIM_SECONDS = int(60)  # job assigned but not started within this window → re-queue


def reset_stale_claims(db: Session) -> int:
    """Re-queue jobs that were claimed but never started.

    An agent that crashed between claim and start leaves a job in ASSIGNED
    status with no activity.  After *STALE_CLAIM_SECONDS* we reset it to
    PENDING so another agent can pick it up.

    Returns the number of jobs reset.
    """

    # Use raw SQL for DB-agnostic timestamp arithmetic
    if _is_postgres(db):
        cutoff_expr = text(
            "claimed_at < NOW() - INTERVAL ':sec seconds'"
        )
        # Unfortunately interval parameter binding is tricky; use literal
        rows = db.execute(
            text(
                f"UPDATE jobs SET status='pending', agent_id=NULL, claimed_at=NULL "
                f"WHERE status='assigned' "
                f"AND claimed_at < NOW() - INTERVAL '{STALE_CLAIM_SECONDS} seconds' "
                f"RETURNING id"
            )
        ).fetchall()
        db.commit()
        return len(rows)
    else:
        # SQLite: use strftime arithmetic
        rows = db.execute(
            text(
                f"UPDATE jobs SET status='pending', agent_id=NULL, claimed_at=NULL "
                f"WHERE status='assigned' "
                f"AND claimed_at < datetime('now', '-{STALE_CLAIM_SECONDS} seconds')"
            )
        ).rowcount
        db.commit()
        return rows
