# SPDX-License-Identifier: MIT
# CI Engine - Test fixtures and utilities

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ci_engine.server.models import Base
import ci_engine.server.models_ai  # noqa: F401 — registers AI tables with Base


@pytest.fixture(scope="session")
def engine():
    """Create test database engine."""
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    return test_engine


@pytest.fixture
def db_session(engine):
    """Create a new database session for each test."""
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_pipeline():
    """Sample pipeline YAML for testing."""
    return """
steps:
  - label: "Build"
    command: "echo 'Building...'"
    env:
      - BUILD=true
  - label: "Test"
    command: "echo 'Testing...'"
    plugins:
      - some-plugin#v1.0
  - label: "Deploy"
    command: "echo 'Deploying...'"
    skip: false
"""


@pytest.fixture
def sample_build_data():
    """Sample build creation data."""
    return {
        "pipeline": """
steps:
  - label: "Test"
    command: "echo test"
""",
        "branch": "main",
        "commit": "abc123",
    }


@pytest.fixture
def sample_agent_data():
    """Sample agent registration data."""
    return {
        "name": "test-agent-1",
        "hostname": "test-host",
        "tags": ["linux", "docker"],
    }
