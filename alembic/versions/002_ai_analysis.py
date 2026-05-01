"""Add AI analysis tables

Revision ID: 002_ai_analysis
Revises: 001_initial
Create Date: 2026-04-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_ai_analysis"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_ai_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("error_category", sa.Text(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("fixed_command", sa.Text(), nullable=True),
        sa.Column("fix_applied", sa.Boolean(), default=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("pipeline_suggestion", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_job_ai_analyses_id", "job_ai_analyses", ["id"])
    op.create_index("ix_job_ai_analyses_job_id", "job_ai_analyses", ["job_id"])

    op.create_table(
        "build_ai_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("build_id", sa.Integer(), sa.ForeignKey("builds.id"), nullable=False),
        sa.Column("overall_health", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("what_failed", sa.Text(), nullable=True),
        sa.Column("what_was_fixed", sa.Text(), nullable=True),
        sa.Column("recommendations", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("build_id"),
    )
    op.create_index("ix_build_ai_summaries_id", "build_ai_summaries", ["id"])
    op.create_index("ix_build_ai_summaries_build_id", "build_ai_summaries", ["build_id"])


def downgrade() -> None:
    op.drop_index("ix_build_ai_summaries_build_id", "build_ai_summaries")
    op.drop_index("ix_build_ai_summaries_id", "build_ai_summaries")
    op.drop_table("build_ai_summaries")
    op.drop_index("ix_job_ai_analyses_job_id", "job_ai_analyses")
    op.drop_index("ix_job_ai_analyses_id", "job_ai_analyses")
    op.drop_table("job_ai_analyses")
