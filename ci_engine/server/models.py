# SPDX-License-Identifier: MIT
# CI Engine - Core models and database

from datetime import datetime
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Enum as SQLEnum, Boolean
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
    BLOCKED = "blocked"
    SKIPPED = "skipped"


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
    repository = Column(String(500), nullable=True)
    git_ref = Column(String(100), nullable=True)
    clone_depth = Column(Integer, nullable=True)
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
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=0)
    timeout_seconds = Column(Integer, default=3600)
    priority = Column(Integer, default=0)
    required_tags = Column(String(200), nullable=True)
    env_vars = Column(Text, nullable=True)
    working_dir = Column(String(500), nullable=True)
    matrix_vars = Column(Text, nullable=True)
    skip_condition = Column(String(500), nullable=True)
    required_skills = Column(String(500), nullable=True)
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
    skills = Column(Text, nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=True)

    jobs = relationship("Job", back_populates="agent")
    agent_skills = relationship("AgentSkill", back_populates="agent", cascade="all, delete-orphan")


class AgentSkill(Base):
    __tablename__ = "agent_skills"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    name = Column(String(100), nullable=False)
    level = Column(Integer, default=1)
    enabled = Column(Boolean, default=True)
    category = Column(String(50), nullable=True)
    version = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    extra_data = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="agent_skills")


class SkillDefinition(Base):
    __tablename__ = "skill_definitions"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    category = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    detect_command = Column(String(500), nullable=True)
    min_version = Column(String(50), nullable=True)
    required_tools = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)


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
    repository: Optional[str] = None
    git_ref: Optional[str] = "main"
    clone_depth: Optional[int] = None


class BuildResponse(BaseModel):
    id: int
    pipeline: str
    branch: str
    commit: Optional[str]
    repository: Optional[str]
    git_ref: Optional[str]
    status: BuildStatus
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    jobs: list["JobResponse"] = []

    model_config = ConfigDict(from_attributes=True)


class JobResponse(BaseModel):
    id: int
    build_id: int
    step_index: int
    label: str
    command: str
    status: JobStatus
    exit_code: Optional[int]
    retry_count: int
    max_retries: int
    timeout_seconds: int
    priority: int
    required_tags: Optional[str]
    env_vars: Optional[dict[str, str]] = {}
    working_dir: Optional[str]
    matrix_vars: Optional[dict[str, Any]] = {}
    skip_condition: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class AgentCreate(BaseModel):
    name: str
    hostname: str
    tags: Optional[list[str]] = []
    skills: Optional[list[str]] = []


class AgentResponse(BaseModel):
    id: int
    name: str
    hostname: str
    ip_address: str
    status: AgentStatus
    tags: Optional[list[str]]
    skills: Optional[list[str]] = []
    registered_at: datetime
    last_seen: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class LogStreamResponse(BaseModel):
    job_id: int
    timestamp: datetime
    stream: str
    line: str


class WebhookConfig(Base):
    __tablename__ = "webhook_configs"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    events = Column(String(200), nullable=False)
    secret = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(Integer, primary_key=True)
    build_id = Column(Integer, ForeignKey("builds.id"))
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    filename = Column(String(200), nullable=False)
    size = Column(Integer, nullable=False)
    content_type = Column(String(100), nullable=False)
    storage_key = Column(String(500), nullable=False)
    checksum = Column(String(64), nullable=True)
    storage_location = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# Pydantic models for webhooks
class WebhookCreate(BaseModel):
    name: str
    url: str
    events: list[str]
    secret: Optional[str] = None


class WebhookResponse(BaseModel):
    id: int
    name: str
    url: str
    events: list[str]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class AgentSkillCreate(BaseModel):
    name: str
    level: int = 1
    category: Optional[str] = None
    version: Optional[str] = None


class AgentSkillUpdate(BaseModel):
    level: Optional[int] = None
    enabled: Optional[bool] = None
    version: Optional[str] = None


class AgentSkillResponse(BaseModel):
    id: int
    name: str
    level: int
    enabled: bool
    category: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AgentSkillsUpdate(BaseModel):
    skills: list[AgentSkillCreate]


class SkillDefinitionResponse(BaseModel):
    id: int
    name: str
    display_name: str
    category: str
    description: Optional[str]
    min_version: Optional[str]
    tags: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class SkillCategoryResponse(BaseModel):
    category: str
    display_name: str
    skill_count: int


# Pydantic models for artifacts
class ArtifactResponse(BaseModel):
    id: int
    build_id: int
    job_id: Optional[int]
    filename: str
    size: int
    content_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Update forward references
BuildResponse.model_rebuild()
