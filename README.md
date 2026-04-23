# CI Engine

A modern, extensible CI/CD platform built with Python, designed for AI agent collaboration and distributed build execution.

[![CI](https://github.com/Himan-D/ci-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Himan-D/ci-engine/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Table of Contents

- [What is CI Engine?](#what-is-ci-engine)
- [Architecture](#architecture)
- [Features](#features)
- [Quick Start](#quick-start)
- [Development Setup](#development-setup)
- [Codebase Tour](#codebase-tour)
- [Extending CI Engine](#extending-ci-engine)
  - [Plugin System](#plugin-system)
  - [Agent SDK](#agent-sdk)
  - [Custom Middleware](#custom-middleware)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Testing](#testing)
- [Code Style](#code-style)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [Roadmap](#roadmap)

---

## What is CI Engine?

CI Engine is a self-hosted CI/CD platform similar to Buildkite, GitHub Actions, or GitLab CI. It enables you to:

- Define build pipelines in YAML
- Execute jobs on distributed agents
- Run builds in isolated Docker containers
- Stream logs in real-time
- Manage secrets securely
- Scale agents automatically

**Key differentiators:**

- **AI-First Design**: Built with AI agent collaboration in mind
- **Extensible Plugin System**: Hook into job execution lifecycle
- **Custom Agent SDK**: Create specialized agents for your needs
- **Modern Tech Stack**: FastAPI, SQLAlchemy 2.0, Pydantic v2

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CI Engine                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐     ┌──────────────────┐     ┌──────────────────┐  │
│  │  Client  │────▶│  FastAPI Server  │────▶│  Build Agents     │  │
│  │   (UI)   │     │   (REST API)     │     │  (Execute Jobs)   │  │
│  └──────────┘     └────────┬─────────┘     └────────┬─────────┘  │
│                            │                          │           │
│                            ▼                          ▼           │
│                    ┌───────────────┐           ┌──────────────┐   │
│                    │  PostgreSQL   │           │  Containers   │   │
│                    │  (Metadata)   │           │ (Docker/Pod)  │   │
│                    └───────────────┘           └──────────────┘   │
│                            │                                        │
│                            ▼                                        │
│                    ┌───────────────┐                                 │
│                    │     Redis     │                                 │
│                    │   (Cache)     │                                 │
│                    └───────────────┘                                 │
│                            │                                        │
│                            ▼                                        │
│                    ┌───────────────┐                                 │
│                    │      S3       │                                 │
│                    │  (Artifacts)  │                                 │
│                    └───────────────┘                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Description |
|-----------|-------------|
| **Server** | FastAPI application handling REST APIs, WebSocket connections, job scheduling |
| **Agents** | Lightweight workers that poll the server for jobs and execute them in isolated environments |
| **Database** | PostgreSQL for persistent storage of builds, jobs, agents, and configuration |
| **Redis** | Caching, session management, and rate limiting |
| **S3** | Artifact storage with presigned URLs |

---

## Features

### Pipeline Orchestration
- YAML-based pipeline definitions
- Job dependencies with `depends_on`
- Matrix expansion for parallel builds
- Conditional execution (`if:` expressions)
- Wait steps and manual approval gates
- Automatic retry on failure
- Timeout handling

### Agent Management
- Agent registration and heartbeat
- Tag-based job matching
- Skill detection and assignment
- Parallel job execution
- Drain mode for graceful shutdown
- Resource monitoring (CPU/memory limits)

### Container Support
- Docker and Podman execution
- Configurable CPU and memory limits
- Volume mounting
- Network isolation
- Fallback to local execution

### Observability
- Real-time log streaming via WebSocket
- Prometheus metrics endpoint
- OpenTelemetry tracing
- Structured JSON logging
- Audit logging

### Security
- JWT authentication with access/refresh tokens
- Role-based access control (Admin, Developer, Viewer)
- Fernet-encrypted secrets storage
- SSH key management for agents
- OIDC/SSO support (AWS, GCP, Azure)
- HMAC webhook signature verification

### Integrations
- GitHub webhooks
- GitLab webhooks
- Slack notifications
- Discord notifications
- Email notifications
- S3-compatible artifact storage

---

## Quick Start

### Using Docker Compose (Recommended for Development)

```bash
# Clone and start
git clone https://github.com/Himan-D/ci-engine.git
cd ci-engine
docker-compose up

# Server available at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### Manual Setup

```bash
# Create virtual environment
cd ci-engine
uv venv --python 3.12
source .venv/bin/activate

# Install dependencies
uv pip install -e ".[dev]"

# Start the server
uvicorn ci_engine.server.main:app --reload --port 8000

# In another terminal, start an agent
python -m ci_engine.agent.agent --server http://localhost:8000 --name build-agent-1
```

### Create Your First Build

```bash
# Using curl
curl -X POST http://localhost:8000/api/builds \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": "steps:\n  - label: \"Hello\"\n    command: \"echo Hello, CI Engine!\"",
    "branch": "main"
  }'

# View build status
curl http://localhost:8000/api/builds
```

---

## Development Setup

### Prerequisites

- Python 3.12+
- PostgreSQL 15+ (or use SQLite for development)
- Redis 7+ (optional, for caching)
- Docker (optional, for container execution)

### Environment Variables

Create a `.env` file in the project root:

```bash
# Required for production
DATABASE_URL=postgresql://user:pass@localhost/ci_engine
CI_ENGINE_JWT_SECRET_KEY=your-secret-key-here

# Optional - Database (uses SQLite by default)
# DATABASE_URL=sqlite:///./ci_engine.db

# Optional - Artifacts
CI_ENGINE_S3_BUCKET=your-bucket
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
AWS_REGION=us-east-1

# Optional - Encryption
CI_ENGINE_FERNET_KEY=base64-encoded-fernet-key

# Optional - Notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
DISCORD_WEBHOOK_URL=https://discord.com/...

# Optional - Logging
LOG_LEVEL=DEBUG
LOG_FORMAT=json
```

### Running Tests

```bash
# Run all tests
.venv/bin/python -m pytest tests/ -v

# Run specific test file
.venv/bin/python -m pytest tests/unit/test_pipeline.py -v

# Run with coverage
.venv/bin/python -m pytest tests/ --cov=ci_engine --cov-report=term-missing
```

### Code Quality

```bash
# Lint code
ruff check ci_engine/ tests/

# Format code
ruff format ci_engine/ tests/
```

### Verify Imports

```bash
# Test all major imports
python -c "from ci_engine.agent.agent import Agent; from ci_engine.agent.sdk import CIEngineAgent; from ci_engine.server.main import app; print('All imports OK')"
```

---

## Codebase Tour

```
ci_engine/
├── __init__.py              # Package entry point
├── cli.py                   # Command-line interface
│
├── agent/                   # Build agent implementation
│   ├── agent.py            # Core agent with job polling and execution
│   ├── git.py              # Git operations (clone, checkout)
│   ├── plugins.py          # Plugin interface and registry
│   ├── middleware.py       # Middleware chain for job transformation
│   ├── sdk.py              # Public SDK for custom agents
│   ├── skills.py           # Skill auto-detection system
│   └── builtins.py         # Built-in plugins
│
├── core/                    # Core business logic
│   ├── artifacts.py        # S3 artifact storage
│   ├── audit.py           # Audit logging service
│   ├── cache.py           # Build cache system
│   ├── container.py       # Docker/Podman executor
│   ├── environments.py     # Environment variable groups
│   ├── executor.py         # Command execution engine
│   ├── logging.py          # Structured logging
│   ├── metrics.py          # Prometheus metrics
│   ├── notifications.py    # Slack/Discord/Email
│   ├── pipeline.py         # YAML pipeline parsing
│   ├── scaler.py          # Auto-scaling service
│   ├── scheduler.py        # Job scheduling logic
│   ├── secrets.py          # Fernet encryption
│   ├── ssh_keys.py         # SSH key management
│   └── triggers.py         # Cron-based triggers
│
└── server/                  # FastAPI server
    ├── main.py             # API routes and WebSocket handlers
    ├── models.py           # SQLAlchemy models
    ├── db.py              # Database connection
    ├── auth.py            # JWT authentication
    ├── middleware.py       # Rate limiting
    ├── dashboard.py        # Web UI routes
    ├── webhooks.py         # GitHub/GitLab webhooks
    └── github_oauth.py     # GitHub OAuth
```

### Module Responsibilities

| Module | Purpose |
|--------|---------|
| `agent/agent.py` | Main agent loop, job polling, execution, heartbeat |
| `core/pipeline.py` | Parse YAML into job definitions with matrix expansion |
| `core/scheduler.py` | Match jobs to agents, handle dependencies |
| `core/executor.py` | Run commands in isolated workspaces |
| `core/container.py` | Docker/Podman container management |
| `server/main.py` | REST endpoints, WebSocket streams, auth |

---

## Extending CI Engine

### Plugin System

CI Engine provides a powerful plugin system that allows you to hook into the job execution lifecycle.

#### Available Hooks

| Hook | When Called | Use Case |
|------|-------------|----------|
| `on_register` | When agent registers with server | Initialize resources, load config |
| `pre_execute` | Before job execution | Modify command, inject env vars |
| `post_execute` | After job completes | Send notifications, cleanup |
| `on_error` | When job fails | Alert teams, create issues |
| `on_heartbeat` | Periodic heartbeat | Update metrics, check health |
| `on_shutdown` | Agent shutting down | Graceful cleanup |

#### Creating a Plugin

```python
from ci_engine.agent.sdk import CIEnginePlugin, JobContext, JobResult

class MyPlugin(CIEnginePlugin):
    name = "my-custom-plugin"
    version = "1.0.0"
    
    def pre_execute(self, context: JobContext) -> JobContext:
        """Called before job execution."""
        # Add environment variables
        context.env_vars["MY_CUSTOM_VAR"] = "value"
        # Modify command
        context.command = f"echo 'Starting...' && {context.command}"
        return context
    
    def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
        """Called after job execution."""
        if result.exit_code != 0:
            print(f"Job {context.job_id} failed with exit code {result.exit_code}")
        return result
```

#### Registering Plugins

```python
from ci_engine.agent.sdk import CIEngineAgent

agent = CIEngineAgent(
    name="my-agent",
    server_url="http://localhost:8000",
    plugins=[MyPlugin()],
)
agent.run()
```

### Agent SDK

The Agent SDK provides a user-friendly interface for creating custom agents.

```python
from ci_engine.agent.sdk import CIEngineAgent, CIEnginePlugin

class SlackNotifyPlugin(CIEnginePlugin):
    name = "slack-notify"
    
    def post_execute(self, context, result):
        if result.exit_code == 0:
            send_slack_message("Build passed!")
        else:
            send_slack_message("Build failed!")
        return result

# Create agent with plugin
agent = CIEngineAgent(
    name="slack-agent",
    plugins=[SlackNotifyPlugin()],
    tags=["docker", "production"],
    max_parallel_jobs=4,
)
agent.run()
```

### Custom Middleware

Middleware transforms jobs before execution. Use it for logging, validation, or transformation.

```python
from ci_engine.agent.sdk import (
    MiddlewareChain,
    TransformMiddleware,
    MiddlewareOrder,
)

class AddTimestampMiddleware(TransformMiddleware):
    name = "timestamp"
    order = MiddlewareOrder.PRE
    
    def transform(self, job: dict) -> dict:
        job["env_vars"]["JOB_STARTED_AT"] = str(datetime.utcnow())
        return job

# Use middleware
agent = CIEngineAgent(
    name="my-agent",
    middleware=[AddTimestampMiddleware()],
)
agent.run()
```

### Built-in Plugins

CI Engine includes several built-in plugins:

| Plugin | Purpose |
|--------|---------|
| `LoggingPlugin` | Structured job logging |
| `MetricsPlugin` | Prometheus metrics collection |
| `CachePlugin` | Build cache management |
| `EnvironmentPlugin` | Environment variable injection |
| `ValidationPlugin` | Job validation before execution |
| `TimeoutPlugin` | Timeout enforcement |

---

## API Reference

### Core Endpoints

#### Builds

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/builds` | Create a new build |
| `GET` | `/api/builds` | List all builds |
| `GET` | `/api/builds/{id}` | Get build details |
| `POST` | `/api/builds/{id}/cancel` | Cancel a build |
| `GET` | `/api/builds/{id}/artifacts` | Get build artifacts |

#### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/jobs/{id}/claim` | Claim a job |
| `POST` | `/api/jobs/{id}/start` | Start job execution |
| `POST` | `/api/jobs/{id}/complete` | Complete the job |
| `POST` | `/api/jobs/{id}/log` | Append log output |
| `WS` | `/ws/jobs/{id}/logs` | Stream job logs |

#### Agents

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/agents/register` | Register new agent |
| `GET` | `/api/agents` | List all agents |
| `GET` | `/api/agents/{id}` | Get agent details |
| `POST` | `/api/agents/{id}/heartbeat` | Send heartbeat |
| `POST` | `/api/agents/{id}/drain` | Enter drain mode |
| `GET` | `/api/agents/{id}/skills` | Get agent skills |

#### Secrets

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/secrets` | Create secret |
| `GET` | `/api/secrets` | List secrets |
| `GET` | `/api/secrets/{id}` | Get secret metadata |
| `PUT` | `/api/secrets/{id}` | Update secret |
| `DELETE` | `/api/secrets/{id}` | Delete secret |
| `POST` | `/api/secrets/{id}/rotate` | Rotate secret |

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/register` | Register new user |
| `POST` | `/api/auth/login` | Login |
| `POST` | `/api/auth/refresh` | Refresh token |
| `POST` | `/api/auth/tokens` | Create API token |
| `GET` | `/api/auth/me` | Get current user |

### Webhooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/webhooks/github` | GitHub webhook |
| `POST` | `/api/webhooks/gitlab` | GitLab webhook |
| `GET` | `/api/webhooks` | List webhooks |
| `POST` | `/api/webhooks` | Create webhook |

For full API documentation, visit `http://localhost:8000/docs` when the server is running.

---

## Configuration

### Environment Variables

#### Required

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `CI_ENGINE_JWT_SECRET_KEY` | JWT signing key |

#### Optional - Artifacts

| Variable | Description |
|----------|-------------|
| `CI_ENGINE_S3_BUCKET` | S3 bucket for artifacts |
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_REGION` | AWS region |
| `S3_ENDPOINT_URL` | S3-compatible endpoint |

#### Optional - Notifications

| Variable | Description |
|----------|-------------|
| `SLACK_WEBHOOK_URL` | Slack webhook URL |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL |
| `SMTP_HOST` | SMTP server |
| `SMTP_PORT` | SMTP port |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP password |
| `EMAIL_FROM` | Sender email |
| `EMAIL_TO` | Recipient emails |

#### Optional - Security

| Variable | Description |
|----------|-------------|
| `CI_ENGINE_FERNET_KEY` | Fernet encryption key |
| `AWS_OIDC_ISSUER` | AWS OIDC issuer URL |
| `GCP_OIDC_ISSUER` | GCP OIDC issuer URL |
| `AZURE_TENANT_ID` | Azure tenant ID |

#### Optional - Agent

| Variable | Description |
|----------|-------------|
| `CI_SERVER_URL` | Server URL (agent) |
| `CI_AGENT_NAME` | Agent name (agent) |
| `CI_WORKSPACE` | Workspace directory |
| `CI_CONTAINER_RUNTIME` | docker or podman |
| `CI_ENGINE_DEFAULT_IMAGE` | Default container image |

#### Optional - Observability

| Variable | Description |
|----------|-------------|
| `LOG_LEVEL` | DEBUG, INFO, WARNING, ERROR |
| `LOG_FORMAT` | json for JSON logs |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint |
| `OTEL_SERVICE_NAME` | Service name for tracing |

---

## Testing

### Writing Tests

CI Engine uses pytest with the following conventions:

```python
# tests/unit/test_my_feature.py
import pytest

class TestMyFeature:
    """Tests for my feature."""
    
    @pytest.fixture
    def my_fixture(self):
        """Create fixture for testing."""
        return MyClass()
    
    def test_basic_case(self, my_fixture):
        """Test basic functionality."""
        result = my_fixture.do_something()
        assert result == expected
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific file
pytest tests/unit/test_pipeline.py -v

# With coverage
pytest tests/ --cov=ci_engine --cov-report=term-missing

# Integration tests only
pytest tests/integration/ -v
```

### Test Organization

```
tests/
├── conftest.py          # Shared fixtures
├── unit/
│   ├── test_auth.py
│   ├── test_executor.py
│   ├── test_pipeline.py
│   └── test_plugins.py
└── integration/
    └── test_api.py
```

---

## Code Style

### Conventions

- **Indentation**: 4 spaces
- **Line Length**: Max 100 characters
- **Type Hints**: Required for all functions
- **Docstrings**: Required for public APIs
- **Imports**: Grouped (stdlib, third-party, local)

### Import Organization

```python
# Standard library
import json
from datetime import datetime, timezone

# Third-party
from fastapi import FastAPI
from sqlalchemy.orm import Session

# Local
from ci_engine.core.pipeline import PipelineParser
from ci_engine.server.models import Build
```

### Naming Conventions

| Type | Convention |
|------|------------|
| Classes | PascalCase (`MyClass`) |
| Functions | snake_case (`my_function`) |
| Constants | UPPER_SNAKE_CASE |
| Private methods | `_leading_underscore` |

### Error Handling

Use specific exceptions:

```python
# Good
try:
    result = parse_pipeline(content)
except yaml.YAMLError as e:
    raise PipelineParseError(f"Invalid YAML: {e}") from e

# Avoid
try:
    result = parse_pipeline(content)
except:
    pass
```

---

## Deployment

### Docker

```bash
# Build images
docker build -f Dockerfile.server -t ci-engine/server .
docker build -f Dockerfile.agent -t ci-engine/agent .

# Run with docker-compose
docker-compose -f docker-compose.yml up
```

### Kubernetes

```bash
# Install Helm chart
helm install ci-engine ./helm/ci-engine

# Or with custom values
helm install ci-engine ./helm/ci-engine -f my-values.yaml
```

### Production Checklist

- [ ] Set secure `DATABASE_URL`
- [ ] Configure `CI_ENGINE_JWT_SECRET_KEY`
- [ ] Set up `CI_ENGINE_FERNET_KEY`
- [ ] Configure backup for PostgreSQL
- [ ] Set up monitoring/alerting
- [ ] Configure TLS/SSL
- [ ] Review rate limiting settings
- [ ] Set up log aggregation

---

## Contributing

### Process

1. **Fork** the repository
2. **Create a branch** for your feature (`git checkout -b feature/my-feature`)
3. **Write tests** for your changes
4. **Implement** your changes
5. **Run tests** to ensure everything passes
6. **Commit** with descriptive message
7. **Push** to your fork
8. **Open a Pull Request**

### Commit Messages

```
Add <feature_name>

Description of what was added and why.

Tests:
- Unit tests for X
- Integration tests for Y

Co-authored-by: Your Name <you@example.com>
```

### Code Review Criteria

- All tests pass
- No lint errors
- Type hints present
- Docstrings added for public APIs
- Tests cover the new functionality

---

## Pipeline Examples

### Simple Pipeline

```yaml
# examples/simple-pipeline.yaml
steps:
  - label: "Build"
    command: "npm install && npm run build"
  - label: "Test"
    command: "npm test"
  - label: "Deploy"
    command: "npm run deploy"
```

### With Dependencies

```yaml
# examples/dependencies.yaml
name: dependency-pipeline

steps:
  - label: "Setup"
    command: "make setup"
    id: setup

  - label: "Backend Tests"
    command: "make test-backend"
    depends_on: setup

  - label: "Frontend Tests"
    command: "make test-frontend"
    depends_on: setup

  - label: "Integration Tests"
    command: "make test-integration"
    depends_on:
      - backend-tests
      - frontend-tests
```

### With Docker Container

```yaml
steps:
  - label: "Build Docker Image"
    command: "docker build -t myapp ."
    container:
      image: "docker:20.10"
      volumes:
        - /var/run/docker.sock:/var/run/docker.sock
```

### With Matrix Expansion

```yaml
steps:
  - label: "Test {:matrix.python}"
    command: "python {:matrix.python} -m pytest"
    matrix:
      python:
        - "3.10"
        - "3.11"
        - "3.12"
```

---

## Roadmap

### In Progress
- [ ] OIDC provider verification
- [ ] Remote cache backend (S3)
- [ ] Pipeline visualization UI

### Planned
- [ ] GitHub Actions compatibility layer
- [ ] GitLab CI importer
- [ ] Advanced job retry policies
- [ ] Pipeline templates library
- [ ] Integration with external dashboards

### Future Ideas
- [ ] Distributed locking for multi-region
- [ ] Plugin marketplace
- [ ] SaaS offering
- [ ] Native Kubernetes operator

---

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

- [GitHub Issues](https://github.com/Himan-D/ci-engine/issues)
- [Documentation](https://github.com/Himan-D/ci-engine#readme)
- [Discussions](https://github.com/Himan-D/ci-engine/discussions)