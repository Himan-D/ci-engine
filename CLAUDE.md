# CI Engine - AI Assistant Context

This file provides context for AI assistants working on the CI Engine project.

## Project Overview

CI Engine is a production-ready CI/CD platform (Buildkite alternative) with:
- Distributed agent-based architecture
- Container isolation (Docker/Podman)
- S3 artifact storage
- OIDC/SSO authentication (AWS, GCP, Azure)
- Structured logging + OpenTelemetry tracing
- Dead Letter Queue for failed jobs
- Circuit breakers for resilience
- Audit logging for compliance
- Kubernetes deployment manifests

## Key Files

| File | Purpose |
|------|---------|
| `ci_engine/server/main.py` | FastAPI server, all API endpoints |
| `ci_engine/server/models.py` | SQLAlchemy models |
| `ci_engine/agent/agent.py` | Build agent with container execution |
| `ci_engine/core/executor.py` | Command execution |
| `ci_engine/core/container.py` | Docker executor |
| `ci_engine/core/artifacts.py` | S3 artifact storage |
| `ci_engine/core/secrets.py` | Fernet encrypted secrets |
| `ci_engine/core/notifications.py` | Slack/Discord/Email |
| `Dockerfile.server` | Server container image |
| `k8s/` | Kubernetes manifests |

## Critical Rules for AI Agents

### MUST DO
1. **Always run tests** before committing: `pytest tests/ -v`
2. **Always run linting** before committing: `ruff check ci_engine/ tests/`
3. **Never break existing tests**
4. **Use type hints** on all functions
5. **Add tests** for new features

### MUST NOT
1. **Never commit directly to main/master** - always use PR
2. **Never skip tests** even for small changes
3. **Never use `shell=True`** in subprocess calls - use `shlex.split()`
4. **Never hardcode secrets** - use environment variables

## Testing Commands

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/unit/test_pipeline.py -v

# Run with coverage
pytest tests/ --cov=ci_engine --cov-report=term-missing

# Lint
ruff check ci_engine/ tests/
ruff format ci_engine/ tests/
```

## Deployment

```bash
# Docker
docker build -f Dockerfile.server -t ci-engine .
docker run -p 8000:8000 ci-engine

# Kubernetes
kubectl apply -k k8s/
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|--------------|
| `DATABASE_URL` | Yes | PostgreSQL connection |
| `CI_ENGINE_JWT_SECRET_KEY` | Yes | JWT signing key |
| `CI_ENGINE_S3_BUCKET` | No | S3 artifact bucket |
| `SLACK_WEBHOOK_URL` | No | Slack notifications |
| `AWS_OIDC_ISSUER` | No | OIDC auth |

## Common Issues

### If tests fail
1. Check imports - ensure all modules exist
2. Check environment variables are set
3. Run `ruff check --fix` to auto-fix lint issues

### If Docker build fails
1. Check Dockerfile paths are correct
2. Ensure all dependencies in pyproject.toml
3. Check base image is available

### If agent doesn't work
1. Check server is running first
2. Check agent can reach server URL
3. Check Docker is available on agent machine
