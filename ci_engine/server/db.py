# SPDX-License-Identifier: MIT
# CI Engine - Database setup

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ci_engine.server.models import Base


def get_database_url() -> str:
    """Get database URL from environment or use SQLite default."""
    return os.environ.get("DATABASE_URL", "sqlite:///ci_engine.db")


def create_engine_func():
    """Create database engine."""
    url = get_database_url()

    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    return create_engine(url)


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
