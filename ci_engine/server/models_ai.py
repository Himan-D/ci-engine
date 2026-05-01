# SPDX-License-Identifier: MIT
# CI Engine - AI analysis models

from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from ci_engine.server.models import Base


class JobAIAnalysis(Base):
    """Stores LLM analysis results for a failed job."""

    __tablename__ = "job_ai_analyses"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), unique=True, nullable=False, index=True)
    root_cause = Column(Text, nullable=True)
    error_category = Column(Text, nullable=True)  # dependency_missing | syntax_error | test_failure | etc.
    explanation = Column(Text, nullable=True)
    fixed_command = Column(Text, nullable=True)
    fix_applied = Column(Boolean, default=False)
    confidence = Column(Float, nullable=True)
    pipeline_suggestion = Column(Text, nullable=True)
    provider = Column(Text, nullable=True)   # which LLM provider was used
    model = Column(Text, nullable=True)      # exact model name
    analyzed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    job = relationship("Job", backref="ai_analysis", uselist=False)


class BuildAISummary(Base):
    """Stores LLM build summary after a build completes."""

    __tablename__ = "build_ai_summaries"

    id = Column(Integer, primary_key=True, index=True)
    build_id = Column(Integer, ForeignKey("builds.id"), unique=True, nullable=False, index=True)
    overall_health = Column(Text, nullable=True)  # healthy | degraded | failed | recovering
    summary = Column(Text, nullable=True)
    what_failed = Column(Text, nullable=True)   # JSON list stored as text
    what_was_fixed = Column(Text, nullable=True)  # JSON list stored as text
    recommendations = Column(Text, nullable=True)  # JSON list stored as text
    generated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    build = relationship("Build", backref="ai_summary", uselist=False)
