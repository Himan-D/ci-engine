# SPDX-License-Identifier: MIT
# CI Engine - Database setup

import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from ci_engine.server.models import Base


def get_database_url() -> str:
    """Get database URL from environment or use SQLite default."""
    return os.environ.get("DATABASE_URL", "sqlite:///ci_engine.db")


def create_engine_func():
    """Create database engine with connection pooling."""
    url = get_database_url()

    if url.startswith("sqlite"):
        # NullPool: each request gets its own connection — no shared cursor
        # state across concurrent threads, preventing IndexError on relationship loads.
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=NullPool,
        )
        # Enable WAL mode for better concurrent read/write performance
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(conn, _record):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        return engine

    if url.startswith("postgresql"):
        return create_engine(
            url,
            poolclass=QueuePool,
            pool_size=20,
            max_overflow=30,
            pool_pre_ping=True,
            pool_recycle=3600,
        )

    return create_engine(url, pool_pre_ping=True)


engine = create_engine_func()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables."""
    # Register all model modules so their tables are included in create_all()
    import ci_engine.server.models_ai        # noqa: F401
    import ci_engine.server.models_extensions  # noqa: F401
    import ci_engine.server.auth             # noqa: F401
    import ci_engine.core.secrets            # noqa: F401
    import ci_engine.core.audit              # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Add columns that may be missing from existing DBs (idempotent ALTER TABLE)
    with engine.connect() as conn:
        for col_sql in [
            "ALTER TABLE jobs ADD COLUMN node_type VARCHAR(50) DEFAULT 'command'",
            "ALTER TABLE jobs ADD COLUMN continue_on_error BOOLEAN DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN security_policy TEXT",
            "ALTER TABLE jobs ADD COLUMN claimed_at DATETIME",
            "ALTER TABLE jobs ADD COLUMN environment VARCHAR(200)",
            # Buildkite parity columns
            "ALTER TABLE jobs ADD COLUMN soft_fail BOOLEAN DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN concurrency INTEGER",
            "ALTER TABLE jobs ADD COLUMN concurrency_group VARCHAR(200)",
            "ALTER TABLE jobs ADD COLUMN parallel_group_id VARCHAR(100)",
            "ALTER TABLE jobs ADD COLUMN parallel_index INTEGER",
            "ALTER TABLE jobs ADD COLUMN parallel_total INTEGER",
            "ALTER TABLE jobs ADD COLUMN queue VARCHAR(100) DEFAULT 'default'",
            "ALTER TABLE agents ADD COLUMN queue VARCHAR(100) DEFAULT 'default'",
            "ALTER TABLE builds ADD COLUMN pr_number INTEGER",
            "ALTER TABLE job_ai_analyses ADD COLUMN provider TEXT",
            "ALTER TABLE job_ai_analyses ADD COLUMN model TEXT",
            "ALTER TABLE builds ADD COLUMN external_repo VARCHAR(500)",
            "ALTER TABLE builds ADD COLUMN head_sha VARCHAR(100)",
            "ALTER TABLE secrets ADD COLUMN repository VARCHAR(500)",
            "ALTER TABLE environment_groups ADD COLUMN requires_approval BOOLEAN DEFAULT 0",
            "ALTER TABLE environment_groups ADD COLUMN allowed_branches TEXT",
            "ALTER TABLE environment_groups ADD COLUMN allowed_roles TEXT",
            "ALTER TABLE environment_groups ADD COLUMN auto_approve_timeout_minutes INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(text(col_sql))
                conn.commit()
            except Exception:
                pass  # column already exists


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_health() -> bool:
    """Check database connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
