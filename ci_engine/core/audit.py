# SPDX-License-Identifier: MIT
# CI Engine - Audit logging

import os
import json
from datetime import datetime, timezone
from typing import Optional
from enum import Enum

from sqlalchemy import Column, Integer, String, DateTime, Text
from pydantic import BaseModel, ConfigDict

from ci_engine.server.models import Base


class AuditAction(str, Enum):
    """Audit action types."""

    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_DELETE = "user.delete"

    BUILD_CREATE = "build.create"
    BUILD_START = "build.start"
    BUILD_CANCEL = "build.cancel"
    BUILD_UNBLOCK = "build.unblock"
    BUILD_COMPLETE = "build.complete"

    JOB_CLAIM = "job.claim"
    JOB_START = "job.start"
    JOB_COMPLETE = "job.complete"
    JOB_CANCEL = "job.cancel"
    JOB_RETRY = "job.retry"

    AGENT_REGISTER = "agent.register"
    AGENT_HEARTBEAT = "agent.heartbeat"
    AGENT_OFFLINE = "agent.offline"

    SECRET_CREATE = "secret.create"
    SECRET_UPDATE = "secret.update"
    SECRET_DELETE = "secret.delete"

    WEBHOOK_CREATE = "webhook.create"
    WEBHOOK_UPDATE = "webhook.update"
    WEBHOOK_DELETE = "webhook.delete"
    WEBHOOK_TRIGGER = "webhook.trigger"

    ARTIFACT_UPLOAD = "artifact.upload"
    ARTIFACT_DELETE = "artifact.delete"

    TOKEN_CREATE = "token.create"
    TOKEN_REVOKE = "token.revoke"

    ADMIN_CLEANUP = "admin.cleanup"
    ADMIN_CONFIG_CHANGE = "admin.config_change"


class AuditLevel(str, Enum):
    """Audit log levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SECURITY = "security"


class AuditEntry(Base):
    """Audit log entry model."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    action = Column(String(100), nullable=False)
    level = Column(String(20), default=AuditLevel.INFO.value, nullable=False)
    user_id = Column(Integer, nullable=True)
    username = Column(String(100), nullable=True)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(String(100), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)


class AuditLogCreate(BaseModel):
    """Schema for creating audit log entries."""

    action: str
    level: str = AuditLevel.INFO.value
    user_id: Optional[int] = None
    username: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[dict] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditLogResponse(BaseModel):
    """Schema for audit log responses."""

    id: int
    timestamp: datetime
    action: str
    level: str
    user_id: Optional[int]
    username: Optional[str]
    resource_type: Optional[str]
    resource_id: Optional[str]
    details: Optional[dict]
    ip_address: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class AuditLogger:
    """Audit logging service."""

    def __init__(self, db_session=None):
        self.db = db_session
        self._buffer = []
        self._flush_size = int(os.environ.get("AUDIT_FLUSH_SIZE", "10"))
        self._enabled = os.environ.get("AUDIT_ENABLED", "true").lower() == "true"

    def log(
        self,
        action: str,
        level: str = AuditLevel.INFO.value,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """Log an audit event."""
        if not self._enabled:
            return

        entry = AuditLogCreate(
            action=action,
            level=level,
            user_id=user_id,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self._buffer.append(entry)

        if len(self._buffer) >= self._flush_size:
            self.flush()

    def flush(self):
        """Flush buffered logs to database."""
        if not self._buffer or not self.db:
            return

        try:
            for entry_data in self._buffer:
                entry = AuditEntry(
                    timestamp=datetime.now(timezone.utc),
                    action=entry_data.action,
                    level=entry_data.level,
                    user_id=entry_data.user_id,
                    username=entry_data.username,
                    resource_type=entry_data.resource_type,
                    resource_id=entry_data.resource_id,
                    details=json.dumps(entry_data.details) if entry_data.details else None,
                    ip_address=entry_data.ip_address,
                    user_agent=entry_data.user_agent,
                )
                self.db.add(entry)
            self.db.commit()
            self._buffer = []
        except Exception:
            self._buffer = []

    def log_security_event(self, action: str, details: dict, user_id: Optional[int] = None):
        """Log a security-related event."""
        self.log(action, AuditLevel.SECURITY, user_id=user_id, details=details)

    def log_build_event(self, build_id: int, action: str, user_id: Optional[int] = None):
        """Log a build-related event."""
        self.log(
            action,
            AuditLevel.INFO,
            user_id=user_id,
            resource_type="build",
            resource_id=str(build_id),
        )

    def log_agent_event(self, agent_id: int, action: str):
        """Log an agent-related event."""
        self.log(
            action,
            AuditLevel.INFO,
            resource_type="agent",
            resource_id=str(agent_id),
        )

    def log_job_event(self, job_id: int, action: str, user_id: Optional[int] = None):
        """Log a job-related event."""
        self.log(
            action,
            AuditLevel.INFO,
            user_id=user_id,
            resource_type="job",
            resource_id=str(job_id),
        )


def get_audit_logger(db_session=None) -> AuditLogger:
    """Get an audit logger instance."""
    return AuditLogger(db_session)
