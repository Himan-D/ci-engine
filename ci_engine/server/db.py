# SPDX-License-Identifier: MIT
# CI Engine - Database setup

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool, QueuePool

from ci_engine.server.models import Base


def get_database_url() -> str:
    """Get database URL from environment or use SQLite default."""
    return os.environ.get("DATABASE_URL", "sqlite:///ci_engine.db")


def create_engine_func():
    """Create database engine with connection pooling."""
    url = get_database_url()

    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_pre_ping=True,
        )

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
    Base.metadata.create_all(bind=engine)


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
