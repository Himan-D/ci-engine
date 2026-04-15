# SPDX-License-Identifier: MIT
# CI Engine - FastAPI Server

import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

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
from ci_engine.server.auth import AuthService, User
from pydantic import BaseModel
from ci_engine.server.middleware import (
    create_access_token,
    create_refresh_token,
    verify_token,
    get_current_user,
)
from ci_engine.server.webhooks import WebhookService


app = FastAPI(title="CI Engine", version="0.1.0")

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


@app.on_event("startup")
def startup():
    init_db()


app.include_router(dashboard_router)


# Build endpoints
@app.post("/api/builds", response_model=BuildResponse)
def create_build(build_data: BuildCreate, db: Session = Depends(get_db)):
    """Create a new build from a pipeline definition."""
    build = Build(
        pipeline=build_data.pipeline,
        branch=build_data.branch,
        commit=build_data.commit,
        status=BuildStatus.PENDING,
    )
    db.add(build)
    db.commit()
    db.refresh(build)

    steps = parse_pipeline(build_data.pipeline)
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


# Agent endpoints
@app.post("/api/agents/register", response_model=AgentResponse)
def register_agent(agent_data: AgentCreate, db: Session = Depends(get_db)):
    """Register a new build agent."""
    existing = db.query(Agent).filter(Agent.name == agent_data.name).first()
    if existing:
        existing.status = AgentStatus.IDLE
        existing.last_seen = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    agent = Agent(
        name=agent_data.name,
        hostname=agent_data.hostname,
        ip_address="0.0.0.0",
        status=AgentStatus.IDLE,
        tags=",".join(agent_data.tags) if agent_data.tags else "",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
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
    job.started_at = datetime.utcnow()

    build = db.query(Build).filter(Build.id == job.build_id).first()
    if build and build.status == BuildStatus.PENDING:
        build.status = BuildStatus.RUNNING
        build.started_at = datetime.utcnow()

    db.commit()
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
    job.finished_at = datetime.utcnow()

    if job.agent:
        job.agent.status = AgentStatus.IDLE

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
                build.finished_at = datetime.utcnow()

    db.commit()

    if retry_triggered:
        return {
            "status": "completed",
            "exit_code": exit_code,
            "retry_triggered": True,
            "new_job_id": job.id,
        }

    return {"status": "completed", "exit_code": exit_code}


@app.post("/api/jobs/{job_id}/log")
def append_log(job_id: int, stream: str, line: str, db: Session = Depends(get_db)):
    """Append log line to job."""
    log = JobLog(job_id=job_id, stream=stream, line=line)
    db.add(log)
    db.commit()
    return {"status": "logged"}


# WebSocket for log streaming
@app.websocket("/ws/logs/{job_id}")
async def websocket_logs(websocket: WebSocket, job_id: int):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(data)
    except WebSocketDisconnect:
        pass


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Get CI engine statistics."""
    from datetime import datetime, timedelta

    now = datetime.utcnow()
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

    class Config:
        from_attributes = True


@app.post("/api/auth/register", response_model=UserResponse, tags=["auth"])
def register_user(user_data: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user."""
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


@app.get("/api/auth/me", response_model=UserResponse, tags=["auth"])
def get_me(current_user: User = Depends(get_current_user)):
    """Get current user info."""
    return current_user


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
    build.finished_at = datetime.utcnow()

    jobs = db.query(Job).filter(Job.build_id == build_id).all()
    for job in jobs:
        if job.status in (JobStatus.PENDING, JobStatus.ASSIGNED, JobStatus.RUNNING):
            job.status = JobStatus.CANCELED
            job.finished_at = datetime.utcnow()
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
    job.finished_at = datetime.utcnow()

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
            build.finished_at = datetime.utcnow()

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

    agent.last_seen = datetime.utcnow()
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


# Artifact endpoints
@app.post("/api/artifacts", response_model=ArtifactResponse, tags=["artifacts"])
async def upload_artifact(
    build_id: int,
    job_id: Optional[int] = None,
    filename: str = "",
    content_type: str = "application/octet-stream",
    db: Session = Depends(get_db),
):
    """Upload an artifact (placeholder - implement with actual file upload)."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    artifact = Artifact(
        build_id=build_id,
        job_id=job_id,
        filename=filename or "artifact",
        size=0,
        content_type=content_type,
        storage_key=f"builds/{build_id}/jobs/{job_id or 'none'}/{filename}",
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


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
    from datetime import timedelta

    cutoff_date = datetime.utcnow() - timedelta(days=days)

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
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)

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
