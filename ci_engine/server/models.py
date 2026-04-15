# SPDX-License-Identifier: MIT
# CI Engine - Core models and database

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class BuildStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELED = "canceled"


class JobStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELED = "canceled"


class AgentStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


class Build(Base):
    __tablename__ = "builds"

    id = Column(Integer, primary_key=True)
    pipeline = Column(String(500), nullable=False)
    branch = Column(String(100), nullable=False)
    commit = Column(String(100), nullable=True)
    status = Column(SQLEnum(BuildStatus), default=BuildStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    jobs = relationship("Job", back_populates="build")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    build_id = Column(Integer, ForeignKey("builds.id"))
    step_index = Column(Integer, nullable=False)
    label = Column(String(200), nullable=False)
    command = Column(Text, nullable=False)
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    exit_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    build = relationship("Build", back_populates="jobs")
    agent = relationship("Agent", back_populates="jobs")
    logs = relationship("JobLog", back_populates="job")


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    hostname = Column(String(200), nullable=False)
    ip_address = Column(String(50), nullable=False)
    status = Column(SQLEnum(AgentStatus), default=AgentStatus.IDLE)
    tags = Column(String(500), nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=True)

    jobs = relationship("Job", back_populates="agent")


class JobLog(Base):
    __tablename__ = "job_logs"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    stream = Column(String(10), default="stdout")
    line = Column(Text, nullable=False)

    job = relationship("Job", back_populates="logs")


# Pydantic models for API
class BuildCreate(BaseModel):
    pipeline: str
    branch: str = "main"
    commit: Optional[str] = None


class BuildResponse(BaseModel):
    id: int
    pipeline: str
    branch: str
    commit: Optional[str]
    status: BuildStatus
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    jobs: list["JobResponse"] = []

    class Config:
        from_attributes = True


class JobResponse(BaseModel):
    id: int
    build_id: int
    step_index: int
    label: str
    command: str
    status: JobStatus
    exit_code: Optional[int]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True


class AgentCreate(BaseModel):
    name: str
    hostname: str
    tags: Optional[list[str]] = []


class AgentResponse(BaseModel):
    id: int
    name: str
    hostname: str
    ip_address: str
    status: AgentStatus
    tags: Optional[list[str]]
    registered_at: datetime
    last_seen: Optional[datetime]

    class Config:
        from_attributes = True


class LogStreamResponse(BaseModel):
    job_id: int
    timestamp: datetime
    stream: str
    line: str


# Update forward references
BuildResponse.model_rebuild()
