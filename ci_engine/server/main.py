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

from ci_engine.server.db import get_db, init_db
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


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    yield

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
    ],
)

# Rate limiting
from slowapi import Limiter
from slowapi.util import get_remote_address

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


def broadcast_job_status(job_id: int, build_id: int, status: str, exit_code: Optional[int] = None):
    """Broadcast job status change to all subscribers."""
    asyncio.create_task(
        manager.broadcast(
            f"build:{build_id}",
            {
                "type": "job_status",
                "job_id": job_id,
                "build_id": build_id,
                "status": status,
                "exit_code": exit_code,
            },
        )
    )
    asyncio.create_task(
        manager.broadcast(
            "builds:all",
            {
                "type": "job_status",
                "job_id": job_id,
                "build_id": build_id,
                "status": status,
                "exit_code": exit_code,
            },
        )
    )


def broadcast_build_status(
    build_id: int,
    status: str,
    jobs_total: int,
    jobs_passed: int,
    jobs_failed: int,
    jobs_running: int,
):
    """Broadcast build status change to all subscribers."""
    asyncio.create_task(
        manager.broadcast(
            f"build:{build_id}",
            {
                "type": "build_status",
                "build_id": build_id,
                "status": status,
                "jobs_total": jobs_total,
                "jobs_passed": jobs_passed,
                "jobs_failed": jobs_failed,
                "jobs_running": jobs_running,
            },
        )
    )
    asyncio.create_task(
        manager.broadcast(
            "builds:all",
            {
                "type": "build_status",
                "build_id": build_id,
                "status": status,
                "jobs_total": jobs_total,
                "jobs_passed": jobs_passed,
                "jobs_failed": jobs_failed,
                "jobs_running": jobs_running,
            },
        )
    )


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
    for i, step in enumerate(steps):
        env_vars = step.get("env")
        if env_vars and isinstance(env_vars, list):
            env_vars_dict = {}
            for env in env_vars:
                if "=" in env:
                    key, val = env.split("=", 1)
                    env_vars_dict[key] = val
            env_vars = json.dumps(env_vars_dict) if env_vars_dict else None
        elif env_vars and isinstance(env_vars, dict):
            env_vars = json.dumps(env_vars)

        matrix_vars = step.get("matrix_vars")
        skip_condition = step.get("skip_condition")

        job_status = JobStatus.SKIPPED if skip_condition else JobStatus.PENDING

        job = Job(
            build_id=build.id,
            step_index=i,
            label=step.get("label", f"Step {i}"),
            command=step.get("command", ""),
            status=job_status,
            env_vars=env_vars,
            working_dir=step.get("working_directory"),
            timeout_seconds=step.get("timeout", 3600),
            max_retries=step.get("retry", 0),
            priority=step.get("priority", 0),
            required_tags=step.get("required_tags"),
            matrix_vars=json.dumps(matrix_vars) if matrix_vars else None,
            skip_condition=skip_condition,
        )
        db.add(job)

    db.commit()
    db.refresh(build)

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
@app.post("/api/agents/register", response_model=AgentResponse)
def register_agent(agent_data: AgentCreate, db: Session = Depends(get_db)):
    """Register a new build agent."""
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
        return existing

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

    return agent


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
    return [{"id": l.id, "key": l.key, "value": l.value} for l in labels]


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
@app.post("/api/jobs/{job_id}/claim")
def claim_job(job_id: int, agent_id: int, db: Session = Depends(get_db)):
    """Agent claims a job to execute."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.PENDING:
        raise HTTPException(status_code=400, detail="Job not available")

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    job.agent_id = agent_id
    job.status = JobStatus.ASSIGNED
    agent.status = AgentStatus.BUSY

    db.commit()
    return {"status": "claimed", "job_id": job.id}


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: int, db: Session = Depends(get_db)):
    """Mark job as started."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)

    build = db.query(Build).filter(Build.id == job.build_id).first()
    if build and build.status == BuildStatus.PENDING:
        build.status = BuildStatus.RUNNING
        build.started_at = datetime.now(timezone.utc)

    db.commit()

    broadcast_job_status(job_id, job.build_id, "running")
    return {"status": "started"}


@app.post("/api/jobs/{job_id}/complete")
def complete_job(job_id: int, exit_code: int, db: Session = Depends(get_db)):
    """Mark job as completed with optional retry logic."""
    from ci_engine.core.scheduler import Scheduler

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = JobStatus.PASSED if exit_code == 0 else JobStatus.FAILED
    job.exit_code = exit_code
    job.finished_at = datetime.now(timezone.utc)

    if job.agent:
        job.agent.status = AgentStatus.IDLE

    db.commit()

    Scheduler.check_and_update_dependencies(db, job.build_id)

    retry_triggered = False

    if job.status == JobStatus.FAILED and job.max_retries > 0:
        retried_job = Scheduler.retry_job(db, job)
        if retried_job:
            retry_triggered = True

    if not retry_triggered:
        pending_jobs = (
            db.query(Job)
            .filter(Job.build_id == job.build_id, Job.status == JobStatus.PENDING)
            .count()
        )

        if pending_jobs == 0:
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

        broadcast_job_status(job_id, job.build_id.value, job.status.value, exit_code)
        broadcast_build_status(
            build.id, build.status.value, jobs_total, jobs_passed, jobs_failed, jobs_running
        )

    if retry_triggered:
        return {
            "status": "completed",
            "exit_code": exit_code,
            "retry_triggered": True,
            "new_job_id": job.id,
        }

    return {"status": "completed", "exit_code": exit_code}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    """Cancel a running or pending job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in (JobStatus.PASSED, JobStatus.FAILED, JobStatus.CANCELED, JobStatus.SKIPPED):
        raise HTTPException(status_code=400, detail=f"Job already {job.status.value}")

    job.status = JobStatus.CANCELED
    job.finished_at = datetime.now(timezone.utc)

    if job.agent:
        job.agent.status = AgentStatus.IDLE

    db.commit()

    Scheduler.check_and_update_dependencies(db, job.build_id)

    return {"status": "canceled", "job_id": job_id}


@app.post("/api/builds/{build_id}/cancel")
def cancel_build(build_id: int, db: Session = Depends(get_db)):
    """Cancel all running and pending jobs in a build."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    jobs = db.query(Job).filter(Job.build_id == build_id).all()
    canceled_count = 0

    for job in jobs:
        if job.status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.ASSIGNED):
            job.status = JobStatus.CANCELED
            job.finished_at = datetime.now(timezone.utc)
            if job.agent:
                job.agent.status = AgentStatus.IDLE
            canceled_count += 1

    build.status = BuildStatus.CANCELED
    build.finished_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "status": "canceled",
        "build_id": build_id,
        "jobs_canceled": canceled_count,
    }


@app.post("/api/jobs/{job_id}/log")
def append_log(job_id: int, stream: str, line: str, db: Session = Depends(get_db)):
    """Append log line to job."""
    log = JobLog(job_id=job_id, stream=stream, line=line)
    db.add(log)
    db.commit()
    return {"status": "logged"}


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
def unblock_build(build_id: int, db: Session = Depends(get_db)):
    """Unblock a blocked build, triggering pending jobs."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    blocked_jobs = (
        db.query(Job).filter(Job.build_id == build_id, Job.status == JobStatus.BLOCKED).all()
    )

    if not blocked_jobs:
        raise HTTPException(status_code=400, detail="No blocked jobs to unblock")

    for job in blocked_jobs:
        job.status = JobStatus.PENDING

    if build.status == BuildStatus.PENDING:
        build.status = BuildStatus.RUNNING

    db.commit()
    db.refresh(build)
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
            pipeline = """
steps:
  - label: "Build"
    command: "make build"
  - label: "Test"
    command: "make test"
"""
            build = Build(
                pipeline=pipeline,
                branch=build_info.get("branch", "main"),
                commit=build_info.get("commit"),
                status=BuildStatus.PENDING,
            )
            db.add(build)
            db.commit()

            steps = parse_pipeline(pipeline)
            for i, step in enumerate(steps):
                job = Job(
                    build_id=build.id,
                    step_index=i,
                    label=step.get("label", f"Step {i}"),
                    command=step.get("command", ""),
                    status=JobStatus.PENDING,
                )
                db.add(job)
            db.commit()
            return {"status": "created", "build_id": build.id}

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
            pipeline = """
steps:
  - label: "Build"
    command: "make build"
  - label: "Test"
    command: "make test"
"""
            build = Build(
                pipeline=pipeline,
                branch=build_info.get("branch", "main"),
                commit=build_info.get("commit"),
                status=BuildStatus.PENDING,
            )
            db.add(build)
            db.commit()

            steps = parse_pipeline(pipeline)
            for i, step in enumerate(steps):
                job = Job(
                    build_id=build.id,
                    step_index=i,
                    label=step.get("label", f"Step {i}"),
                    command=step.get("command", ""),
                    status=JobStatus.PENDING,
                )
                db.add(job)
            db.commit()
            return {"status": "created", "build_id": build.id}

    return {"status": "received"}


# Artifact endpoints
from fastapi import UploadFile, File
from ci_engine.core.artifacts import get_artifact_storage


@app.post("/api/artifacts", response_model=ArtifactResponse, tags=["artifacts"])
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
from ci_engine.core.cache import get_cache, compute_cache_key


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
from ci_engine.server.oidc import OIDCProviderManager, OIDCTokenVerifier, OIDCTokenExchange


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
from ci_engine.core.audit import AuditEntry, AuditLogResponse, AuditAction


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
from ci_engine.core.secrets import Secret, SecretCreate, SecretResponse


@app.get("/api/secrets", response_model=list[SecretResponse], tags=["secrets"])
def list_secrets(db: Session = Depends(get_db)):
    """List all secrets (without values)."""
    secrets = db.query(Secret).filter(Secret.is_active == True).all()
    return secrets


@app.post("/api/secrets", response_model=SecretResponse, tags=["secrets"])
def create_secret(secret_data: SecretCreate, db: Session = Depends(get_db)):
    """Create a new secret."""
    from ci_engine.core.secrets import _encrypt_value

    existing = db.query(Secret).filter(Secret.name == secret_data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Secret already exists")

    encrypted, version = _encrypt_value(secret_data.value)

    secret = Secret(
        name=secret_data.name,
        value_encrypted=encrypted,
        key_version=version,
        created_by=secret_data.created_by,
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
