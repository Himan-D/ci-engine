"""Add Buildkite parity features: build_annotations, build_metadata tables;
jobs.concurrency, jobs.concurrency_group, jobs.parallel_group_id,
jobs.parallel_index, jobs.soft_fail, jobs.queue;
agents.queue; builds.pr_number.

Revision ID: 004
Revises: 003
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # New tables
    # ------------------------------------------------------------------ #

    op.create_table(
        "build_annotations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("build_id", sa.Integer, sa.ForeignKey("builds.id"), nullable=False),
        sa.Column("context", sa.String(100), nullable=False),
        sa.Column("body_html", sa.Text, nullable=False),
        # success / warning / error / info
        sa.Column("style", sa.String(20), server_default="info"),
        sa.Column("created_by_job_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("build_id", "context", name="uq_build_annotation_context"),
    )
    op.create_index("ix_build_annotations_build_id", "build_annotations", ["build_id"])

    op.create_table(
        "build_metadata",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("build_id", sa.Integer, sa.ForeignKey("builds.id"), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("set_by_job_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("build_id", "key", name="uq_build_metadata_key"),
    )
    op.create_index("ix_build_metadata_build_id", "build_metadata", ["build_id"])

    # ------------------------------------------------------------------ #
    # New columns on existing tables
    # ------------------------------------------------------------------ #

    # builds: pr_number (for GitHub PR comment posting)
    with op.batch_alter_table("builds") as batch:
        batch.add_column(sa.Column("pr_number", sa.Integer, nullable=True))

    # jobs: concurrency, concurrency_group, parallel_group_id, parallel_index,
    #        soft_fail, queue
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("concurrency", sa.Integer, nullable=True))
        batch.add_column(sa.Column("concurrency_group", sa.String(200), nullable=True))
        batch.add_column(sa.Column("parallel_group_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("parallel_index", sa.Integer, nullable=True))
        batch.add_column(sa.Column("parallel_total", sa.Integer, nullable=True))
        batch.add_column(sa.Column("soft_fail", sa.Boolean, server_default=sa.text("0")))
        batch.add_column(sa.Column("queue", sa.String(100), server_default="default"))

    # agents: queue
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("queue", sa.String(100), server_default="default"))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("queue")

    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("queue")
        batch.drop_column("soft_fail")
        batch.drop_column("parallel_total")
        batch.drop_column("parallel_index")
        batch.drop_column("parallel_group_id")
        batch.drop_column("concurrency_group")
        batch.drop_column("concurrency")

    with op.batch_alter_table("builds") as batch:
        batch.drop_column("pr_number")

    op.drop_index("ix_build_metadata_build_id", "build_metadata")
    op.drop_table("build_metadata")
    op.drop_index("ix_build_annotations_build_id", "build_annotations")
    op.drop_table("build_annotations")
