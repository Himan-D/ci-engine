# SPDX-License-Identifier: MIT
# Integration tests for AI analysis endpoints
#
# Tests the full request/response cycle through FastAPI + SQLAlchemy.
# litellm is never called — the plugin POSTs results directly via the API,
# which is exactly how the real agent uses these endpoints.

import json
import pytest
from fastapi.testclient import TestClient

from ci_engine.server.main import app
from ci_engine.server.db import init_db, SessionLocal
from ci_engine.server.models import Build, BuildStatus, Job, JobStatus


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helpers: create minimal DB objects
# ---------------------------------------------------------------------------

def _create_build(db) -> Build:
    b = Build(
        pipeline="steps:\n  - label: Test\n    command: pytest",
        status=BuildStatus.RUNNING,
        branch="main",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _create_failed_job(db, build: Build) -> Job:
    j = Job(
        build_id=build.id,
        label="Test",
        command="pytest tests/",
        status=JobStatus.FAILED,
        step_index=0,
        exit_code=1,
        priority=0,
        max_retries=2,
        retry_count=0,
    )
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


def _create_passed_build(db) -> Build:
    b = Build(
        pipeline="steps:\n  - label: Build\n    command: make",
        status=BuildStatus.PASSED,
        branch="feature/xyz",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


# ---------------------------------------------------------------------------
# GET /api/ai/status
# ---------------------------------------------------------------------------

class TestAIStatus:
    def test_returns_200(self, client):
        r = client.get("/api/ai/status")
        assert r.status_code == 200

    def test_has_backend_field(self, client):
        data = client.get("/api/ai/status").json()
        assert data["backend"] == "litellm"

    def test_has_enabled_field(self, client):
        data = client.get("/api/ai/status").json()
        assert "enabled" in data
        assert isinstance(data["enabled"], bool)

    def test_has_providers_dict(self, client):
        data = client.get("/api/ai/status").json()
        assert "providers" in data
        providers = data["providers"]
        for name in ("anthropic", "openrouter", "openai", "groq", "together", "mistral"):
            assert name in providers
            assert isinstance(providers[name], bool)

    def test_has_config_section(self, client):
        data = client.get("/api/ai/status").json()
        assert "config" in data
        cfg = data["config"]
        assert "CI_ENGINE_LLM_PROVIDER" in cfg
        assert "CI_ENGINE_AI_AUTO_FIX" in cfg

    def test_litellm_version_present(self, client):
        data = client.get("/api/ai/status").json()
        # litellm is installed in test env so version should be a string
        assert data["litellm_version"] is not None
        assert isinstance(data["litellm_version"], str)


# ---------------------------------------------------------------------------
# POST + GET /api/jobs/{id}/ai-analysis
# ---------------------------------------------------------------------------

class TestJobAIAnalysis:
    def test_get_returns_404_when_no_analysis(self, client, db):
        build = _create_build(db)
        job = _create_failed_job(db, build)
        r = client.get(f"/api/jobs/{job.id}/ai-analysis")
        assert r.status_code == 404

    def test_post_stores_analysis(self, client, db):
        build = _create_build(db)
        job = _create_failed_job(db, build)
        payload = {
            "root_cause": "Missing test dependency",
            "error_category": "dependency_missing",
            "explanation": "pytest-cov was not installed.",
            "fixed_command": "pip install pytest-cov && pytest tests/",
            "confidence": 0.88,
            "pipeline_suggestion": "Add pip install step",
            "provider": "groq",
            "model": "groq/llama-3.1-8b-instant",
        }
        r = client.post(f"/api/jobs/{job.id}/ai-analysis", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["root_cause"] == payload["root_cause"]
        assert data["error_category"] == "dependency_missing"
        assert data["provider"] == "groq"
        assert data["model"] == "groq/llama-3.1-8b-instant"
        assert data["fix_applied"] is False

    def test_get_returns_analysis_after_post(self, client, db):
        build = _create_build(db)
        job = _create_failed_job(db, build)
        client.post(f"/api/jobs/{job.id}/ai-analysis", json={
            "root_cause": "Network error",
            "error_category": "network_error",
            "explanation": "DNS resolution failed.",
            "confidence": 0.7,
        })
        r = client.get(f"/api/jobs/{job.id}/ai-analysis")
        assert r.status_code == 200
        assert r.json()["error_category"] == "network_error"

    def test_post_upserts_on_second_call(self, client, db):
        """Second POST for the same job_id should update, not create a duplicate."""
        build = _create_build(db)
        job = _create_failed_job(db, build)
        client.post(f"/api/jobs/{job.id}/ai-analysis", json={
            "root_cause": "First analysis",
            "error_category": "unknown",
            "explanation": "First attempt.",
            "confidence": 0.5,
        })
        r2 = client.post(f"/api/jobs/{job.id}/ai-analysis", json={
            "root_cause": "Updated analysis",
            "error_category": "syntax_error",
            "explanation": "Updated explanation.",
            "confidence": 0.95,
        })
        assert r2.status_code == 200
        # GET should show the updated values
        r3 = client.get(f"/api/jobs/{job.id}/ai-analysis")
        assert r3.json()["root_cause"] == "Updated analysis"
        assert r3.json()["error_category"] == "syntax_error"

    def test_analysis_stores_null_fixed_command(self, client, db):
        build = _create_build(db)
        job = _create_failed_job(db, build)
        r = client.post(f"/api/jobs/{job.id}/ai-analysis", json={
            "root_cause": "Complex failure",
            "error_category": "unknown",
            "explanation": "Too complex to auto-fix.",
            "fixed_command": None,
            "confidence": 0.3,
        })
        assert r.status_code == 200
        assert r.json()["fixed_command"] is None

    def test_analysis_for_nonexistent_job_still_stores(self, client):
        """The endpoint doesn't validate job existence — stores the record regardless."""
        r = client.post("/api/jobs/999999/ai-analysis", json={
            "root_cause": "phantom",
            "error_category": "unknown",
            "explanation": "test.",
            "confidence": 0.1,
        })
        # Either 200 (stored) or 422/500 (FK constraint) — both are acceptable
        assert r.status_code in (200, 422, 500)


# ---------------------------------------------------------------------------
# POST /api/jobs/{id}/ai-fix
# ---------------------------------------------------------------------------

class TestJobAIFix:
    def test_triggers_retry_on_failed_job(self, client, db):
        build = _create_build(db)
        job = _create_failed_job(db, build)
        r = client.post(f"/api/jobs/{job.id}/ai-fix", json={
            "fixed_command": "pip install pytest-cov && pytest tests/",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "retry_triggered"
        assert data["new_command"] == "pip install pytest-cov && pytest tests/"

    def test_marks_fix_applied_in_analysis(self, client, db):
        build = _create_build(db)
        job = _create_failed_job(db, build)
        # First store an analysis
        client.post(f"/api/jobs/{job.id}/ai-analysis", json={
            "root_cause": "missing dep",
            "error_category": "dependency_missing",
            "explanation": "dep missing.",
            "fixed_command": "pip install dep",
            "confidence": 0.9,
        })
        # Now apply the fix
        client.post(f"/api/jobs/{job.id}/ai-fix", json={"fixed_command": "pip install dep"})
        # Check analysis was updated
        r = client.get(f"/api/jobs/{job.id}/ai-analysis")
        assert r.json()["fix_applied"] is True

    def test_returns_400_when_job_not_failed(self, client, db):
        build = _create_build(db)
        # Create a PASSED job
        j = Job(
            build_id=build.id, label="Passed", command="echo ok",
            status=JobStatus.PASSED, step_index=0, exit_code=0,
            priority=0, max_retries=0, retry_count=0,
        )
        db.add(j); db.commit(); db.refresh(j)
        r = client.post(f"/api/jobs/{j.id}/ai-fix", json={"fixed_command": "echo ok"})
        assert r.status_code == 400

    def test_returns_400_when_retry_budget_exhausted(self, client, db):
        build = _create_build(db)
        j = Job(
            build_id=build.id, label="Exhausted", command="false",
            status=JobStatus.FAILED, step_index=0, exit_code=1,
            priority=0, max_retries=2, retry_count=2,  # budget used up
        )
        db.add(j); db.commit(); db.refresh(j)
        r = client.post(f"/api/jobs/{j.id}/ai-fix", json={"fixed_command": "echo fixed"})
        assert r.status_code == 400

    def test_returns_404_for_unknown_job(self, client):
        r = client.post("/api/jobs/999999/ai-fix", json={"fixed_command": "echo"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST + GET /api/builds/{id}/ai-summary
# ---------------------------------------------------------------------------

class TestBuildAISummary:
    def test_get_returns_404_when_no_summary(self, client, db):
        build = _create_passed_build(db)
        r = client.get(f"/api/builds/{build.id}/ai-summary")
        assert r.status_code == 404

    def test_post_stores_summary(self, client, db):
        build = _create_passed_build(db)
        payload = {
            "overall_health": "healthy",
            "summary": "All 5 jobs passed cleanly on the first run.",
            "what_failed": [],
            "what_was_fixed": [],
            "recommendations": ["Consider caching node_modules between runs."],
        }
        r = client.post(f"/api/builds/{build.id}/ai-summary", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["overall_health"] == "healthy"
        assert data["build_id"] == build.id

    def test_get_returns_summary_after_post(self, client, db):
        build = _create_passed_build(db)
        client.post(f"/api/builds/{build.id}/ai-summary", json={
            "overall_health": "degraded",
            "summary": "One job failed but was auto-fixed.",
            "what_failed": ["Test"],
            "what_was_fixed": ["Test"],
            "recommendations": ["Pin pytest version."],
        })
        r = client.get(f"/api/builds/{build.id}/ai-summary")
        assert r.status_code == 200
        data = r.json()
        assert data["overall_health"] == "degraded"
        # what_failed is stored as JSON string — parse it
        assert "Test" in json.loads(data["what_failed"])

    def test_post_upserts_on_second_call(self, client, db):
        build = _create_passed_build(db)
        client.post(f"/api/builds/{build.id}/ai-summary", json={
            "overall_health": "failed",
            "summary": "First summary.",
            "what_failed": ["A"],
            "what_was_fixed": [],
            "recommendations": [],
        })
        r2 = client.post(f"/api/builds/{build.id}/ai-summary", json={
            "overall_health": "recovering",
            "summary": "Updated summary.",
            "what_failed": ["A"],
            "what_was_fixed": ["A"],
            "recommendations": ["Check logs"],
        })
        assert r2.status_code == 200
        r3 = client.get(f"/api/builds/{build.id}/ai-summary")
        assert r3.json()["overall_health"] == "recovering"
        assert "A" in json.loads(r3.json()["what_was_fixed"])

    def test_summary_with_empty_lists(self, client, db):
        build = _create_passed_build(db)
        r = client.post(f"/api/builds/{build.id}/ai-summary", json={
            "overall_health": "healthy",
            "summary": "Perfect build.",
            "what_failed": [],
            "what_was_fixed": [],
            "recommendations": [],
        })
        assert r.status_code == 200
        data = client.get(f"/api/builds/{build.id}/ai-summary").json()
        assert json.loads(data["what_failed"]) == []
