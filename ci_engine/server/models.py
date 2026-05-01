# SPDX-License-Identifier: MIT
# CI Engine - Core models and database

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, field_validator
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
    SOFT_FAILED = "soft_failed"
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
    pr_number = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
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
    depends_on = Column(String(500), nullable=True)
    node_type = Column(String(50), nullable=True, default="command")  # command, wait, block, parallel, matrix
    continue_on_error = Column(Boolean, default=False)
    soft_fail = Column(Boolean, default=False)
    concurrency = Column(Integer, nullable=True)
    concurrency_group = Column(String(200), nullable=True)
    parallel_group_id = Column(String(100), nullable=True)
    parallel_index = Column(Integer, nullable=True)
    parallel_total = Column(Integer, nullable=True)
    queue = Column(String(100), default="default")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
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
    pool_id = Column(Integer, ForeignKey("agent_pools.id"), nullable=True)
    version = Column(String(50), nullable=True)
    drain_mode = Column(Boolean, default=False)
    queue = Column(String(100), default="default")
    registered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime, nullable=True)

    jobs = relationship("Job", back_populates="agent")
    agent_skills = relationship("AgentSkill", back_populates="agent", cascade="all, delete-orphan")
    pool = relationship("AgentPool", back_populates="agents")


class AgentPool(Base):
    __tablename__ = "agent_pools"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(500), nullable=True)
    max_agents = Column(Integer, default=0)
    min_agents = Column(Integer, default=0)
    scaling_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    agents = relationship("Agent", back_populates="pool")


class AgentLabel(Base):
    __tablename__ = "agent_labels"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    key = Column(String(100), nullable=False)
    value = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    stream = Column(String(10), default="stdout")
    line = Column(Text, nullable=False)

    job = relationship("Job", back_populates="logs")


class EnvironmentGroup(Base):
    __tablename__ = "environment_groups"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    variables = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=True)


class PipelineTrigger(Base):
    __tablename__ = "pipeline_triggers"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    pipeline = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BuildAnnotation(Base):
    """Styled HTML annotation posted by a job to the build page.

    Multiple annotations can exist per build; each is keyed by *context*
    (e.g. "coverage", "lint", "security"). Upsert by (build_id, context).
    """

    __tablename__ = "build_annotations"

    id = Column(Integer, primary_key=True)
    build_id = Column(Integer, ForeignKey("builds.id"), nullable=False, index=True)
    # Unique key per build — upsert replaces when context matches
    context = Column(String(100), nullable=False)
    body_html = Column(Text, nullable=False)
    # success / warning / error / info
    style = Column(String(20), default="info")
    created_by_job_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=True)


class BuildMetadata(Base):
    """Arbitrary key-value pairs set by agents during a build.

    Equivalent to Buildkite's ``buildkite-agent meta-data set KEY VALUE``.
    Keys are unique per build; setting an existing key overwrites it.
    """

    __tablename__ = "build_metadata"

    id = Column(Integer, primary_key=True)
    build_id = Column(Integer, ForeignKey("builds.id"), nullable=False, index=True)
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    set_by_job_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=True)


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
    node_type: Optional[str] = "command"
    continue_on_error: bool = False
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)

    @field_validator("env_vars", "matrix_vars", mode="before")
    @classmethod
    def parse_json_field(cls, v: Any) -> Any:
        if v is None:
            return {}
        if isinstance(v, (dict, list)):
            return v
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return {}
        return {}


class AgentCreate(BaseModel):
    name: str
    hostname: str
    tags: Optional[list[str]] = []
    skills: Optional[list[str]] = []
    pool_id: Optional[int] = None


class AgentResponse(BaseModel):
    id: int
    name: str
    hostname: str
    ip_address: str
    status: AgentStatus
    tags: Optional[list[str]] = []
    skills: Optional[list[str]] = []
    pool_id: Optional[int] = None
    drain_mode: bool = False
    registered_at: datetime
    last_seen: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("tags", "skills", mode="before")
    @classmethod
    def csv_to_list(cls, v: Any) -> list[str]:
        """Convert comma-separated string stored in DB to a list."""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return []


class AgentPoolCreate(BaseModel):
    name: str
    description: Optional[str] = None
    max_agents: int = 0
    min_agents: int = 0
    scaling_enabled: bool = False


class AgentPoolResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    max_agents: int
    min_agents: int
    scaling_enabled: bool
    agent_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class AgentLabelCreate(BaseModel):
    key: str
    value: str


class AgentLabelResponse(BaseModel):
    id: int
    key: str
    value: str
    created_at: datetime

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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


class EnvironmentGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    variables: Optional[dict] = None


class EnvironmentGroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PipelineTriggerCreate(BaseModel):
    name: str
    pipeline: str


class PipelineTriggerResponse(BaseModel):
    id: int
    name: str
    pipeline: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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


# ---- BuildAnnotation Pydantic models ----

class BuildAnnotationCreate(BaseModel):
    context: str = "default"
    body_html: str
    style: str = "info"  # success / warning / error / info
    created_by_job_id: Optional[int] = None


class BuildAnnotationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    build_id: int
    context: str
    body_html: str
    style: str
    created_by_job_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# ---- BuildMetadata Pydantic models ----

class BuildMetadataSet(BaseModel):
    value: str
    set_by_job_id: Optional[int] = None


class BuildMetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    build_id: int
    key: str
    value: str
    set_by_job_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# Update forward references
BuildResponse.model_rebuild()
