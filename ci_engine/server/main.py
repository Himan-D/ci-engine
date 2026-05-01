# SPDX-License-Identifier: MIT
# CI Engine - FastAPI Server

import os
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from collections import defaultdict

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Request,
)
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import asyncio

from ci_engine.server.db import get_db, init_db, SessionLocal
from ci_engine.server.models import (
    Build,
    BuildStatus,
    BuildCreate,
    BuildResponse,
    Job,
    JobStatus,
    Agent,
    AgentStatus,
    AgentCreate,
    AgentResponse,
    AgentSkill,
    AgentSkillCreate,
    AgentSkillUpdate,
    AgentPool,
    AgentPoolCreate,
    AgentPoolResponse,
    AgentLabel,
    AgentLabelCreate,
    JobLog,
    WebhookConfig,
    WebhookCreate,
    WebhookResponse,
    Artifact,
    ArtifactResponse,
    EnvironmentGroup,
    EnvironmentGroupResponse,
    EnvironmentGroupCreate,
    PipelineTrigger,
    PipelineTriggerResponse,
    PipelineTriggerCreate,
    BuildAnnotation,
    BuildAnnotationCreate,
    BuildAnnotationResponse,
    BuildMetadata,
    BuildMetadataSet,
    BuildMetadataResponse,
)
from ci_engine.core.pipeline import parse_pipeline
from ci_engine.server.dashboard import router as dashboard_router
from ci_engine.server.middleware import AuthenticationMiddleware
from ci_engine.server.auth import AuthService, User, TokenResponse
from pydantic import BaseModel, ConfigDict
from ci_engine.server.middleware import (
    create_access_token,
    create_refresh_token,
    verify_token,
    get_current_user,
    limiter,
)
from ci_engine.server.webhooks import WebhookService
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import UploadFile, File
from ci_engine.core.artifacts import get_artifact_storage
from ci_engine.core.cache import get_cache, compute_cache_key
from ci_engine.server.oidc import OIDCProviderManager, OIDCTokenVerifier, OIDCTokenExchange
from ci_engine.core.audit import AuditEntry, AuditLogResponse, AuditAction
from ci_engine.core.secrets import Secret, SecretCreate, SecretResponse
from ci_engine.server.models_ai import JobAIAnalysis, BuildAISummary


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_event_loop
    _main_event_loop = asyncio.get_running_loop()
    init_db()
    from ci_engine.core.logging import setup_logging

    setup_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        json_format=os.environ.get("LOG_FORMAT", "") == "json",
    )
    try:
        from ci_engine.core.tracing import init_tracing

        init_tracing("ci-engine-server")
    except ImportError:
        pass

    # Start background task loops (agent reaper, job timeout, analytics…)
    from ci_engine.core.background import BackgroundTaskRunner
    _bg_runner = BackgroundTaskRunner()
    _bg_runner.start()

    yield

    await _bg_runner.stop()

    print("Starting graceful shutdown...")
    active_builds = []
    for channel in manager.active_connections.keys():
        if channel.startswith("build:"):
            build_id = channel.split(":")[1]
            active_builds.append(build_id)

    print(f"Broadcasting shutdown to {len(active_builds)} active builds...")

    await manager.broadcast(
        "builds:all",
        {"type": "shutdown", "message": "Server is shutting down"},
    )

    for channel in list(manager.active_connections.keys()):
        connections = list(manager.active_connections[channel])
        for ws in connections:
            try:
                await ws.close(code=1012, reason="Server shutdown")
            except Exception:
                pass

    print("WebSocket connections closed")

    from ci_engine.server.db import engine

    engine.dispose()

    print("Database connections closed. Shutdown complete.")


app = FastAPI(
    title="CI Engine",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware first (outer)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware second (inner) - must be added AFTER CORS for correct order
app.add_middleware(
    AuthenticationMiddleware,
    public_paths=[
        "/",
        "/health",
        "/status",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/auth/login",
        "/api/auth/register",
        "/api/builds",
    ],
)

# Rate limiting
limiter_obj = Limiter(key_func=get_remote_address)

app.state.limiter = limiter_obj


def get_limiter_key(request: Request) -> str:
    """Get rate limit key - use auth header if available."""
    auth = request.headers.get("Authorization")
    if auth:
        return auth
    return get_remote_address(request)


# WebSocket Connection Manager
class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, channel: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[channel].add(websocket)

    def disconnect(self, channel: str, websocket: WebSocket):
        self.active_connections[channel].discard(websocket)

    async def broadcast(self, channel: str, message: dict):
        disconnected = set()
        for connection in self.active_connections[channel]:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        for ws in disconnected:
            self.active_connections[channel].discard(ws)

    def get_count(self, channel: str) -> int:
        return len(self.active_connections[channel])


manager = ConnectionManager()


# WebSocket endpoints for real-time streaming
@app.websocket("/ws/jobs/{job_id}/logs")
async def job_logs_stream(websocket: WebSocket, job_id: int):
    """Stream logs for a specific job in real-time."""
    channel = f"job_logs:{job_id}"
    await manager.connect(channel, websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(channel, websocket)


@app.websocket("/ws/builds/{build_id}")
async def build_updates_stream(websocket: WebSocket, build_id: int):
    """Real-time build progress updates."""
    channel = f"build:{build_id}"
    await manager.connect(channel, websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(channel, websocket)


@app.websocket("/ws/builds")
async def all_builds_stream(websocket: WebSocket):
    """Subscribe to all build updates."""
    channel = "builds:all"
    await manager.connect(channel, websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(channel, websocket)


_main_event_loop: asyncio.AbstractEventLoop | None = None


def _safe_broadcast(coro):
    """Schedule a broadcast coroutine on the main event loop from any thread.

    FastAPI sync endpoints run in worker threads (anyio threadpool).  We
    cannot use asyncio.create_task() from there — it requires a running loop
    in the current thread.  Instead we post to the main loop via
    run_coroutine_threadsafe, which is the correct cross-thread API.
    """
    global _main_event_loop
    if _main_event_loop is None or _main_event_loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(coro, _main_event_loop)
    except Exception:
        pass


async def _generate_build_summary_async(build_id: int):
    """Background coroutine: generate LLM build summary after a build completes."""
    try:
        from ci_engine.core.ai_analyzer import LLMAnalyzer

        analyzer = LLMAnalyzer()
        if not analyzer.is_enabled():
            return

        db = SessionLocal()
        try:
            build = db.query(Build).filter(Build.id == build_id).first()
            if not build:
                return
            jobs = db.query(Job).filter(Job.build_id == build_id).all()
            # Collect ai_fix_applied flags
            job_dicts = []
            for j in jobs:
                analysis = db.query(JobAIAnalysis).filter(JobAIAnalysis.job_id == j.id).first()
                job_dicts.append({
                    "id": j.id,
                    "label": j.label,
                    "command": j.command,
                    "status": j.status.value,
                    "ai_fix_applied": bool(analysis and analysis.fix_applied) if analysis else False,
                })

            result = analyzer.generate_build_summary(
                build_id=build_id,
                branch=build.branch or "unknown",
                status=build.status.value,
                jobs=job_dicts,
            )
            if result:
                existing = db.query(BuildAISummary).filter(BuildAISummary.build_id == build_id).first()
                if existing:
                    existing.overall_health = result.overall_health
                    existing.summary = result.summary
                    existing.what_failed = json.dumps(result.what_failed)
                    existing.what_was_fixed = json.dumps(result.what_was_fixed)
                    existing.recommendations = json.dumps(result.recommendations)
                else:
                    record = BuildAISummary(
                        build_id=build_id,
                        overall_health=result.overall_health,
                        summary=result.summary,
                        what_failed=json.dumps(result.what_failed),
                        what_was_fixed=json.dumps(result.what_was_fixed),
                        recommendations=json.dumps(result.recommendations),
                    )
                    db.add(record)
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("_generate_build_summary_async failed: %s", exc)


def broadcast_job_status(job_id: int, build_id: int, status: str, exit_code: Optional[int] = None):
    """Broadcast job status change to all subscribers."""
    msg = {
        "type": "job_status",
        "job_id": job_id,
        "build_id": build_id,
        "status": status,
        "exit_code": exit_code,
    }
    _safe_broadcast(manager.broadcast(f"build:{build_id}", msg))
    _safe_broadcast(manager.broadcast("builds:all", msg))


def broadcast_build_status(
    build_id: int,
    status: str,
    jobs_total: int,
    jobs_passed: int,
    jobs_failed: int,
    jobs_running: int,
):
    """Broadcast build status change to all subscribers."""
    msg = {
        "type": "build_status",
        "build_id": build_id,
        "status": status,
        "jobs_total": jobs_total,
        "jobs_passed": jobs_passed,
        "jobs_failed": jobs_failed,
        "jobs_running": jobs_running,
    }
    _safe_broadcast(manager.broadcast(f"build:{build_id}", msg))
    _safe_broadcast(manager.broadcast("builds:all", msg))


app.include_router(dashboard_router)


# Build endpoints
@app.post("/api/builds", response_model=BuildResponse)
@limiter.limit("100/minute")
def create_build(request: Request, build_data: BuildCreate, db: Session = Depends(get_db)):
    """Create a new build from a pipeline definition."""
    import json

    build = Build(
        pipeline=build_data.pipeline,
        branch=build_data.branch,
        commit=build_data.commit,
        repository=build_data.repository,
        git_ref=build_data.git_ref,
        clone_depth=build_data.clone_depth,
        status=BuildStatus.PENDING,
    )
    db.add(build)
    db.commit()
    db.refresh(build)

    steps = parse_pipeline(build_data.pipeline)
    import logging as _logging
    _log = _logging.getLogger(__name__)
    _log.info(f"Creating build #{build.id} with {len(steps)} parsed steps")
    for i, step in enumerate(steps):
        env_vars = step.get("env")
        if env_vars and isinstance(env_vars, list):
            env_vars_dict = {}
            for env in env_vars:
                if isinstance(env, str) and "=" in env:
                    key, val = env.split("=", 1)
                    env_vars_dict[key] = val
                elif isinstance(env, dict):
                    env_vars_dict.update(env)
            env_vars = json.dumps(env_vars_dict) if env_vars_dict else None
        elif env_vars and isinstance(env_vars, dict):
            env_vars = json.dumps(env_vars)
        else:
            env_vars = None

        matrix_vars = step.get("matrix_vars")
        skip_condition = step.get("skip_condition")

        # depends_on may be a list from parse_pipeline normalization
        depends_on = step.get("depends_on") or []
        if isinstance(depends_on, list):
            depends_on_str = ",".join(str(d) for d in depends_on) or None
        else:
            depends_on_str = str(depends_on) or None

        # Determine node type — explicit node_type/step_type field, or infer from step structure
        node_type = (
            step.get("node_type")
            or step.get("step_type")
            or "command"
        )
        # Normalize aliases
        if node_type in ("block", "manual", "approval", "gate"):
            node_type = "wait"

        # continue-on-error support (GitHub Actions style key with hyphen or underscore)
        coe = bool(
            step.get("continue_on_error")
            or step.get("continue-on-error", False)
        )

        if skip_condition:
            job_status = JobStatus.SKIPPED
        elif node_type in ("wait", "block") and depends_on_str:
            # Wait nodes with dependencies start BLOCKED — they only unblock when deps pass
            job_status = JobStatus.BLOCKED
        elif node_type in ("wait", "block") and not depends_on_str:
            # Wait node with no dependencies starts BLOCKED immediately (first step gate)
            job_status = JobStatus.BLOCKED
        else:
            job_status = JobStatus.PENDING

        # timeout: prefer explicit timeout field, then timeout-minutes converted to seconds
        timeout_secs = step.get("timeout") or step.get("timeout_seconds") or 3600

        # command: wait/block nodes have no command to execute
        command = step.get("command") or ("" if node_type in ("wait", "block") else "echo done")

        job = Job(
            build_id=build.id,
            step_index=i,
            label=step.get("label", f"Step {i + 1}"),
            command=command,
            status=job_status,
            env_vars=env_vars,
            working_dir=step.get("working_directory"),
            timeout_seconds=int(timeout_secs),
            max_retries=int(step.get("retry", 0)),
            priority=int(step.get("priority", 0)),
            required_tags=step.get("required_tags"),
            required_skills=step.get("required_skills"),
            matrix_vars=json.dumps(matrix_vars) if matrix_vars else None,
            skip_condition=skip_condition,
            depends_on=depends_on_str,
            node_type=node_type,
            continue_on_error=coe,
            # Buildkite parity fields
            soft_fail=bool(step.get("soft_fail", False)),
            concurrency=step.get("concurrency"),
            concurrency_group=step.get("concurrency_group"),
            parallel_group_id=step.get("parallel_group_id"),
            parallel_index=step.get("parallel_index"),
            parallel_total=step.get("parallel_total"),
            queue=step.get("queue", "default"),
        )
        try:
            db.add(job)
            db.flush()  # catch constraint errors per-job, not all at once
        except Exception as e:
            db.rollback()
            _log.error(f"Failed to create job {i} ({step.get('label')}): {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create job: {e}")

    try:
        db.commit()
        db.refresh(build)
    except Exception as e:
        db.rollback()
        _log.error(f"Failed to commit build #{build.id} jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save jobs: {e}")

    return build


@app.get("/api/builds", response_model=list[BuildResponse])
def list_builds(
    limit: int = 50, status: Optional[BuildStatus] = None, db: Session = Depends(get_db)
):
    """List all builds."""
    query = db.query(Build)
    if status:
        query = query.filter(Build.status == status)
    builds = query.order_by(Build.created_at.desc()).limit(limit).all()
    return builds


@app.get("/api/builds/{build_id}", response_model=BuildResponse)
def get_build(build_id: int, db: Session = Depends(get_db)):
    """Get a specific build with its jobs."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    return build


@app.get("/api/builds/{build_id}/jobs", tags=["jobs"])
def get_build_jobs(build_id: int, db: Session = Depends(get_db)):
    """Get all jobs for a build."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    jobs = db.query(Job).filter(Job.build_id == build_id).order_by(Job.step_index).all()

    return [
        {
            "id": job.id,
            "build_id": job.build_id,
            "step_index": job.step_index,
            "label": job.label,
            "command": job.command,
            "status": job.status.value if job.status else None,
            "exit_code": job.exit_code,
            "agent_id": job.agent_id,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
        for job in jobs
    ]


# Agent endpoints
@app.post("/api/agents/register")
def register_agent(agent_data: AgentCreate, db: Session = Depends(get_db)):
    """Register a new build agent. Returns agent details + a scoped agent_token."""
    from ci_engine.server.auth import issue_agent_token

    existing = db.query(Agent).filter(Agent.name == agent_data.name).first()
    if existing:
        existing.status = AgentStatus.IDLE
        existing.last_seen = datetime.now(timezone.utc)
        if agent_data.tags:
            existing.tags = ",".join(agent_data.tags)
        if agent_data.skills:
            existing.skills = ",".join(agent_data.skills)
        db.commit()
        db.refresh(existing)
        # Issue a fresh scoped token on re-registration
        agent_token = issue_agent_token(db, existing.id)
        agent_resp = AgentResponse.model_validate(existing)
        return {**agent_resp.model_dump(), "agent_token": agent_token}

    agent = Agent(
        name=agent_data.name,
        hostname=agent_data.hostname,
        ip_address="0.0.0.0",
        status=AgentStatus.IDLE,
        tags=",".join(agent_data.tags) if agent_data.tags else None,
        skills=",".join(agent_data.skills) if agent_data.skills else None,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    for skill_name in agent_data.skills or []:
        skill = AgentSkill(agent_id=agent.id, name=skill_name, level=1)
        db.add(skill)
    db.commit()

    agent_token = issue_agent_token(db, agent.id)
    agent_resp = AgentResponse.model_validate(agent)
    return {**agent_resp.model_dump(), "agent_token": agent_token}


@app.get("/api/agents", response_model=list[AgentResponse])
def list_agents(db: Session = Depends(get_db)):
    """List all registered agents."""
    return db.query(Agent).all()


@app.get("/api/agents/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: int, db: Session = Depends(get_db)):
    """Get a specific agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@app.get("/api/agents/{agent_id}/metrics")
def get_agent_metrics(agent_id: int, db: Session = Depends(get_db)):
    """Get metrics for a specific agent including CPU, memory, disk, and job stats."""
    import psutil

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    running_jobs = (
        db.query(Job).filter(Job.agent_id == agent_id, Job.status == JobStatus.RUNNING).count()
    )

    completed_jobs = (
        db.query(Job)
        .filter(Job.agent_id == agent_id, Job.status.in_([JobStatus.PASSED, JobStatus.FAILED]))
        .count()
    )

    return {
        "agent_id": agent_id,
        "agent_name": agent.name,
        "status": agent.status.value,
        "system": {
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": memory.percent,
            "memory_used_mb": round(memory.used / (1024 * 1024), 2),
            "memory_available_mb": round(memory.available / (1024 * 1024), 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 2),
        },
        "jobs": {
            "running": running_jobs,
            "completed_total": completed_jobs,
        },
        "last_seen": agent.last_seen.isoformat() if agent.last_seen else None,
    }


@app.get("/api/agents/metrics/summary")
def get_agents_metrics_summary(db: Session = Depends(get_db)):
    """Get summary metrics for all agents."""
    import psutil

    all_agents = db.query(Agent).all()

    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()

    agents_by_status = {
        "idle": 0,
        "busy": 0,
        "offline": 0,
    }
    total_jobs_running = 0
    total_jobs_completed = 0

    for agent in all_agents:
        status_key = agent.status.value.lower()
        if status_key in agents_by_status:
            agents_by_status[status_key] += 1

        running = (
            db.query(Job).filter(Job.agent_id == agent.id, Job.status == JobStatus.RUNNING).count()
        )
        completed = (
            db.query(Job)
            .filter(Job.agent_id == agent.id, Job.status.in_([JobStatus.PASSED, JobStatus.FAILED]))
            .count()
        )
        total_jobs_running += running
        total_jobs_completed += completed

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": {
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": memory.percent,
        },
        "agents": {
            "total": len(all_agents),
            "by_status": agents_by_status,
        },
        "jobs": {
            "running": total_jobs_running,
            "completed_total": total_jobs_completed,
        },
    }


@app.get("/api/scaling/recommendations")
def get_scaling_recommendations(db: Session = Depends(get_db)):
    """Get auto-scaling recommendations based on current state."""
    from ci_engine.core.scaler import check_and_trigger_scaling

    return check_and_trigger_scaling(db)


@app.get("/api/skills")
def get_all_skills():
    """Get all available skill definitions."""
    from ci_engine.core.skills import list_all_skills

    return list_all_skills()


@app.get("/api/skills/categories")
def get_skill_categories():
    """Get all skill categories."""
    from ci_engine.core.skills import SKILL_CATEGORIES

    return [
        {"key": key, "display_name": value["display_name"], "description": value["description"]}
        for key, value in SKILL_CATEGORIES.items()
    ]


@app.get("/api/agents/{agent_id}/skills")
def get_agent_skills(agent_id: int, db: Session = Depends(get_db)):
    """Get all skills for an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return [
        {
            "id": skill.id,
            "name": skill.name,
            "level": skill.level,
            "category": skill.category,
            "version": skill.version,
            "enabled": skill.enabled,
            "description": skill.description,
        }
        for skill in agent.agent_skills
    ]


@app.post("/api/agents/{agent_id}/skills")
def add_agent_skill(agent_id: int, skill_data: AgentSkillCreate, db: Session = Depends(get_db)):
    """Add a skill to an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    existing = (
        db.query(AgentSkill)
        .filter(AgentSkill.agent_id == agent_id, AgentSkill.name == skill_data.name)
        .first()
    )

    if existing:
        existing.level = skill_data.level
        existing.category = skill_data.category or existing.category
        existing.version = skill_data.version or existing.version
        db.commit()
        db.refresh(existing)
        return existing

    skill = AgentSkill(
        agent_id=agent_id,
        name=skill_data.name,
        level=skill_data.level,
        category=skill_data.category,
        version=skill_data.version,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@app.put("/api/agents/{agent_id}/skills/{skill_name}")
def update_agent_skill(
    agent_id: int, skill_name: str, skill_update: AgentSkillUpdate, db: Session = Depends(get_db)
):
    """Update a skill for an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    skill = (
        db.query(AgentSkill)
        .filter(AgentSkill.agent_id == agent_id, AgentSkill.name == skill_name)
        .first()
    )

    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if skill_update.level is not None:
        skill.level = skill_update.level
    if skill_update.enabled is not None:
        skill.enabled = skill_update.enabled
    if skill_update.version is not None:
        skill.version = skill_update.version

    db.commit()
    db.refresh(skill)
    return skill


@app.delete("/api/agents/{agent_id}/skills/{skill_name}")
def delete_agent_skill(agent_id: int, skill_name: str, db: Session = Depends(get_db)):
    """Delete a skill from an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    skill = (
        db.query(AgentSkill)
        .filter(AgentSkill.agent_id == agent_id, AgentSkill.name == skill_name)
        .first()
    )

    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    db.delete(skill)
    db.commit()
    return {"message": "Skill deleted successfully"}


@app.post("/api/agents/{agent_id}/skills/auto-detect")
def auto_detect_agent_skills(agent_id: int, db: Session = Depends(get_db)):
    """Auto-detect and update agent skills."""
    from ci_engine.agent.skills import auto_detect_skills

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    detected = auto_detect_skills()

    for skill_info in detected["skills"]:
        existing = (
            db.query(AgentSkill)
            .filter(AgentSkill.agent_id == agent_id, AgentSkill.name == skill_info["name"])
            .first()
        )

        if existing:
            existing.version = skill_info.get("version")
            existing.category = skill_info.get("category")
        else:
            skill = AgentSkill(
                agent_id=agent_id,
                name=skill_info["name"],
                level=skill_info.get("level", 1),
                category=skill_info.get("category"),
                version=skill_info.get("version"),
                enabled=True,
            )
            db.add(skill)

    db.commit()
    return {
        "message": f"Auto-detected {len(detected['skills'])} skills",
        "detected": detected["summary"],
    }


# Agent Pool endpoints
@app.post("/api/agent-pools", response_model=AgentPoolResponse)
def create_agent_pool(pool_data: AgentPoolCreate, db: Session = Depends(get_db)):
    """Create a new agent pool."""
    existing = db.query(AgentPool).filter(AgentPool.name == pool_data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Pool already exists")

    pool = AgentPool(
        name=pool_data.name,
        description=pool_data.description,
        max_agents=pool_data.max_agents,
        min_agents=pool_data.min_agents,
        scaling_enabled=pool_data.scaling_enabled,
    )
    db.add(pool)
    db.commit()
    db.refresh(pool)
    return pool


@app.get("/api/agent-pools", response_model=list[AgentPoolResponse])
def list_agent_pools(db: Session = Depends(get_db)):
    """List all agent pools."""
    pools = db.query(AgentPool).all()
    result = []
    for pool in pools:
        agent_count = db.query(Agent).filter(Agent.pool_id == pool.id).count()
        response = AgentPoolResponse(
            id=pool.id,
            name=pool.name,
            description=pool.description,
            max_agents=pool.max_agents,
            min_agents=pool.min_agents,
            scaling_enabled=pool.scaling_enabled,
            agent_count=agent_count,
        )
        result.append(response)
    return result


@app.get("/api/agent-pools/{pool_id}", response_model=AgentPoolResponse)
def get_agent_pool(pool_id: int, db: Session = Depends(get_db)):
    """Get a specific agent pool."""
    pool = db.query(AgentPool).filter(AgentPool.id == pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")

    agent_count = db.query(Agent).filter(Agent.pool_id == pool.id).count()
    return AgentPoolResponse(
        id=pool.id,
        name=pool.name,
        description=pool.description,
        max_agents=pool.max_agents,
        min_agents=pool.min_agents,
        scaling_enabled=pool.scaling_enabled,
        agent_count=agent_count,
    )


@app.delete("/api/agent-pools/{pool_id}")
def delete_agent_pool(pool_id: int, db: Session = Depends(get_db)):
    """Delete an agent pool."""
    pool = db.query(AgentPool).filter(AgentPool.id == pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")

    db.query(Agent).filter(Agent.pool_id == pool_id).update({Agent.pool_id: None})
    db.delete(pool)
    db.commit()
    return {"message": "Pool deleted"}


# Agent Labels endpoints
@app.get("/api/agents/{agent_id}/labels")
def get_agent_labels(agent_id: int, db: Session = Depends(get_db)):
    """Get all labels for an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    labels = db.query(AgentLabel).filter(AgentLabel.agent_id == agent_id).all()
    return [{"id": label.id, "key": label.key, "value": label.value} for label in labels]


@app.post("/api/agents/{agent_id}/labels")
def add_agent_label(agent_id: int, label: AgentLabelCreate, db: Session = Depends(get_db)):
    """Add a label to an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    existing = (
        db.query(AgentLabel)
        .filter(AgentLabel.agent_id == agent_id, AgentLabel.key == label.key)
        .first()
    )

    if existing:
        existing.value = label.value
        db.commit()
        return existing

    new_label = AgentLabel(agent_id=agent_id, key=label.key, value=label.value)
    db.add(new_label)
    db.commit()
    db.refresh(new_label)
    return new_label


@app.delete("/api/agents/{agent_id}/labels/{label_key}")
def delete_agent_label(agent_id: int, label_key: str, db: Session = Depends(get_db)):
    """Delete a label from an agent."""

    label = (
        db.query(AgentLabel)
        .filter(AgentLabel.agent_id == agent_id, AgentLabel.key == label_key)
        .first()
    )

    if not label:
        raise HTTPException(status_code=404, detail="Label not found")

    db.delete(label)
    db.commit()
    return {"message": "Label deleted"}


# Agent Drain Mode
@app.post("/api/agents/{agent_id}/drain")
def drain_agent(agent_id: int, db: Session = Depends(get_db)):
    """Put agent in drain mode - stop accepting new jobs."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.drain_mode = True
    if agent.status == AgentStatus.IDLE:
        agent.status = AgentStatus.OFFLINE
    db.commit()
    return {"message": "Agent now in drain mode", "drain_mode": True}


@app.post("/api/agents/{agent_id}/undrain")
def undrain_agent(agent_id: int, db: Session = Depends(get_db)):
    """Remove agent from drain mode."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.drain_mode = False
    if agent.status == AgentStatus.OFFLINE:
        agent.status = AgentStatus.IDLE
    db.commit()
    return {"message": "Agent removed from drain mode", "drain_mode": False}


# Agent Upgrade
@app.post("/api/agents/{agent_id}/upgrade")
def upgrade_agent(agent_id: int, db: Session = Depends(get_db)):
    """Trigger agent upgrade."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "message": "Upgrade triggered",
        "agent_id": agent_id,
        "current_version": agent.version,
        "upgrade_url": os.environ.get("AGENT_UPGRADE_URL", ""),
    }


# Job endpoints
@app.get("/api/jobs/pending", tags=["jobs"])
def get_pending_jobs(db: Session = Depends(get_db)):
    """Return pending jobs ready to run — dependencies satisfied, across all active builds.

    Only returns jobs whose depends_on requirements are all PASSED/SKIPPED so
    agents never pick up a job before its predecessors have finished.
    """
    from ci_engine.core.secrets import get_active_secrets

    candidate_jobs = (
        db.query(Job)
        .join(Build, Job.build_id == Build.id)
        .filter(
            Job.status == JobStatus.PENDING,
            Build.status.in_([BuildStatus.PENDING, BuildStatus.RUNNING]),
        )
        .order_by(Job.priority.desc(), Job.id)
        .limit(50)
        .all()
    )

    ready = []
    for j in candidate_jobs:
        # Skip wait/block nodes — they need manual unblocking, not agent execution
        if j.node_type in ("wait", "block"):
            continue

        if j.depends_on:
            deps = [d.strip() for d in j.depends_on.split(",") if d.strip()]
            sibling_jobs = db.query(Job).filter(Job.build_id == j.build_id).all()
            by_label = {sj.label: sj for sj in sibling_jobs}
            by_index = {sj.step_index: sj for sj in sibling_jobs}

            deps_satisfied = True
            for dep in deps:
                dep_job = by_label.get(dep) or (
                    by_index.get(int(dep)) if dep.isdigit() else None
                )
                if dep_job and dep_job.status not in (JobStatus.PASSED, JobStatus.SKIPPED):
                    deps_satisfied = False
                    break
            if not deps_satisfied:
                continue

        # Fetch build info for repository context
        build = db.query(Build).filter(Build.id == j.build_id).first()
        build_info = {}
        if build:
            build_info = {
                "id": build.id,
                "repository": build.repository,
                "branch": build.branch,
                "commit": build.commit,
                "clone_depth": build.clone_depth,
            }

        # Inject active secrets as env vars (scoped to build repository)
        secrets_env: dict[str, str] = {}
        try:
            repo = build.repository if build else None
            secrets_env = get_active_secrets(db, repository=repo)
        except Exception:
            pass

        # Merge job-level env_vars with secrets (secrets don't override explicit vars)
        job_env: dict = {}
        if j.env_vars:
            try:
                import json as _json
                job_env = _json.loads(j.env_vars)
            except Exception:
                pass
        merged_env = {**secrets_env, **job_env}

        ready.append({
            "id": j.id,
            "build_id": j.build_id,
            "label": j.label,
            "command": j.command,
            "status": j.status.value,
            "timeout_seconds": j.timeout_seconds,
            "env_vars": merged_env,
            "container_image": None,
            "depends_on": j.depends_on,
            "node_type": j.node_type or "command",
            "continue_on_error": bool(j.continue_on_error),
            "build": build_info,
        })

        if len(ready) >= 10:
            break

    return ready


@app.get("/api/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get a single job by ID — used by agents to check cancellation status."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "build_id": job.build_id,
        "label": job.label,
        "command": job.command,
        "status": job.status.value,
        "exit_code": job.exit_code,
        "agent_id": job.agent_id,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "timeout_seconds": job.timeout_seconds,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
    }


@app.post("/api/jobs/{job_id}/claim")
def claim_job(job_id: int, agent_id: int, db: Session = Depends(get_db)):
    """Agent claims a job to execute (atomic, race-condition-safe)."""
    from ci_engine.core.locking import claim_job_atomic

    # Validate existence before attempting atomic claim
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    success = claim_job_atomic(db, job_id, agent_id)
    if not success:
        raise HTTPException(status_code=409, detail="Job already claimed by another agent")

    return {"status": "claimed", "job_id": job_id}


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: int, db: Session = Depends(get_db)):
    """Mark job as started."""
    from ci_engine.core.notifications import send_build_notification, send_job_notification
    from ci_engine.core.notifications import NotificationEvent

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)

    build = db.query(Build).filter(Build.id == job.build_id).first()
    build_was_pending = build and build.status == BuildStatus.PENDING
    if build and build.status == BuildStatus.PENDING:
        build.status = BuildStatus.RUNNING
        build.started_at = datetime.now(timezone.utc)

    db.commit()

    broadcast_job_status(job_id, job.build_id, "running")

    # Report build started to GitHub/GitLab
    if build_was_pending and build:
        try:
            from ci_engine.core.git_status import get_reporter as get_git_reporter
            external_repo = getattr(build, "external_repo", None)
            head_sha = getattr(build, "head_sha", None)
            get_git_reporter().report_build_started(build.id, head_sha, external_repo)
        except Exception:
            pass

    # Fire notifications (background — don't block the agent)
    try:
        job_data = {"id": job.id, "label": job.label, "status": "running"}
        build_data = {
            "id": build.id, "branch": build.branch,
            "commit": build.commit, "status": "running",
        } if build else {}
        send_job_notification(NotificationEvent.JOB_STARTED, job_data, build_data)
        if build_was_pending:
            send_build_notification(NotificationEvent.BUILD_STARTED, build_data)
    except Exception:
        pass

    return {"status": "started"}


@app.post("/api/jobs/{job_id}/complete")
def complete_job(job_id: int, exit_code: int, db: Session = Depends(get_db)):
    """Mark job as completed with optional retry logic."""
    from ci_engine.core.scheduler import Scheduler

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Determine job outcome — continue_on_error jobs that fail are treated
    # as PASSED for dependency resolution so downstream jobs can still run.
    # We store the real exit_code but treat the status as PASSED.
    effective_failed = exit_code != 0
    job.exit_code = exit_code
    job.finished_at = datetime.now(timezone.utc)

    if job.agent:
        job.agent.status = AgentStatus.IDLE

    # continue_on_error / soft_fail: different treatment of failures.
    # - continue_on_error: treated as PASSED so downstream runs, but exit_code visible in UI.
    # - soft_fail: stored as SOFT_FAILED — downstream runs, build doesn't fail.
    # - hard fail: FAILED status, may cascade-skip downstream.
    continue_on_error = bool(getattr(job, "continue_on_error", False))
    soft_fail = bool(getattr(job, "soft_fail", False))

    if effective_failed and soft_fail:
        job.status = JobStatus.SOFT_FAILED
    elif effective_failed and not continue_on_error:
        job.status = JobStatus.FAILED
    else:
        job.status = JobStatus.PASSED

    db.commit()

    # Update downstream job statuses (unblock those whose deps are now met,
    # skip those whose deps failed).
    Scheduler.check_and_update_dependencies(db, job.build_id)

    retry_triggered = False

    if job.status == JobStatus.FAILED and job.max_retries > 0:
        retried_job = Scheduler.retry_job(db, job)
        if retried_job:
            retry_triggered = True

    if not retry_triggered:
        # Build is complete when no more jobs are pending/running/assigned
        active_count = (
            db.query(Job)
            .filter(
                Job.build_id == job.build_id,
                Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.ASSIGNED]),
            )
            .count()
        )

        if active_count == 0:
            build = db.query(Build).filter(Build.id == job.build_id).first()
            if build:
                failed_jobs = (
                    db.query(Job)
                    .filter(Job.build_id == build.id, Job.status == JobStatus.FAILED)
                    .count()
                )
                build.status = BuildStatus.PASSED if failed_jobs == 0 else BuildStatus.FAILED
                build.finished_at = datetime.now(timezone.utc)

    db.commit()

    build = db.query(Build).filter(Build.id == job.build_id).first()
    if build:
        jobs_total = db.query(Job).filter(Job.build_id == build.id).count()
        jobs_passed = (
            db.query(Job).filter(Job.build_id == build.id, Job.status == JobStatus.PASSED).count()
        )
        jobs_failed = (
            db.query(Job).filter(Job.build_id == build.id, Job.status == JobStatus.FAILED).count()
        )
        jobs_running = (
            db.query(Job).filter(Job.build_id == build.id, Job.status == JobStatus.RUNNING).count()
        )

        broadcast_job_status(job_id, job.build_id, job.status.value, exit_code)
        broadcast_build_status(
            build.id, build.status.value, jobs_total, jobs_passed, jobs_failed, jobs_running
        )

    # Fire notifications
    try:
        from ci_engine.core.notifications import send_build_notification, send_job_notification
        from ci_engine.core.notifications import NotificationEvent

        job_data = {
            "id": job.id, "label": job.label,
            "status": job.status.value, "exit_code": exit_code,
        }
        build_data = {
            "id": build.id, "branch": build.branch,
            "commit": build.commit, "status": build.status.value,
        } if build else {}

        if job.status == JobStatus.FAILED:
            send_job_notification(NotificationEvent.JOB_FAILED, job_data, build_data)
        else:
            send_job_notification(NotificationEvent.JOB_COMPLETED, job_data, build_data)

        if build and build.status in (BuildStatus.PASSED, BuildStatus.FAILED):
            if build.status == BuildStatus.PASSED:
                send_build_notification(NotificationEvent.BUILD_COMPLETED, build_data)
            else:
                send_build_notification(NotificationEvent.BUILD_FAILED, build_data)
    except Exception:
        pass

    # Report build completion to GitHub/GitLab + materialise analytics
    if build and build.status in (BuildStatus.PASSED, BuildStatus.FAILED):
        try:
            from ci_engine.core.git_status import get_reporter as get_git_reporter
            from ci_engine.core.analytics import materialise_build_metrics
            external_repo = getattr(build, "external_repo", None)
            head_sha = getattr(build, "head_sha", None)
            pr_number = getattr(build, "pr_number", None)
            is_passed = build.status == BuildStatus.PASSED
            reporter = get_git_reporter()
            reporter.report_build_completed(
                build.id, head_sha, external_repo, passed=is_passed,
            )
            # Post PR comment with build summary
            if pr_number:
                failed_job_labels = [
                    j.label for j in db.query(Job).filter(
                        Job.build_id == build.id, Job.status == JobStatus.FAILED
                    ).all()
                ]
                reporter.post_pr_comment(
                    external_repo=external_repo,
                    pr_number=pr_number,
                    build_id=build.id,
                    passed=is_passed,
                    failed_jobs=failed_job_labels,
                )
            materialise_build_metrics(db, build.id)
        except Exception:
            pass

    # Trigger async AI build summary when the build reaches a terminal state
    if build and build.status in (BuildStatus.PASSED, BuildStatus.FAILED):
        _safe_broadcast(_generate_build_summary_async(build.id))

    if retry_triggered:
        return {
            "status": "completed",
            "exit_code": exit_code,
            "retry_triggered": True,
            "new_job_id": job.id,
        }

    return {"status": "completed", "exit_code": exit_code}


@app.get("/api/jobs/{job_id}/logs", tags=["jobs"])
def get_job_logs(job_id: int, db: Session = Depends(get_db)):
    """Get all stored log lines for a job."""
    logs = db.query(JobLog).filter(JobLog.job_id == job_id).order_by(JobLog.id).all()
    return {
        "job_id": job_id,
        "lines": [
            {"line_number": i + 1, "content": log.line, "stream": log.stream, "timestamp": log.timestamp}
            for i, log in enumerate(logs)
        ],
    }


@app.post("/api/jobs/{job_id}/log")
async def append_log(
    job_id: int,
    request: Request,
    stream: Optional[str] = None,
    line: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Append a log line to a job — accepts query params OR JSON body.

    Agents send logs as query params: ?stream=stdout&line=text
    Fallback: JSON body {"stream": "stdout", "line": "text"}
    """
    if stream is None or line is None:
        try:
            body = await request.json()
            stream = stream or body.get("stream", "stdout")
            line = line if line is not None else body.get("line", "")
        except Exception:
            stream = stream or "stdout"
            line = line or ""

    log_entry = JobLog(job_id=job_id, stream=stream, line=line)
    db.add(log_entry)
    db.commit()

    # Broadcast to any live WebSocket subscribers
    await manager.broadcast(
        f"job_{job_id}_logs",
        {"type": "log", "job_id": job_id, "stream": stream, "content": line},
    )

    return {"status": "logged"}


# ---------------------------------------------------------------------------
# AI Analysis endpoints
# ---------------------------------------------------------------------------

class JobAIAnalysisCreate(BaseModel):
    root_cause: str = ""
    error_category: str = "unknown"
    explanation: str = ""
    fixed_command: Optional[str] = None
    confidence: float = 0.5
    pipeline_suggestion: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


class JobAIAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    root_cause: Optional[str] = None
    error_category: Optional[str] = None
    explanation: Optional[str] = None
    fixed_command: Optional[str] = None
    fix_applied: bool = False
    confidence: Optional[float] = None
    pipeline_suggestion: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


class AIFixRequest(BaseModel):
    fixed_command: str


class BuildAISummaryCreate(BaseModel):
    overall_health: str = "unknown"
    summary: str = ""
    what_failed: list[str] = []
    what_was_fixed: list[str] = []
    recommendations: list[str] = []


class BuildAISummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    build_id: int
    overall_health: Optional[str] = None
    summary: Optional[str] = None
    what_failed: Optional[str] = None
    what_was_fixed: Optional[str] = None
    recommendations: Optional[str] = None


@app.post("/api/jobs/{job_id}/ai-analysis", response_model=JobAIAnalysisResponse, tags=["ai"])
def store_job_ai_analysis(job_id: int, body: JobAIAnalysisCreate, db: Session = Depends(get_db)):
    """Agent plugin stores AI analysis for a failed job (upsert)."""
    existing = db.query(JobAIAnalysis).filter(JobAIAnalysis.job_id == job_id).first()
    if existing:
        existing.root_cause = body.root_cause
        existing.error_category = body.error_category
        existing.explanation = body.explanation
        existing.fixed_command = body.fixed_command
        existing.confidence = body.confidence
        existing.pipeline_suggestion = body.pipeline_suggestion
        existing.provider = body.provider
        existing.model = body.model
        db.commit()
        db.refresh(existing)
        return existing
    analysis = JobAIAnalysis(
        job_id=job_id,
        root_cause=body.root_cause,
        error_category=body.error_category,
        explanation=body.explanation,
        fixed_command=body.fixed_command,
        confidence=body.confidence,
        pipeline_suggestion=body.pipeline_suggestion,
        provider=body.provider,
        model=body.model,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


@app.get("/api/jobs/{job_id}/ai-analysis", response_model=JobAIAnalysisResponse, tags=["ai"])
def get_job_ai_analysis(job_id: int, db: Session = Depends(get_db)):
    """Frontend fetches AI analysis for a failed job."""
    analysis = db.query(JobAIAnalysis).filter(JobAIAnalysis.job_id == job_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="No AI analysis for this job")
    return analysis


@app.post("/api/jobs/{job_id}/ai-fix", tags=["ai"])
def apply_ai_fix(job_id: int, body: AIFixRequest, db: Session = Depends(get_db)):
    """Agent plugin triggers autonomous retry with a fixed command."""
    from ci_engine.core.scheduler import Scheduler

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="Job is not in FAILED state")
    if job.retry_count >= job.max_retries:
        raise HTTPException(status_code=400, detail="Retry budget exhausted")

    # Patch the command with the AI-suggested fix
    job.command = body.fixed_command

    # Mark analysis as fix_applied
    analysis = db.query(JobAIAnalysis).filter(JobAIAnalysis.job_id == job_id).first()
    if analysis:
        analysis.fix_applied = True
    db.commit()

    # Use existing retry mechanism
    retried = Scheduler.retry_job(db, job)
    if not retried:
        raise HTTPException(status_code=500, detail="Retry failed — check retry budget")

    return {"status": "retry_triggered", "new_command": body.fixed_command, "job_id": job_id}


@app.get("/api/builds/{build_id}/ai-summary", response_model=BuildAISummaryResponse, tags=["ai"])
def get_build_ai_summary(build_id: int, db: Session = Depends(get_db)):
    """Frontend fetches AI summary for a completed build."""
    summary = db.query(BuildAISummary).filter(BuildAISummary.build_id == build_id).first()
    if not summary:
        raise HTTPException(status_code=404, detail="No AI summary for this build")
    return summary


@app.post("/api/builds/{build_id}/ai-summary", response_model=BuildAISummaryResponse, tags=["ai"])
def store_build_ai_summary(build_id: int, body: BuildAISummaryCreate, db: Session = Depends(get_db)):
    """Background task stores LLM build summary (upsert)."""
    existing = db.query(BuildAISummary).filter(BuildAISummary.build_id == build_id).first()
    if existing:
        existing.overall_health = body.overall_health
        existing.summary = body.summary
        existing.what_failed = json.dumps(body.what_failed)
        existing.what_was_fixed = json.dumps(body.what_was_fixed)
        existing.recommendations = json.dumps(body.recommendations)
        db.commit()
        db.refresh(existing)
        return existing
    record = BuildAISummary(
        build_id=build_id,
        overall_health=body.overall_health,
        summary=body.summary,
        what_failed=json.dumps(body.what_failed),
        what_was_fixed=json.dumps(body.what_was_fixed),
        recommendations=json.dumps(body.recommendations),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# WebSocket for log streaming with job log storage
@app.websocket("/ws/logs/{job_id}")
async def websocket_logs(websocket: WebSocket, job_id: int):
    """Stream job logs via WebSocket with real-time updates."""
    await websocket.accept()
    channel = f"job_{job_id}_logs"
    await manager.connect(channel, websocket)
    try:
        await websocket.send_json(
            {
                "type": "connected",
                "job_id": job_id,
                "message": "Connected to job log stream",
            }
        )

        # Send existing logs if any
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                await websocket.send_json(
                    {
                        "type": "job_status",
                        "job_id": job_id,
                        "status": job.status,
                        "started_at": job.started_at.isoformat() if job.started_at else None,
                    }
                )
        finally:
            db.close()

        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
            elif data.startswith("log:"):
                # Broadcast log line to all subscribers
                log_line = data[4:]
                await manager.broadcast(
                    channel,
                    {
                        "type": "log",
                        "job_id": job_id,
                        "content": log_line,
                    },
                )
            else:
                await websocket.send_json({"type": "echo", "content": data})
    except WebSocketDisconnect:
        manager.disconnect(channel, websocket)


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/ai/status", tags=["ai"])
def ai_provider_status():
    """Return which LLM providers are configured and which is active.

    Powered by litellm — a unified interface to 100+ LLM providers.
    """
    from ci_engine.core.llm_providers import provider_status, discover_provider, list_available_providers

    active = discover_provider()
    available = list_available_providers()

    # litellm version (best-effort)
    litellm_version = None
    try:
        import importlib.metadata
        litellm_version = importlib.metadata.version("litellm")
    except Exception:
        pass

    return {
        "enabled": active is not None,
        "backend": "litellm",
        "litellm_version": litellm_version,
        "active_provider": active.name if active else None,
        "active_analysis_model": active.get_analysis_model() if active else None,
        "active_summary_model": active.get_summary_model() if active else None,
        "available_providers": [p.name for p in available],
        "providers": provider_status(),
        "config": {
            "CI_ENGINE_LLM_PROVIDER": os.environ.get("CI_ENGINE_LLM_PROVIDER") or "(auto)",
            "CI_ENGINE_AI_ANALYSIS_MODEL": os.environ.get("CI_ENGINE_AI_ANALYSIS_MODEL") or "(provider default)",
            "CI_ENGINE_AI_SUMMARY_MODEL": os.environ.get("CI_ENGINE_AI_SUMMARY_MODEL") or "(provider default)",
            "CI_ENGINE_AI_AUTO_FIX": os.environ.get("CI_ENGINE_AI_AUTO_FIX", "true"),
            "CI_ENGINE_AI_MAX_LOG_LINES": os.environ.get("CI_ENGINE_AI_MAX_LOG_LINES", "200"),
        },
    }


@app.get("/health/deep")
def deep_health_check(db: Session = Depends(get_db)):
    """Deep health check with database and system status."""
    import shutil
    import psutil
    from sqlalchemy import text

    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"

    disk = shutil.disk_usage("/")
    disk_free_gb = round(disk.free / (1024**3), 2)
    disk_total_gb = round(disk.total / (1024**3), 2)

    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.1)

    agents_online = db.query(Agent).filter(Agent.status == AgentStatus.IDLE).count()
    agents_busy = db.query(Agent).filter(Agent.status == AgentStatus.BUSY).count()
    agents_offline = db.query(Agent).filter(Agent.status == AgentStatus.OFFLINE).count()

    ws_connections = sum(len(connections) for connections in manager.active_connections.values())

    return {
        "status": "healthy" if db_status == "ok" else "degraded",
        "database": db_status,
        "system": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "disk_free_gb": disk_free_gb,
            "disk_total_gb": disk_total_gb,
        },
        "agents": {
            "online": agents_online,
            "busy": agents_busy,
            "offline": agents_offline,
            "total": agents_online + agents_busy + agents_offline,
        },
        "websockets": {
            "total_connections": ws_connections,
            "channels": len(manager.active_connections),
        },
    }


@app.get("/metrics")
def prometheus_metrics():
    """Prometheus metrics endpoint."""
    from ci_engine.core.metrics import metrics_endpoint

    return Response(content=metrics_endpoint.get_metrics(), media_type="text/plain")


# WebSocket graceful shutdown is now handled in lifespan


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Get CI engine statistics."""
    from datetime import datetime

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    builds_24h = db.query(Build).filter(Build.created_at >= day_ago).count()
    total_builds = db.query(Build).count()
    active_pipelines = db.query(Build).filter(Build.status == BuildStatus.RUNNING).count()

    return {
        "builds_24h": builds_24h,
        "total_builds": total_builds,
        "active_pipelines": active_pipelines,
    }


@app.get("/status")
def status_page(db: Session = Depends(get_db)):
    """Status page similar to Buildkite."""
    return {
        "status": "All Systems Operational",
        "components": [
            {"name": "API Server", "status": "operational"},
            {"name": "Agent Pool", "status": "operational"},
            {"name": "Database", "status": "operational"},
        ],
    }


# Auth endpoints
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "developer"


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


@app.post("/api/auth/register", response_model=UserResponse, tags=["auth"])
def register_user(user_data: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user with password validation."""
    from ci_engine.server.auth import PasswordValidator

    errors = PasswordValidator.validate(user_data.password)
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    existing = db.query(User).filter(User.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    user = AuthService.create_user(db, user_data.username, user_data.password, user_data.role)
    return user


@app.post("/api/auth/login", response_model=LoginResponse, tags=["auth"])
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    """Login and get access/refresh tokens."""
    user = AuthService.authenticate_user(db, credentials.username, credentials.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(user.id)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@app.post("/api/auth/refresh", response_model=LoginResponse, tags=["auth"])
def refresh_token(refresh_data: TokenRefreshRequest, db: Session = Depends(get_db)):
    """Refresh access token using refresh token."""
    try:
        payload = verify_token(refresh_data.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.type != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user = db.query(User).filter(User.id == int(payload.sub)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    access_token = create_access_token(user.id, user.username)
    new_refresh_token = create_refresh_token(user.id)

    return LoginResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
    )


@app.get("/api/auth/github/login", tags=["auth"])
def github_login():
    """Redirect to GitHub for OAuth login."""
    import secrets

    state = secrets.token_urlsafe(32)
    from ci_engine.server.github_oauth import get_github_oauth_url

    url = get_github_oauth_url(state)
    return {"authorization_url": url, "state": state}


@app.get("/api/auth/github/callback", tags=["auth"])
def github_callback(code: str, state: str):
    """Handle GitHub OAuth callback."""
    from ci_engine.server.github_oauth import handle_github_callback

    return handle_github_callback(code, state)


@app.get("/api/auth/me", response_model=UserResponse, tags=["auth"])
def get_me(current_user: User = Depends(get_current_user)):
    """Get current user info."""
    return current_user


# Token management endpoints
class TokenCreate(BaseModel):
    name: str
    expires_in_days: Optional[int] = 30


class TokenListItem(BaseModel):
    id: int
    name: str
    created_at: datetime
    expires_at: Optional[datetime]
    last_used: Optional[datetime]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TokenRefreshRequest(BaseModel):
    token_id: int


@app.post("/api/auth/tokens", response_model=TokenResponse, tags=["auth"])
def create_token(
    token_data: TokenCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new API token."""
    token_obj, raw_token = AuthService.create_api_token(
        db, current_user.id, token_data.name, token_data.expires_in_days or 30
    )
    return TokenResponse(
        token=raw_token,
        name=token_obj.name,
        created_at=token_obj.created_at,
        expires_at=token_obj.expires_at,
    )


@app.get("/api/auth/tokens", response_model=list[TokenListItem], tags=["auth"])
def list_tokens(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all API tokens for current user."""
    return AuthService.list_user_tokens_metadata(db, current_user.id)


@app.delete("/api/auth/tokens/{token_id}", tags=["auth"])
def revoke_token(
    token_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke an API token."""
    success = AuthService.revoke_token_by_id(db, token_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "revoked", "token_id": token_id}


@app.post("/api/auth/tokens/refresh", response_model=TokenResponse, tags=["auth"])
def rotate_token(
    refresh_data: TokenRefreshRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rotate an API token (create new, revoke old)."""
    result = AuthService.rotate_refresh_token(db, refresh_data.token_id, current_user.id)
    if not result:
        raise HTTPException(status_code=404, detail="Token not found or already inactive")

    token_obj, raw_token = result
    return TokenResponse(
        token=raw_token,
        name=token_obj.name,
        created_at=token_obj.created_at,
        expires_at=token_obj.expires_at,
    )


# Build cancellation endpoints
@app.post("/api/builds/{build_id}/cancel", tags=["builds"])
def cancel_build(build_id: int, db: Session = Depends(get_db)):
    """Cancel a build and all its jobs."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    if build.status in (BuildStatus.PASSED, BuildStatus.FAILED, BuildStatus.CANCELED):
        raise HTTPException(status_code=400, detail=f"Build already {build.status}")

    build.status = BuildStatus.CANCELED
    build.finished_at = datetime.now(timezone.utc)

    jobs = db.query(Job).filter(Job.build_id == build_id).all()
    for job in jobs:
        if job.status in (JobStatus.PENDING, JobStatus.ASSIGNED, JobStatus.RUNNING):
            job.status = JobStatus.CANCELED
            job.finished_at = datetime.now(timezone.utc)
            if job.agent:
                job.agent.status = AgentStatus.IDLE

    db.commit()
    return {"status": "canceled", "build_id": build_id}


@app.post("/api/jobs/{job_id}/cancel", tags=["jobs"])
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    """Cancel a specific job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in (JobStatus.PASSED, JobStatus.FAILED, JobStatus.CANCELED):
        raise HTTPException(status_code=400, detail=f"Job already {job.status}")

    job.status = JobStatus.CANCELED
    job.finished_at = datetime.now(timezone.utc)

    if job.agent:
        job.agent.status = AgentStatus.IDLE

    pending_jobs = (
        db.query(Job)
        .filter(
            Job.build_id == job.build_id,
            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.ASSIGNED]),
        )
        .count()
    )

    if pending_jobs == 0:
        build = db.query(Build).filter(Build.id == job.build_id).first()
        if build and build.status != BuildStatus.CANCELED:
            build.status = BuildStatus.FAILED
            build.finished_at = datetime.now(timezone.utc)

    db.commit()
    return {"status": "canceled", "job_id": job_id}


@app.post("/api/builds/{build_id}/unblock", response_model=BuildResponse, tags=["builds"])
def unblock_build(build_id: int, step: Optional[str] = None, db: Session = Depends(get_db)):
    """Unblock a blocked build or a specific wait/block step.

    - If `step` is provided: unblock only that named step (label match).
    - Otherwise: unblock the first (lowest step_index) wait/block node that is BLOCKED
      and whose dependencies are all satisfied.
    """
    from ci_engine.core.scheduler import Scheduler

    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    all_jobs = db.query(Job).filter(Job.build_id == build_id).all()
    blocked_wait_jobs = [
        j for j in all_jobs
        if j.status == JobStatus.BLOCKED and j.node_type in ("wait", "block")
    ]

    if not blocked_wait_jobs:
        # Fall back: unblock ANY blocked job (e.g. dependency-blocked jobs now ready)
        blocked_jobs = [j for j in all_jobs if j.status == JobStatus.BLOCKED]
        if not blocked_jobs:
            raise HTTPException(status_code=400, detail="No blocked jobs to unblock")
        for j in blocked_jobs:
            j.status = JobStatus.PENDING
    else:
        # If a specific step was requested, unblock only that step
        if step:
            target = next((j for j in blocked_wait_jobs if j.label == step), None)
            if not target:
                raise HTTPException(status_code=404, detail=f"No blocked wait step named '{step}'")
            jobs_to_unblock = [target]
        else:
            # Unblock the lowest-index wait/block step that has its deps satisfied
            by_label = {j.label: j for j in all_jobs}
            by_index = {j.step_index: j for j in all_jobs}
            ready_waits = []
            for j in sorted(blocked_wait_jobs, key=lambda x: x.step_index):
                deps_ok = True
                if j.depends_on:
                    for dep in j.depends_on.split(","):
                        dep = dep.strip()
                        dep_job = by_label.get(dep) or (by_index.get(int(dep)) if dep.isdigit() else None)
                        if dep_job and dep_job.status not in (JobStatus.PASSED, JobStatus.SKIPPED):
                            deps_ok = False
                            break
                if deps_ok:
                    ready_waits.append(j)
            jobs_to_unblock = ready_waits[:1] if ready_waits else blocked_wait_jobs[:1]

        for j in jobs_to_unblock:
            # Wait/block nodes pass immediately when unblocked — no command to run
            j.status = JobStatus.PASSED
            j.finished_at = datetime.now(timezone.utc)
            broadcast_job_status(j.id, build_id, "passed", 0)

    if build.status == BuildStatus.PENDING:
        build.status = BuildStatus.RUNNING

    db.commit()

    # Run dependency resolution so jobs waiting on this gate become runnable
    Scheduler.check_and_update_dependencies(db, build_id)

    db.refresh(build)

    broadcast_build_status(
        build.id, build.status.value,
        len(all_jobs),
        sum(1 for j in all_jobs if j.status == JobStatus.PASSED),
        sum(1 for j in all_jobs if j.status == JobStatus.FAILED),
        sum(1 for j in all_jobs if j.status == JobStatus.RUNNING),
    )

    return build


# Agent heartbeat endpoint
@app.post("/api/agents/{agent_id}/heartbeat", tags=["agents"])
def agent_heartbeat(agent_id: int, db: Session = Depends(get_db)):
    """Update agent last_seen timestamp."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.last_seen = datetime.now(timezone.utc)
    agent.status = AgentStatus.IDLE
    db.commit()
    return {"status": "ok", "agent_id": agent_id}


def _create_build_from_webhook(db, build_info: dict) -> dict:
    """Create a build from webhook event data.

    Looks up a registered pipeline for the repository, or uses a sensible
    default that actually works for most projects.  The pipeline can be
    overridden per-repository via the pipeline_triggers table.
    """
    repo = build_info.get("repository", "")
    branch = build_info.get("branch", "main")

    # Look for a saved pipeline trigger that matches this repository
    pipeline_yaml = None
    trigger = (
        db.query(PipelineTrigger).filter(PipelineTrigger.name == repo).first()
        or db.query(PipelineTrigger).filter(PipelineTrigger.pipeline.contains(repo)).first()
    )
    if trigger:
        pipeline_yaml = trigger.pipeline

    if not pipeline_yaml:
        # Sensible default: detect common CI patterns
        pipeline_yaml = f"""
env:
  REPO: "{repo}"
  BRANCH: "{branch}"

steps:
  - label: "Checkout & Install"
    command: |
      echo "Repository: {repo}"
      echo "Branch: {branch}"
      if [ -f package.json ]; then npm ci; fi
      if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      if [ -f Gemfile ]; then bundle install; fi
      if [ -f go.mod ]; then go mod download; fi

  - label: "Build"
    command: |
      if [ -f Makefile ] && grep -q '^build:' Makefile; then make build
      elif [ -f package.json ] && grep -q '"build"' package.json; then npm run build
      elif [ -f go.mod ]; then go build ./...
      else echo "No build step detected — skipping"
      fi
    depends_on: ["Checkout & Install"]

  - label: "Test"
    command: |
      if [ -f Makefile ] && grep -q '^test:' Makefile; then make test
      elif [ -f package.json ] && grep -q '"test"' package.json; then npm test
      elif [ -f pytest.ini ] || [ -f setup.cfg ] || [ -f pyproject.toml ]; then pytest
      elif [ -f go.mod ]; then go test ./...
      else echo "No test step detected — skipping"
      fi
    depends_on: ["Build"]
    continue-on-error: false
"""

    build = Build(
        pipeline=pipeline_yaml,
        branch=branch,
        commit=build_info.get("commit"),
        repository=repo,
        git_ref=branch,
        status=BuildStatus.PENDING,
    )
    db.add(build)
    db.commit()

    steps = parse_pipeline(pipeline_yaml)
    for i, step in enumerate(steps):
        depends_on = step.get("depends_on") or []
        if isinstance(depends_on, list):
            depends_on_str = ",".join(depends_on)
        else:
            depends_on_str = str(depends_on)

        job = Job(
            build_id=build.id,
            step_index=i,
            label=step.get("label", f"Step {i + 1}"),
            command=step.get("command", "echo done"),
            status=JobStatus.PENDING,
            depends_on=depends_on_str or None,
            timeout_seconds=step.get("timeout", 3600),
            max_retries=step.get("retry", 0),
        )
        db.add(job)
    db.commit()

    return {"status": "created", "build_id": build.id, "steps": len(steps)}


# Webhook endpoints
@app.post("/api/webhooks", response_model=WebhookResponse, tags=["webhooks"])
def create_webhook(webhook_data: WebhookCreate, db: Session = Depends(get_db)):
    """Create a new webhook configuration."""
    webhook = WebhookConfig(
        name=webhook_data.name,
        url=webhook_data.url,
        events=",".join(webhook_data.events),
        secret=webhook_data.secret,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)
    return webhook


@app.get("/api/webhooks", response_model=list[WebhookResponse], tags=["webhooks"])
def list_webhooks(db: Session = Depends(get_db)):
    """List all webhooks."""
    return db.query(WebhookConfig).all()


@app.get("/api/webhooks/{webhook_id}", response_model=WebhookResponse, tags=["webhooks"])
def get_webhook(webhook_id: int, db: Session = Depends(get_db)):
    """Get a specific webhook."""
    webhook = db.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


@app.delete("/api/webhooks/{webhook_id}", tags=["webhooks"])
def delete_webhook(webhook_id: int, db: Session = Depends(get_db)):
    """Delete a webhook."""
    webhook = db.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    db.delete(webhook)
    db.commit()
    return {"status": "deleted", "webhook_id": webhook_id}


@app.post("/api/webhooks/github", tags=["webhooks"])
def github_webhook(
    payload: dict,
    x_hub_signature_256: Optional[str] = None,
    x_github_event: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Handle incoming GitHub webhooks."""
    active_webhooks = (
        db.query(WebhookConfig)
        .filter(
            WebhookConfig.is_active,
            WebhookConfig.events.contains("github"),
        )
        .all()
    )

    for webhook in active_webhooks:
        if webhook.secret:
            if not WebhookService.verify_github_signature(
                str(payload).encode(),
                webhook.secret,
                x_hub_signature_256 or "",
            ):
                continue

    event = WebhookService.parse_github_event(payload, x_github_event or "")
    if event:
        build_info = WebhookService.extract_build_info(event)
        if build_info:
            return _create_build_from_webhook(db, build_info)

    return {"status": "received"}


@app.post("/api/webhooks/gitlab", tags=["webhooks"])
def gitlab_webhook(
    payload: dict,
    x_gitlab_token: Optional[str] = None,
    x_gitlab_event: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Handle incoming GitLab webhooks."""
    active_webhooks = (
        db.query(WebhookConfig)
        .filter(
            WebhookConfig.is_active,
            WebhookConfig.events.contains("gitlab"),
        )
        .all()
    )

    for webhook in active_webhooks:
        if webhook.secret:
            if not WebhookService.verify_gitlab_token(x_gitlab_token or "", webhook.secret):
                raise HTTPException(status_code=401, detail="Invalid GitLab token")

    event = WebhookService.parse_gitlab_event(payload, x_gitlab_event or "")
    if event:
        build_info = WebhookService.extract_build_info(event)
        if build_info:
            return _create_build_from_webhook(db, build_info)

    return {"status": "received"}


# Artifact endpoints


@ app.post("/api/artifacts", response_model=ArtifactResponse, tags=["artifacts"])
async def upload_artifact(
    build_id: int,
    job_id: Optional[int] = None,
    filename: str = "",
    content_type: str = "application/octet-stream",
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Upload an artifact with optional file content."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    file_data = b""
    file_size = 0

    if file:
        file_data = await file.read()
        file_size = len(file_data)
        if not filename:
            filename = file.filename or "artifact"
        if not content_type or content_type == "application/octet-stream":
            content_type = file.content_type or "application/octet-stream"

    storage_key = f"builds/{build_id}/jobs/{job_id or 'none'}/{filename}"
    storage_location = (
        f"s3://{os.environ.get('CI_ENGINE_S3_BUCKET', 'ci-engine-artifacts')}/{storage_key}"
    )

    if file_data and os.environ.get("CI_ENGINE_S3_BUCKET"):
        try:
            storage = get_artifact_storage()
            result = await storage.upload_artifact(
                data=file_data,
                build_id=build_id,
                job_id=job_id,
                filename=filename,
                content_type=content_type,
            )
            storage_key = result.key
            storage_location = result.storage_location
            file_size = result.size
        except Exception:
            pass

    artifact = Artifact(
        build_id=build_id,
        job_id=job_id,
        filename=filename or "artifact",
        size=file_size,
        content_type=content_type,
        storage_key=storage_key,
        storage_location=storage_location,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


@app.get("/api/artifacts/{artifact_id}/download", tags=["artifacts"])
async def download_artifact(artifact_id: int, db: Session = Depends(get_db)):
    """Download an artifact file."""
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if os.environ.get("CI_ENGINE_S3_BUCKET") and artifact.storage_key:
        try:
            storage = get_artifact_storage()
            build_id = artifact.build_id
            job_id = artifact.job_id
            data = await storage.download_artifact(
                build_id=build_id,
                job_id=job_id,
                filename=artifact.filename,
            )
            return Response(
                content=data,
                media_type=artifact.content_type,
                headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to download: {str(e)}")

    raise HTTPException(status_code=404, detail="Artifact file not found")


# Cache endpoints


@app.get("/api/cache", tags=["cache"])
def list_cache():
    """List all cache entries."""
    cache = get_cache()
    entries = cache.list()
    return [
        {
            "key": e.key,
            "path": e.path,
            "size": e.size,
            "created_at": e.created_at.isoformat(),
            "expires_at": e.expires_at.isoformat() if e.expires_at else None,
            "hit_count": e.hit_count,
        }
        for e in entries
    ]


@app.post("/api/cache", tags=["cache"])
def create_cache_entry(
    build_id: int,
    job_id: int,
    cache_key: str,
    source_path: str,
    ttl_days: int = 7,
):
    """Store files in cache."""
    key = compute_cache_key(build_id, job_id, cache_key)
    cache = get_cache()
    cache.put(key, source_path, ttl_days)
    return {"key": key, "status": "stored"}


@app.get("/api/cache/{cache_key:path}", tags=["cache"])
def get_cache_entry(cache_key: str):
    """Get cache entry by key."""
    cache = get_cache()
    path = cache.get(cache_key)
    if path is None:
        raise HTTPException(status_code=404, detail="Cache not found")
    return {"key": cache_key, "path": path, "status": "hit"}


@app.delete("/api/cache/{cache_key:path}", tags=["cache"])
def delete_cache_entry(cache_key: str):
    """Delete cache entry."""
    cache = get_cache()
    deleted = cache.delete(cache_key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cache not found")
    return {"status": "deleted", "key": cache_key}


@app.delete("/api/cache", tags=["cache"])
def clear_cache():
    """Clear all cache entries."""
    cache = get_cache()
    count = cache.clear()
    return {"status": "cleared", "count": count}


@app.get(
    "/api/builds/{build_id}/artifacts", response_model=list[ArtifactResponse], tags=["artifacts"]
)
def list_build_artifacts(build_id: int, db: Session = Depends(get_db)):
    """List artifacts for a build."""
    return db.query(Artifact).filter(Artifact.build_id == build_id).all()


@app.get("/api/artifacts/{artifact_id}", response_model=ArtifactResponse, tags=["artifacts"])
def get_artifact(artifact_id: int, db: Session = Depends(get_db)):
    """Get artifact metadata."""
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@app.delete("/api/artifacts/{artifact_id}", tags=["artifacts"])
def delete_artifact(artifact_id: int, db: Session = Depends(get_db)):
    """Delete an artifact."""
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    db.delete(artifact)
    db.commit()
    return {"status": "deleted", "artifact_id": artifact_id}


@app.post("/api/admin/cleanup", tags=["admin"])
def cleanup_old_builds(days: int = 30, db: Session = Depends(get_db)):
    """Clean up old builds and their data. Returns count of deleted items."""

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    old_builds = db.query(Build).filter(Build.created_at < cutoff_date).all()
    deleted_builds = len(old_builds)

    deleted_jobs = 0
    deleted_artifacts = 0
    deleted_logs = 0

    for build in old_builds:
        jobs = db.query(Job).filter(Job.build_id == build.id).all()
        for job in jobs:
            logs = db.query(JobLog).filter(JobLog.job_id == job.id).all()
            deleted_logs += len(logs)
            for log in logs:
                db.delete(log)

            db.delete(job)
            deleted_jobs += 1

        artifacts = db.query(Artifact).filter(Artifact.build_id == build.id).all()
        for artifact in artifacts:
            db.delete(artifact)
            deleted_artifacts += 1

        db.delete(build)

    db.commit()

    return {
        "status": "cleaned",
        "deleted_builds": deleted_builds,
        "deleted_jobs": deleted_jobs,
        "deleted_artifacts": deleted_artifacts,
        "deleted_logs": deleted_logs,
    }


@app.post("/api/admin/reap-offline-agents", tags=["admin"])
def reap_offline_agents(timeout_minutes: int = 5, db: Session = Depends(get_db)):
    """Mark agents as offline if they haven't sent a heartbeat."""

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

    offline_agents = (
        db.query(Agent)
        .filter(
            Agent.status != AgentStatus.OFFLINE,
            Agent.last_seen < cutoff,
        )
        .all()
    )

    count = 0
    for agent in offline_agents:
        agent.status = AgentStatus.OFFLINE
        count += 1

    db.commit()

    return {"status": "reaped", "agents_marked_offline": count}


# OIDC endpoints


@app.get("/api/oidc/config", tags=["oidc"])
def get_oidc_config(provider: str):
    """Get OIDC provider configuration."""
    config = OIDCProviderManager.from_env(provider)
    if not config:
        raise HTTPException(status_code=404, detail="Provider not configured")
    return {
        "provider": config.provider.value,
        "issuer_url": config.issuer_url,
        "client_id": config.client_id,
        "authorization_endpoint": f"{config.issuer_url}/authorize",
        "token_endpoint": f"{config.issuer_url}/oauth/token",
    }


@app.get("/api/oidc/providers", tags=["oidc"])
def list_oidc_providers():
    """List all available OIDC providers."""
    providers = OIDCProviderManager.get_all_providers()
    return [
        {
            "provider": p.provider.value,
            "issuer_url": p.issuer_url,
            "client_id": p.client_id,
        }
        for p in providers
        if p.client_id
    ]


@app.post("/api/oidc/verify", tags=["oidc"])
def verify_oidc_token(provider: str, token: str):
    """Verify an OIDC token."""
    verifier = OIDCTokenVerifier()
    try:
        result = verifier.verify(token, provider)
        return {"valid": True, "claims": result}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@app.post("/api/oidc/exchange", tags=["oidc"])
def exchange_oidc_token(provider: str, token: str):
    """Exchange OIDC token for cloud credentials."""
    exchange = OIDCTokenExchange()
    try:
        if provider == "aws":
            creds = exchange.exchange_for_aws(token)
            return {
                "provider": "aws",
                "access_key": creds.get("AccessKeyId"),
                "region": creds.get("Region"),
            }
        elif provider == "gcp":
            creds = exchange.exchange_for_gcp(token)
            return {"provider": "gcp", "access_token": creds.get("access_token")}
        elif provider == "azure":
            creds = exchange.exchange_for_azure(token)
            return {"provider": "azure", "access_token": creds.get("access_token")}
        else:
            raise HTTPException(status_code=400, detail="Unsupported provider")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Exchange failed: {str(e)}")


# Audit log endpoints


@app.get("/api/audit-logs", response_model=list[AuditLogResponse], tags=["audit"])
def list_audit_logs(
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List audit log entries."""
    query = db.query(AuditEntry).order_by(AuditEntry.timestamp.desc())

    if action:
        query = query.filter(AuditEntry.action == action)
    if user_id:
        query = query.filter(AuditEntry.user_id == user_id)

    return query.limit(limit).all()


@app.get("/api/audit-logs/{entry_id}", response_model=AuditLogResponse, tags=["audit"])
def get_audit_log(entry_id: int, db: Session = Depends(get_db)):
    """Get a specific audit log entry."""
    entry = db.query(AuditEntry).filter(AuditEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Audit log entry not found")
    return entry


@app.get("/api/audit-logs/actions", tags=["audit"])
def list_audit_actions():
    """List all available audit action types."""
    return [action.value for action in AuditAction]


# Secrets management endpoints


@app.get("/api/secrets", response_model=list[SecretResponse], tags=["secrets"])
def list_secrets(db: Session = Depends(get_db)):
    """List all secrets (without values)."""
    secrets = db.query(Secret).filter(Secret.is_active).all()
    return secrets


@app.post("/api/secrets", response_model=SecretResponse, tags=["secrets"])
def create_secret(secret_data: SecretCreate, db: Session = Depends(get_db)):
    """Create a new secret. Optionally scoped to a repository via ``repository`` field."""
    from ci_engine.core.secrets import _encrypt_value

    # Allow same name for different repos; only block global duplicates
    existing = (
        db.query(Secret)
        .filter(
            Secret.name == secret_data.name,
            Secret.repository == secret_data.repository,
            Secret.is_active,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Secret '{secret_data.name}' already exists"
            + (f" for repository '{secret_data.repository}'" if secret_data.repository else " (global)"),
        )

    encrypted, version = _encrypt_value(secret_data.value)

    secret = Secret(
        name=secret_data.name,
        value_encrypted=encrypted,
        key_version=version,
        created_by=secret_data.created_by,
        repository=secret_data.repository,
    )
    db.add(secret)
    db.commit()
    db.refresh(secret)

    return secret


@app.get("/api/secrets/{secret_id}", response_model=SecretResponse, tags=["secrets"])
def get_secret(secret_id: int, db: Session = Depends(get_db)):
    """Get secret metadata (not the value)."""
    secret = db.query(Secret).filter(Secret.id == secret_id).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")
    return secret


@app.put("/api/secrets/{secret_id}", response_model=SecretResponse, tags=["secrets"])
def update_secret(secret_id: int, value: str, db: Session = Depends(get_db)):
    """Update a secret value."""
    from ci_engine.core.secrets import _encrypt_value

    secret = db.query(Secret).filter(Secret.id == secret_id).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    encrypted, version = _encrypt_value(value)
    secret.value_encrypted = encrypted
    secret.key_version = version

    db.commit()
    db.refresh(secret)

    return secret


@app.delete("/api/secrets/{secret_id}", tags=["secrets"])
def delete_secret(
    secret_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a secret (soft delete). Requires admin permission."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Requires admin permission")

    secret = db.query(Secret).filter(Secret.id == secret_id).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    secret.is_active = False
    db.commit()

    return {"status": "deleted", "secret_id": secret_id}


@app.post("/api/secrets/{secret_id}/rotate", response_model=SecretResponse, tags=["secrets"])
def rotate_secret(
    secret_id: int,
    new_value: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rotate a secret with a new value. Requires admin permission."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Requires admin permission")

    from ci_engine.core.secrets import _encrypt_value

    secret = db.query(Secret).filter(Secret.id == secret_id).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    encrypted, version = _encrypt_value(new_value)
    secret.value_encrypted = encrypted
    secret.key_version = version + 1
    secret.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(secret)

    return secret


@app.get("/api/secrets/{secret_id}/value", tags=["secrets"])
def get_secret_value(secret_id: int, db: Session = Depends(get_db)):
    """Get decrypted secret value (requires elevated permissions)."""
    from ci_engine.core.secrets import _decrypt_value

    secret = db.query(Secret).filter(Secret.id == secret_id).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")
    if not secret.is_active:
        raise HTTPException(status_code=400, detail="Secret is inactive")

    try:
        value = _decrypt_value(secret.value_encrypted, secret.key_version)
        return {"value": value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt: {str(e)}")


# Environment Groups API
@app.get(
    "/api/environments", response_model=list["EnvironmentGroupResponse"], tags=["environments"]
)
def list_environments(db: Session = Depends(get_db)):
    """List all environment groups."""
    groups = db.query(EnvironmentGroup).all()
    for group in groups:
        group.variables = (
            json.loads(group.variables) if isinstance(group.variables, str) else group.variables
        )
    return groups


@app.post("/api/environments", response_model="EnvironmentGroupResponse", tags=["environments"])
def create_environment(
    group_data: "EnvironmentGroupCreate",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new environment group. Requires admin permission."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Requires admin permission")

    import json as json_module

    variables_json = json_module.dumps(group_data.variables)

    group = EnvironmentGroup(
        name=group_data.name,
        description=group_data.description,
        variables=variables_json,
        created_by=current_user.username,
    )
    db.add(group)
    db.commit()
    db.refresh(group)

    group.variables = group_data.variables
    return group


@app.get(
    "/api/environments/{group_id}", response_model="EnvironmentGroupResponse", tags=["environments"]
)
def get_environment(group_id: int, db: Session = Depends(get_db)):
    """Get environment group by ID."""
    group = db.query(EnvironmentGroup).filter(EnvironmentGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Environment group not found")

    group.variables = (
        json.loads(group.variables) if isinstance(group.variables, str) else group.variables
    )
    return group


@app.put(
    "/api/environments/{group_id}", response_model="EnvironmentGroupResponse", tags=["environments"]
)
def update_environment(
    group_id: int,
    group_data: "EnvironmentGroupCreate",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update environment group. Requires admin permission."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Requires admin permission")

    group = db.query(EnvironmentGroup).filter(EnvironmentGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Environment group not found")

    import json as json_module

    group.name = group_data.name
    group.description = group_data.description
    group.variables = json_module.dumps(group_data.variables)
    group.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(group)

    group.variables = group_data.variables
    return group


@app.delete("/api/environments/{group_id}", tags=["environments"])
def delete_environment(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete environment group. Requires admin permission."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Requires admin permission")

    group = db.query(EnvironmentGroup).filter(EnvironmentGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Environment group not found")

    db.delete(group)
    db.commit()

    return {"status": "deleted", "group_id": group_id}


# Triggers API
@app.get("/api/triggers", response_model=list["PipelineTriggerResponse"], tags=["triggers"])
def list_triggers(db: Session = Depends(get_db)):
    """List all pipeline triggers."""
    triggers = db.query(PipelineTrigger).all()
    return triggers


@app.post("/api/triggers", response_model="PipelineTriggerResponse", tags=["triggers"])
def create_trigger(
    trigger_data: "PipelineTriggerCreate",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new pipeline trigger. Requires admin permission."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Requires admin permission")

    trigger = PipelineTrigger(
        name=trigger_data.name,
        pipeline=trigger_data.pipeline,
        branch=trigger_data.branch,
        cron_expression=trigger_data.cron_expression,
        enabled=trigger_data.enabled,
    )
    db.add(trigger)
    db.commit()
    db.refresh(trigger)
    return trigger


@app.get("/api/triggers/{trigger_id}", response_model="PipelineTriggerResponse", tags=["triggers"])
def get_trigger(trigger_id: int, db: Session = Depends(get_db)):
    """Get trigger by ID."""
    trigger = db.query(PipelineTrigger).filter(PipelineTrigger.id == trigger_id).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return trigger


@app.put("/api/triggers/{trigger_id}", response_model="PipelineTriggerResponse", tags=["triggers"])
def update_trigger(
    trigger_id: int,
    trigger_data: "PipelineTriggerCreate",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update trigger. Requires admin permission."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Requires admin permission")

    trigger = db.query(PipelineTrigger).filter(PipelineTrigger.id == trigger_id).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    trigger.name = trigger_data.name
    trigger.pipeline = trigger_data.pipeline
    trigger.branch = trigger_data.branch
    trigger.cron_expression = trigger_data.cron_expression
    trigger.enabled = trigger_data.enabled
    trigger.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(trigger)
    return trigger


@app.delete("/api/triggers/{trigger_id}", tags=["triggers"])
def delete_trigger(
    trigger_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete trigger. Requires admin permission."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Requires admin permission")

    trigger = db.query(PipelineTrigger).filter(PipelineTrigger.id == trigger_id).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    db.delete(trigger)
    db.commit()

    return {"status": "deleted", "trigger_id": trigger_id}


# ===========================================================================
# Feature 6 — Pipeline validation (lint) endpoint
# ===========================================================================

class PipelineValidateRequest(BaseModel):
    pipeline_yaml: str


@app.post("/api/pipelines/validate", tags=["pipelines"])
def validate_pipeline(body: PipelineValidateRequest):
    """Lint a pipeline YAML and return validation errors/warnings."""
    from ci_engine.core.pipeline_lint import lint_pipeline
    result = lint_pipeline(body.pipeline_yaml)
    return result.as_dict()


# ===========================================================================
# Feature 7 — Test result ingestion + flakiness
# ===========================================================================

class TestResultsUpload(BaseModel):
    content: str
    content_type: str = ""  # application/xml or application/json
    repository: Optional[str] = None


@app.post("/api/jobs/{job_id}/test-results", tags=["test-results"])
def upload_test_results(
    job_id: int,
    body: TestResultsUpload,
    db: Session = Depends(get_db),
):
    """Ingest JUnit XML or CTRF JSON test results for a job."""
    from ci_engine.core.test_parser import parse_test_results
    from ci_engine.server.models_extensions import TestRun

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    parsed = parse_test_results(body.content, body.content_type)
    if not parsed:
        raise HTTPException(status_code=422, detail="No test cases found in payload")

    repository = body.repository or getattr(
        db.query(Build).filter(Build.id == job.build_id).first(), "repository", None
    )

    rows = [
        TestRun(
            job_id=job_id,
            build_id=job.build_id,
            repository=repository,
            test_name=t["test_name"],
            test_suite=t.get("test_suite"),
            status=t["status"],
            duration_ms=t.get("duration_ms"),
            failure_message=t.get("failure_message"),
            failure_type=t.get("failure_type"),
        )
        for t in parsed
    ]
    db.add_all(rows)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "inserted": len(rows),
        "job_id": job_id,
        "summary": {
            "passed": sum(1 for t in parsed if t["status"] == "passed"),
            "failed": sum(1 for t in parsed if t["status"] == "failed"),
            "skipped": sum(1 for t in parsed if t["status"] == "skipped"),
            "errored": sum(1 for t in parsed if t["status"] == "errored"),
        },
    }


@app.get("/api/jobs/{job_id}/test-results", tags=["test-results"])
def get_test_results(job_id: int, db: Session = Depends(get_db)):
    """Get all test results for a job."""
    from ci_engine.server.models_extensions import TestRun

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    runs = db.query(TestRun).filter(TestRun.job_id == job_id).order_by(TestRun.id).all()
    return {
        "job_id": job_id,
        "total": len(runs),
        "results": [
            {
                "id": r.id,
                "test_name": r.test_name,
                "test_suite": r.test_suite,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "failure_message": r.failure_message,
            }
            for r in runs
        ],
    }


@app.get("/api/repositories/{repository:path}/flakiness", tags=["test-results"])
def get_flakiness(repository: str, db: Session = Depends(get_db)):
    """Get flakiness records for a repository, sorted by score descending."""
    from ci_engine.server.models_extensions import FlakynessRecord

    records = (
        db.query(FlakynessRecord)
        .filter(FlakynessRecord.repository == repository)
        .order_by(FlakynessRecord.flakiness_score.desc())
        .all()
    )
    return {
        "repository": repository,
        "total": len(records),
        "quarantined": sum(1 for r in records if r.quarantined),
        "records": [
            {
                "id": r.id,
                "test_suite": r.test_suite,
                "test_name": r.test_name,
                "total_runs": r.total_runs,
                "failure_count": r.failure_count,
                "pass_count": r.pass_count,
                "flakiness_score": round(r.flakiness_score, 4),
                "quarantined": r.quarantined,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            }
            for r in records
        ],
    }


# ===========================================================================
# Feature 9 — Build analytics endpoints
# ===========================================================================

@app.get("/api/analytics/builds/{build_id}/critical-path", tags=["analytics"])
def get_critical_path(build_id: int, db: Session = Depends(get_db)):
    """Return the critical path through a build's job DAG."""
    from ci_engine.core.analytics import compute_critical_path

    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    path = compute_critical_path(db, build_id)
    total_ms = sum(j["duration_ms"] for j in path)
    return {
        "build_id": build_id,
        "critical_path": path,
        "critical_path_duration_ms": total_ms,
    }


@app.get("/api/analytics/builds/{build_id}/metrics", tags=["analytics"])
def get_build_metrics(build_id: int, db: Session = Depends(get_db)):
    """Get materialized metrics for a specific build."""
    from ci_engine.server.models_extensions import BuildMetrics

    metrics = db.query(BuildMetrics).filter(BuildMetrics.build_id == build_id).first()
    if not metrics:
        raise HTTPException(status_code=404, detail="Metrics not yet available for this build")
    return {
        "build_id": metrics.build_id,
        "repository": metrics.repository,
        "branch": metrics.branch,
        "status": metrics.status,
        "queue_wait_ms": metrics.queue_wait_ms,
        "total_duration_ms": metrics.total_duration_ms,
        "job_count": metrics.job_count,
        "failed_job_count": metrics.failed_job_count,
        "agent_minutes_consumed": metrics.agent_minutes_consumed,
        "is_flaky_build": metrics.is_flaky_build,
        "created_at": metrics.created_at.isoformat() if metrics.created_at else None,
    }


@app.get("/api/analytics/repositories/{repository:path}/metrics", tags=["analytics"])
def get_repository_metrics(
    repository: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get daily aggregate metrics for a repository.

    Optional query params: ``start_date`` and ``end_date`` (YYYY-MM-DD).
    """
    from ci_engine.server.models_extensions import RepositoryMetrics

    query = db.query(RepositoryMetrics).filter(RepositoryMetrics.repository == repository)
    if start_date:
        query = query.filter(RepositoryMetrics.date >= start_date)
    if end_date:
        query = query.filter(RepositoryMetrics.date <= end_date)
    rows = query.order_by(RepositoryMetrics.date.desc()).all()

    return {
        "repository": repository,
        "rows": [
            {
                "date": r.date,
                "total_builds": r.total_builds,
                "passed_builds": r.passed_builds,
                "failed_builds": r.failed_builds,
                "success_rate": round(r.passed_builds / r.total_builds, 4) if r.total_builds else None,
                "avg_duration_ms": r.avg_duration_ms,
                "p95_duration_ms": r.p95_duration_ms,
                "total_agent_minutes": r.total_agent_minutes,
                "mttr_ms": r.mttr_ms,
            }
            for r in rows
        ],
    }


@app.get("/api/analytics/cost", tags=["analytics"])
def get_cost_summary(
    repository: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Summarize agent-minute consumption (proxy for compute cost).

    Filter by ``repository``, ``start_date``, ``end_date`` (YYYY-MM-DD).
    """
    from ci_engine.server.models_extensions import BuildMetrics

    query = db.query(BuildMetrics)
    if repository:
        query = query.filter(BuildMetrics.repository == repository)
    if start_date:
        query = query.filter(BuildMetrics.created_at >= start_date)
    if end_date:
        query = query.filter(BuildMetrics.created_at <= end_date)

    rows = query.all()
    total_agent_minutes = sum(r.agent_minutes_consumed or 0.0 for r in rows)
    total_builds = len(rows)

    return {
        "repository": repository,
        "start_date": start_date,
        "end_date": end_date,
        "total_builds": total_builds,
        "total_agent_minutes": round(total_agent_minutes, 3),
        "avg_agent_minutes_per_build": round(total_agent_minutes / total_builds, 3) if total_builds else 0.0,
    }


# ===========================================================================
# Feature 8 — Environment approval gates
# ===========================================================================

@app.get("/api/environment-approvals/pending", tags=["environments"])
def list_pending_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all pending environment approval requests."""
    from ci_engine.server.models_extensions import EnvironmentApproval

    pending = (
        db.query(EnvironmentApproval)
        .filter(EnvironmentApproval.status == "pending")
        .order_by(EnvironmentApproval.requested_at.asc())
        .all()
    )
    return {
        "total": len(pending),
        "approvals": [
            {
                "id": a.id,
                "build_id": a.build_id,
                "job_id": a.job_id,
                "environment_name": a.environment_name,
                "requested_at": a.requested_at.isoformat() if a.requested_at else None,
                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                "status": a.status,
            }
            for a in pending
        ],
    }


class ApproveRequest(BaseModel):
    approved_by: str
    comment: Optional[str] = None


class RejectRequest(BaseModel):
    rejected_by: str
    reason: Optional[str] = None


@app.post("/api/environment-approvals/{approval_id}/approve", tags=["environments"])
def approve_environment(
    approval_id: int,
    body: ApproveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve an environment gate, unblocking the waiting job."""
    from ci_engine.server.models_extensions import EnvironmentApproval

    approval = db.query(EnvironmentApproval).filter(EnvironmentApproval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval already in state: {approval.status}")

    # Check expiry
    if approval.expires_at and datetime.now(timezone.utc) > approval.expires_at.replace(tzinfo=timezone.utc):
        approval.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Approval request has expired")

    approval.status = "approved"
    approval.approved_at = datetime.now(timezone.utc)
    approval.approved_by = body.approved_by

    # Unblock the job
    job = db.query(Job).filter(Job.id == approval.job_id).first()
    if job and job.status == JobStatus.BLOCKED:
        job.status = JobStatus.PENDING

    db.commit()

    if job:
        broadcast_job_status(job.id, job.build_id, "pending")

    return {"status": "approved", "approval_id": approval_id, "job_id": approval.job_id}


@app.post("/api/environment-approvals/{approval_id}/reject", tags=["environments"])
def reject_environment(
    approval_id: int,
    body: RejectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject an environment gate, failing the waiting job."""
    from ci_engine.server.models_extensions import EnvironmentApproval

    approval = db.query(EnvironmentApproval).filter(EnvironmentApproval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval already in state: {approval.status}")

    approval.status = "rejected"
    approval.rejected_at = datetime.now(timezone.utc)
    approval.rejected_by = body.rejected_by
    approval.rejection_reason = body.reason

    # Fail the blocked job
    job = db.query(Job).filter(Job.id == approval.job_id).first()
    if job and job.status == JobStatus.BLOCKED:
        job.status = JobStatus.FAILED
        job.finished_at = datetime.now(timezone.utc)
        job.exit_code = -1

    db.commit()

    if job:
        broadcast_job_status(job.id, job.build_id, "failed")
        from ci_engine.core.scheduler import Scheduler
        Scheduler.check_and_update_dependencies(db, job.build_id)

    return {"status": "rejected", "approval_id": approval_id, "job_id": approval.job_id}


@app.get("/api/environment-approvals/{approval_id}", tags=["environments"])
def get_approval(approval_id: int, db: Session = Depends(get_db)):
    """Get a specific environment approval request."""
    from ci_engine.server.models_extensions import EnvironmentApproval

    approval = db.query(EnvironmentApproval).filter(EnvironmentApproval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return {
        "id": approval.id,
        "build_id": approval.build_id,
        "job_id": approval.job_id,
        "environment_name": approval.environment_name,
        "requested_at": approval.requested_at.isoformat() if approval.requested_at else None,
        "approved_at": approval.approved_at.isoformat() if approval.approved_at else None,
        "approved_by": approval.approved_by,
        "rejected_at": approval.rejected_at.isoformat() if approval.rejected_at else None,
        "rejected_by": approval.rejected_by,
        "rejection_reason": approval.rejection_reason,
        "status": approval.status,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
    }


# ===========================================================================
# Feature 10 — Agent token revocation
# ===========================================================================

@app.post("/api/agents/{agent_id}/revoke-token", tags=["agents"])
def revoke_agent_token(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke all active tokens for an agent (admin only)."""
    from ci_engine.server.models_extensions import AgentToken

    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Requires admin permission")

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    tokens = (
        db.query(AgentToken)
        .filter(AgentToken.agent_id == agent_id, AgentToken.revoked == False)  # noqa: E712
        .all()
    )
    count = len(tokens)
    for t in tokens:
        t.revoked = True
    db.commit()

    return {"status": "revoked", "agent_id": agent_id, "tokens_revoked": count}


# ===========================================================================
# Build Annotations  (Buildkite: buildkite-agent annotate)
# ===========================================================================

@app.post("/api/builds/{build_id}/annotations", response_model=BuildAnnotationResponse, tags=["builds"])
def upsert_build_annotation(
    build_id: int,
    body: BuildAnnotationCreate,
    db: Session = Depends(get_db),
):
    """Create or update a build annotation (upserted by context key)."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    now = datetime.now(timezone.utc)
    existing = (
        db.query(BuildAnnotation)
        .filter(BuildAnnotation.build_id == build_id, BuildAnnotation.context == body.context)
        .first()
    )
    if existing:
        existing.body_html = body.body_html
        existing.style = body.style
        existing.updated_at = now
        if body.created_by_job_id is not None:
            existing.created_by_job_id = body.created_by_job_id
        db.commit()
        db.refresh(existing)
        return existing
    else:
        annotation = BuildAnnotation(
            build_id=build_id,
            context=body.context,
            body_html=body.body_html,
            style=body.style,
            created_by_job_id=body.created_by_job_id,
            created_at=now,
        )
        db.add(annotation)
        db.commit()
        db.refresh(annotation)
        return annotation


@app.get("/api/builds/{build_id}/annotations", tags=["builds"])
def get_build_annotations(build_id: int, db: Session = Depends(get_db)):
    """Get all annotations for a build, ordered by creation time."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    annotations = (
        db.query(BuildAnnotation)
        .filter(BuildAnnotation.build_id == build_id)
        .order_by(BuildAnnotation.created_at.asc())
        .all()
    )
    return {
        "build_id": build_id,
        "total": len(annotations),
        "annotations": [
            {
                "id": a.id,
                "context": a.context,
                "body_html": a.body_html,
                "style": a.style,
                "created_by_job_id": a.created_by_job_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in annotations
        ],
    }


@app.delete("/api/builds/{build_id}/annotations/{context}", tags=["builds"])
def delete_build_annotation(
    build_id: int,
    context: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a specific build annotation by context."""
    annotation = (
        db.query(BuildAnnotation)
        .filter(BuildAnnotation.build_id == build_id, BuildAnnotation.context == context)
        .first()
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    db.delete(annotation)
    db.commit()
    return {"status": "deleted", "context": context}


# ===========================================================================
# Build Metadata KV  (Buildkite: buildkite-agent meta-data set/get)
# ===========================================================================

@app.post("/api/builds/{build_id}/metadata/{key}", response_model=BuildMetadataResponse, tags=["builds"])
def set_build_metadata(
    build_id: int,
    key: str,
    body: BuildMetadataSet,
    db: Session = Depends(get_db),
):
    """Set (upsert) a metadata key-value pair on a build."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    now = datetime.now(timezone.utc)
    existing = (
        db.query(BuildMetadata)
        .filter(BuildMetadata.build_id == build_id, BuildMetadata.key == key)
        .first()
    )
    if existing:
        existing.value = body.value
        existing.updated_at = now
        if body.set_by_job_id is not None:
            existing.set_by_job_id = body.set_by_job_id
        db.commit()
        db.refresh(existing)
        return existing
    else:
        meta = BuildMetadata(
            build_id=build_id,
            key=key,
            value=body.value,
            set_by_job_id=body.set_by_job_id,
            created_at=now,
        )
        db.add(meta)
        db.commit()
        db.refresh(meta)
        return meta


@app.get("/api/builds/{build_id}/metadata/{key}", tags=["builds"])
def get_build_metadata_key(build_id: int, key: str, db: Session = Depends(get_db)):
    """Get a specific metadata value by key. Returns 404 if not set."""
    meta = (
        db.query(BuildMetadata)
        .filter(BuildMetadata.build_id == build_id, BuildMetadata.key == key)
        .first()
    )
    if not meta:
        raise HTTPException(status_code=404, detail=f"Metadata key '{key}' not found")
    return {"build_id": build_id, "key": meta.key, "value": meta.value}


@app.get("/api/builds/{build_id}/metadata", tags=["builds"])
def list_build_metadata(build_id: int, db: Session = Depends(get_db)):
    """List all metadata key-value pairs for a build."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    rows = (
        db.query(BuildMetadata)
        .filter(BuildMetadata.build_id == build_id)
        .order_by(BuildMetadata.key.asc())
        .all()
    )
    return {
        "build_id": build_id,
        "metadata": {r.key: r.value for r in rows},
    }


# ===========================================================================
# Dynamic Pipeline Upload  (Buildkite: buildkite-agent pipeline upload)
# ===========================================================================

class PipelineUploadRequest(BaseModel):
    pipeline_yaml: str


@app.post("/api/builds/{build_id}/pipeline-upload", tags=["builds"])
def pipeline_upload(
    build_id: int,
    body: PipelineUploadRequest,
    db: Session = Depends(get_db),
):
    """Append new steps to a running build (dynamic pipeline generation).

    Equivalent to ``buildkite-agent pipeline upload``.  The uploaded YAML is
    parsed exactly like the original pipeline; new jobs are appended with
    step indexes continuing from the last existing job.
    """
    import json as _json
    from ci_engine.core.scheduler import Scheduler

    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    if build.status not in (BuildStatus.PENDING, BuildStatus.RUNNING):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot upload pipeline to a build in state '{build.status.value}'",
        )

    steps = parse_pipeline(body.pipeline_yaml)
    if not steps:
        raise HTTPException(status_code=422, detail="No steps parsed from uploaded pipeline YAML")

    # Continue step indexes from where the build left off
    existing_max = db.query(Job).filter(Job.build_id == build_id).count()
    new_jobs = []

    for i, step in enumerate(steps):
        env_vars = step.get("env")
        if isinstance(env_vars, dict):
            env_vars = _json.dumps(env_vars) if env_vars else None
        elif isinstance(env_vars, list):
            from ci_engine.core.pipeline import _list_env_to_dict  # type: ignore[attr-defined]
            env_vars = _json.dumps(_list_env_to_dict(env_vars)) or None
        else:
            env_vars = None

        depends_on = step.get("depends_on") or []
        if isinstance(depends_on, list):
            depends_on_str = ",".join(str(d) for d in depends_on) or None
        else:
            depends_on_str = str(depends_on) or None

        node_type = step.get("node_type") or step.get("step_type") or "command"
        if node_type in ("block", "manual", "approval", "gate"):
            node_type = "wait"

        coe = bool(step.get("continue_on_error") or step.get("continue-on-error", False))
        skip_condition = step.get("skip_condition")
        timeout_secs = step.get("timeout") or step.get("timeout_seconds") or 3600
        command = step.get("command") or ("" if node_type in ("wait", "block") else "echo done")

        job_status = (
            JobStatus.SKIPPED if skip_condition
            else JobStatus.BLOCKED if node_type in ("wait", "block")
            else JobStatus.PENDING
        )

        job = Job(
            build_id=build_id,
            step_index=existing_max + i,
            label=step.get("label", f"Dynamic Step {i + 1}"),
            command=command,
            status=job_status,
            env_vars=env_vars,
            working_dir=step.get("working_directory"),
            timeout_seconds=int(timeout_secs),
            max_retries=int(step.get("retry", 0)),
            priority=int(step.get("priority", 0)),
            required_tags=step.get("required_tags"),
            required_skills=step.get("required_skills"),
            matrix_vars=_json.dumps(step.get("matrix_vars")) if step.get("matrix_vars") else None,
            skip_condition=skip_condition,
            depends_on=depends_on_str,
            node_type=node_type,
            continue_on_error=coe,
            soft_fail=bool(step.get("soft_fail", False)),
            concurrency=step.get("concurrency"),
            concurrency_group=step.get("concurrency_group"),
            parallel_group_id=step.get("parallel_group_id"),
            parallel_index=step.get("parallel_index"),
            parallel_total=step.get("parallel_total"),
            queue=step.get("queue", "default"),
        )
        db.add(job)
        new_jobs.append(job)

    db.commit()

    # Trigger dependency re-evaluation so any immediately-runnable jobs unblock
    Scheduler.check_and_update_dependencies(db, build_id)

    # Broadcast updated build state
    broadcast_build_status(build_id, build.status.value, existing_max + len(new_jobs), 0, 0, 0)

    return {
        "status": "uploaded",
        "build_id": build_id,
        "jobs_added": len(new_jobs),
        "job_ids": [j.id for j in new_jobs],
    }
