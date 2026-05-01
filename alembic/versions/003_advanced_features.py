"""Add advanced feature tables: agent_tokens, environment_approvals,
test_runs, flakiness_records, build_metrics, repository_metrics.
Also adds columns: Build.head_sha, Build.external_repo,
EnvironmentGroup.requires_approval / allowed_branches / allowed_roles,
Job.security_policy, Secret.repository.

Revision ID: 003
Revises: 002
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # New tables
    # ------------------------------------------------------------------ #

    op.create_table(
        "agent_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Integer, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("token_hash", sa.String(256), unique=True, nullable=False),
        sa.Column("allowed_endpoints", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("revoked", sa.Boolean, server_default=sa.text("0")),
        sa.Column("last_used", sa.DateTime, nullable=True),
    )
    op.create_index("ix_agent_tokens_agent_id", "agent_tokens", ["agent_id"])

    op.create_table(
        "environment_approvals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("build_id", sa.Integer, sa.ForeignKey("builds.id"), nullable=False),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("environment_name", sa.String(100), nullable=False),
        sa.Column("requested_at", sa.DateTime, nullable=True),
        sa.Column("approved_at", sa.DateTime, nullable=True),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("rejected_at", sa.DateTime, nullable=True),
        sa.Column("rejected_by", sa.String(100), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("expires_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "test_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("build_id", sa.Integer, sa.ForeignKey("builds.id"), nullable=False),
        sa.Column("repository", sa.String(500), nullable=True),
        sa.Column("test_name", sa.String(500), nullable=False),
        sa.Column("test_suite", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("failure_message", sa.Text, nullable=True),
        sa.Column("failure_type", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_test_runs_job_id", "test_runs", ["job_id"])
    op.create_index("ix_test_runs_build_id", "test_runs", ["build_id"])
    op.create_index("ix_test_runs_repository", "test_runs", ["repository"])

    op.create_table(
        "flakiness_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("repository", sa.String(500), nullable=True),
        sa.Column("test_suite", sa.String(500), nullable=True),
        sa.Column("test_name", sa.String(500), nullable=False),
        sa.Column("total_runs", sa.Integer, server_default="0"),
        sa.Column("failure_count", sa.Integer, server_default="0"),
        sa.Column("pass_count", sa.Integer, server_default="0"),
        sa.Column("flakiness_score", sa.Float, server_default="0.0"),
        sa.Column("quarantined", sa.Boolean, server_default=sa.text("0")),
        sa.Column("first_seen", sa.DateTime, nullable=True),
        sa.Column("last_seen", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("repository", "test_suite", "test_name"),
    )

    op.create_table(
        "build_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("build_id", sa.Integer, sa.ForeignKey("builds.id"), nullable=False),
        sa.Column("repository", sa.String(500), nullable=True),
        sa.Column("branch", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("queue_wait_ms", sa.Float, nullable=True),
        sa.Column("total_duration_ms", sa.Float, nullable=True),
        sa.Column("job_count", sa.Integer, server_default="0"),
        sa.Column("failed_job_count", sa.Integer, server_default="0"),
        sa.Column("agent_minutes_consumed", sa.Float, server_default="0.0"),
        sa.Column("is_flaky_build", sa.Boolean, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("build_id"),
    )
    op.create_index("ix_build_metrics_build_id", "build_metrics", ["build_id"])
    op.create_index("ix_build_metrics_repository", "build_metrics", ["repository"])

    op.create_table(
        "repository_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("repository", sa.String(500), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("total_builds", sa.Integer, server_default="0"),
        sa.Column("passed_builds", sa.Integer, server_default="0"),
        sa.Column("failed_builds", sa.Integer, server_default="0"),
        sa.Column("avg_duration_ms", sa.Float, nullable=True),
        sa.Column("p95_duration_ms", sa.Float, nullable=True),
        sa.Column("total_agent_minutes", sa.Float, server_default="0.0"),
        sa.Column("mttr_ms", sa.Float, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("repository", "date"),
    )
    op.create_index("ix_repository_metrics_repository", "repository_metrics", ["repository"])

    # ------------------------------------------------------------------ #
    # New columns on existing tables
    # ------------------------------------------------------------------ #

    # builds: external_repo, head_sha
    with op.batch_alter_table("builds") as batch:
        batch.add_column(sa.Column("external_repo", sa.String(500), nullable=True))
        batch.add_column(sa.Column("head_sha", sa.String(100), nullable=True))

    # jobs: security_policy, claimed_at
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("security_policy", sa.Text, nullable=True))
        batch.add_column(sa.Column("claimed_at", sa.DateTime, nullable=True))
        batch.add_column(sa.Column("environment", sa.String(200), nullable=True))

    # secrets: repository
    with op.batch_alter_table("secrets") as batch:
        batch.add_column(sa.Column("repository", sa.String(500), nullable=True))

    # environment_groups: protection columns
    with op.batch_alter_table("environment_groups") as batch:
        batch.add_column(sa.Column("requires_approval", sa.Boolean, server_default=sa.text("0")))
        batch.add_column(sa.Column("allowed_branches", sa.Text, nullable=True))
        batch.add_column(sa.Column("allowed_roles", sa.Text, nullable=True))
        batch.add_column(sa.Column("auto_approve_timeout_minutes", sa.Integer, server_default="0"))


def downgrade() -> None:
    op.drop_table("repository_metrics")
    op.drop_table("build_metrics")
    op.drop_table("flakiness_records")
    op.drop_table("test_runs")
    op.drop_table("environment_approvals")
    op.drop_table("agent_tokens")

    with op.batch_alter_table("environment_groups") as batch:
        batch.drop_column("auto_approve_timeout_minutes")
        batch.drop_column("allowed_roles")
        batch.drop_column("allowed_branches")
        batch.drop_column("requires_approval")

    with op.batch_alter_table("secrets") as batch:
        batch.drop_column("repository")

    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("environment")
        batch.drop_column("claimed_at")
        batch.drop_column("security_policy")

    with op.batch_alter_table("builds") as batch:
        batch.drop_column("head_sha")
        batch.drop_column("external_repo")
