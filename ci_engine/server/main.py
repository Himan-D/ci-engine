# SPDX-License-Identifier: MIT
# CI Engine - FastAPI Server

import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from ci_engine.server.db import get_db, init_db
from ci_engine.server.models import (
    Base,
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
)
from ci_engine.core.pipeline import parse_pipeline


app = FastAPI(title="CI Engine", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


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
    """Mark job as completed."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = JobStatus.PASSED if exit_code == 0 else JobStatus.FAILED
    job.exit_code = exit_code
    job.finished_at = datetime.utcnow()

    if job.agent:
        job.agent.status = AgentStatus.IDLE

    pending_jobs = (
        db.query(Job).filter(Job.build_id == job.build_id, Job.status == JobStatus.PENDING).count()
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
