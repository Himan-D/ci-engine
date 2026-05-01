# SPDX-License-Identifier: MIT
# CI Engine — Build analytics
#
# Materialises:
#   • BuildMetrics    — per-build queue wait, duration, agent-minutes
#   • RepositoryMetrics — per-repo daily aggregates + MTTR
#   • FlakynessRecord   — per-test flakiness score (refreshed hourly)
#
# These are called by the background task runner (ci_engine/core/background.py)
# and also triggered inline from complete_job() for the just-finished build.

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Flakiness threshold: tests that fail this fraction of the time are quarantined
FLAKINESS_QUARANTINE_THRESHOLD = float(
    __import__("os").environ.get("CI_ENGINE_FLAKINESS_THRESHOLD", "0.15")
)
# Minimum runs before we compute a meaningful flakiness score
MIN_RUNS_FOR_SCORE = 5


# ---------------------------------------------------------------------------
# BuildMetrics
# ---------------------------------------------------------------------------

def materialise_build_metrics(db, build_id: int) -> None:
    """Compute and upsert BuildMetrics for *build_id*."""
    from ci_engine.server.models import Build, Job, JobStatus
    from ci_engine.server.models_extensions import BuildMetrics

    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        return

    jobs = db.query(Job).filter(Job.build_id == build_id).all()

    # Queue wait: build.created_at → first job.started_at
    started_ats = [j.started_at for j in jobs if j.started_at]
    queue_wait_ms: Optional[float] = None
    if started_ats and build.created_at:
        first_start = min(started_ats)
        # Ensure timezone-aware
        build_created = build.created_at
        if build_created.tzinfo is None:
            build_created = build_created.replace(tzinfo=timezone.utc)
        if first_start.tzinfo is None:
            first_start = first_start.replace(tzinfo=timezone.utc)
        diff = (first_start - build_created).total_seconds() * 1000
        queue_wait_ms = max(0.0, diff)

    # Total duration: build.created_at → build.finished_at
    total_duration_ms: Optional[float] = None
    if build.finished_at and build.created_at:
        finished = build.finished_at
        created = build.created_at
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        total_duration_ms = max(0.0, (finished - created).total_seconds() * 1000)

    # Agent-minutes consumed: sum of each job's runtime
    agent_minutes = 0.0
    for job in jobs:
        if job.started_at and job.finished_at:
            s = job.started_at
            f = job.finished_at
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if f.tzinfo is None:
                f = f.replace(tzinfo=timezone.utc)
            agent_minutes += max(0.0, (f - s).total_seconds()) / 60.0

    failed_count = sum(1 for j in jobs if j.status == JobStatus.FAILED)
    is_flaky = any(j.retry_count > 0 for j in jobs)

    existing = db.query(BuildMetrics).filter(BuildMetrics.build_id == build_id).first()
    if existing:
        existing.queue_wait_ms = queue_wait_ms
        existing.total_duration_ms = total_duration_ms
        existing.job_count = len(jobs)
        existing.failed_job_count = failed_count
        existing.agent_minutes_consumed = agent_minutes
        existing.is_flaky_build = is_flaky
        existing.status = build.status.value if build.status else None
    else:
        db.add(BuildMetrics(
            build_id=build_id,
            repository=build.repository,
            branch=build.branch,
            status=build.status.value if build.status else None,
            queue_wait_ms=queue_wait_ms,
            total_duration_ms=total_duration_ms,
            job_count=len(jobs),
            failed_job_count=failed_count,
            agent_minutes_consumed=agent_minutes,
            is_flaky_build=is_flaky,
        ))

    try:
        db.commit()
    except Exception as exc:
        logger.warning("materialise_build_metrics commit failed: %s", exc)
        db.rollback()


# ---------------------------------------------------------------------------
# RepositoryMetrics (daily aggregates)
# ---------------------------------------------------------------------------

def refresh_repository_metrics(db, repository: str, date_str: str) -> None:
    """Recompute the RepositoryMetrics row for *repository* on *date_str* (YYYY-MM-DD)."""
    from ci_engine.server.models_extensions import BuildMetrics, RepositoryMetrics

    rows = (
        db.query(BuildMetrics)
        .filter(
            BuildMetrics.repository == repository,
            BuildMetrics.created_at.like(f"{date_str}%"),
        )
        .all()
    )

    if not rows:
        return

    total = len(rows)
    passed = sum(1 for r in rows if r.status == "passed")
    failed = sum(1 for r in rows if r.status == "failed")
    durations = [r.total_duration_ms for r in rows if r.total_duration_ms is not None]
    avg_dur = statistics.mean(durations) if durations else None
    p95_dur: Optional[float] = None
    if len(durations) >= 2:
        sorted_d = sorted(durations)
        p95_idx = int(len(sorted_d) * 0.95)
        p95_dur = sorted_d[min(p95_idx, len(sorted_d) - 1)]

    agent_minutes = sum(r.agent_minutes_consumed for r in rows)

    # MTTR: average time from a failure row to the next passing row (by created_at)
    mttr_ms = _compute_mttr(rows)

    existing = (
        db.query(RepositoryMetrics)
        .filter(RepositoryMetrics.repository == repository, RepositoryMetrics.date == date_str)
        .first()
    )
    if existing:
        existing.total_builds = total
        existing.passed_builds = passed
        existing.failed_builds = failed
        existing.avg_duration_ms = avg_dur
        existing.p95_duration_ms = p95_dur
        existing.total_agent_minutes = agent_minutes
        existing.mttr_ms = mttr_ms
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(RepositoryMetrics(
            repository=repository,
            date=date_str,
            total_builds=total,
            passed_builds=passed,
            failed_builds=failed,
            avg_duration_ms=avg_dur,
            p95_duration_ms=p95_dur,
            total_agent_minutes=agent_minutes,
            mttr_ms=mttr_ms,
        ))

    try:
        db.commit()
    except Exception as exc:
        logger.warning("refresh_repository_metrics commit failed: %s", exc)
        db.rollback()


def _compute_mttr(rows: list) -> Optional[float]:
    """Mean time to recovery: average (failure → next pass) interval in ms."""
    sorted_rows = sorted(rows, key=lambda r: r.created_at or datetime.min)
    ttrs: list[float] = []
    i = 0
    while i < len(sorted_rows):
        if sorted_rows[i].status == "failed":
            # Find the next passing build
            for j in range(i + 1, len(sorted_rows)):
                if sorted_rows[j].status == "passed":
                    fail_at = sorted_rows[i].created_at
                    pass_at = sorted_rows[j].created_at
                    if fail_at and pass_at:
                        if fail_at.tzinfo is None:
                            fail_at = fail_at.replace(tzinfo=timezone.utc)
                        if pass_at.tzinfo is None:
                            pass_at = pass_at.replace(tzinfo=timezone.utc)
                        ttrs.append((pass_at - fail_at).total_seconds() * 1000)
                    break
        i += 1
    return statistics.mean(ttrs) if ttrs else None


# ---------------------------------------------------------------------------
# Critical path
# ---------------------------------------------------------------------------

def compute_critical_path(db, build_id: int) -> list[dict]:
    """Return the critical path through the job DAG as an ordered list of jobs.

    Each entry: {id, label, started_at, finished_at, duration_ms}
    The critical path is the longest-duration chain from source to sink.
    """
    from ci_engine.server.models import Job

    jobs = db.query(Job).filter(Job.build_id == build_id).all()
    if not jobs:
        return []

    by_label = {j.label: j for j in jobs}

    def duration_ms(j) -> float:
        if j.started_at and j.finished_at:
            s = j.started_at
            f = j.finished_at
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if f.tzinfo is None:
                f = f.replace(tzinfo=timezone.utc)
            return max(0.0, (f - s).total_seconds() * 1000)
        return 0.0

    # Build adjacency: deps_of[label] = list of dependency labels
    deps_of: dict[str, list[str]] = {}
    for j in jobs:
        label = j.label
        deps_raw = j.depends_on or ""
        deps_of[label] = [d.strip() for d in deps_raw.split(",") if d.strip() and d.strip() in by_label]

    # Topological sort (Kahn's)
    in_deg = {j.label: len(deps_of[j.label]) for j in jobs}
    queue = [j.label for j in jobs if in_deg[j.label] == 0]
    topo: list[str] = []
    while queue:
        node = queue.pop(0)
        topo.append(node)
        for j in jobs:
            if node in deps_of[j.label]:
                in_deg[j.label] -= 1
                if in_deg[j.label] == 0:
                    queue.append(j.label)

    # DP: longest path by duration
    longest: dict[str, float] = {j.label: duration_ms(by_label[j.label]) for j in jobs}
    predecessor: dict[str, Optional[str]] = {j.label: None for j in jobs}

    for label in topo:
        for other in jobs:
            if label in deps_of[other.label]:
                candidate = longest[label] + duration_ms(by_label[other.label])
                if candidate > longest[other.label]:
                    longest[other.label] = candidate
                    predecessor[other.label] = label

    # Find sink (max total)
    sink = max(longest, key=lambda lbl: longest[lbl])

    # Trace back the path
    path: list[str] = []
    node: Optional[str] = sink
    while node:
        path.append(node)
        node = predecessor[node]
    path.reverse()

    return [
        {
            "id": by_label[step].id,
            "label": step,
            "started_at": by_label[step].started_at.isoformat() if by_label[step].started_at else None,
            "finished_at": by_label[step].finished_at.isoformat() if by_label[step].finished_at else None,
            "duration_ms": duration_ms(by_label[step]),
        }
        for step in path
        if step in by_label
    ]


# ---------------------------------------------------------------------------
# Flakiness
# ---------------------------------------------------------------------------

def refresh_flakiness(db) -> None:
    """Recompute FlakynessRecord for all tests updated in the last 24 h."""
    from datetime import timedelta
    from ci_engine.server.models_extensions import TestRun, FlakynessRecord

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # Find test (repository, suite, name) tuples with recent activity
    recent = (
        db.query(
            TestRun.repository,
            TestRun.test_suite,
            TestRun.test_name,
        )
        .filter(TestRun.created_at >= cutoff)
        .distinct()
        .all()
    )

    for repo, suite, name in recent:
        runs = (
            db.query(TestRun)
            .filter(
                TestRun.repository == repo,
                TestRun.test_suite == suite,
                TestRun.test_name == name,
            )
            .all()
        )
        total = len(runs)
        passes = sum(1 for r in runs if r.status == "passed")
        failures = sum(1 for r in runs if r.status in ("failed", "errored"))

        if total < MIN_RUNS_FOR_SCORE:
            continue

        # A test that always fails is broken, not flaky.
        # Flaky = inconsistent: some pass, some fail.
        if passes == 0:
            score = 0.0  # consistently broken — not flaky
        else:
            score = failures / total

        quarantine = score >= FLAKINESS_QUARANTINE_THRESHOLD and passes > 0

        existing = (
            db.query(FlakynessRecord)
            .filter(
                FlakynessRecord.repository == repo,
                FlakynessRecord.test_suite == suite,
                FlakynessRecord.test_name == name,
            )
            .first()
        )
        last_run = max((r.created_at for r in runs if r.created_at), default=None)

        if existing:
            existing.total_runs = total
            existing.failure_count = failures
            existing.pass_count = passes
            existing.flakiness_score = score
            existing.quarantined = quarantine
            existing.last_seen = last_run
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(FlakynessRecord(
                repository=repo,
                test_suite=suite,
                test_name=name,
                total_runs=total,
                failure_count=failures,
                pass_count=passes,
                flakiness_score=score,
                quarantined=quarantine,
                first_seen=min((r.created_at for r in runs if r.created_at), default=None),
                last_seen=last_run,
            ))

    try:
        db.commit()
    except Exception as exc:
        logger.warning("refresh_flakiness commit failed: %s", exc)
        db.rollback()
