# CI Engine - Buildkite Alternative

A modern CI/CD platform built with AI-first vibecoding approach.

## What is CI Engine?

CI Engine is a continuous integration/continuous deployment platform that runs build pipelines on distributed agents, similar to Buildkite but designed with AI agent collaboration in mind.

## Core Features

1. **Pipeline Orchestration** - Define builds in code (YAML)
2. **Agent Pool Management** - Register and manage build agents
3. **Job Distribution** - Distribute work across available agents
4. **Real-time Logging** - Stream build logs in real-time
5. **Build Artifacts** - Store build artifacts
6. **Web Dashboard** - Monitor and manage builds
7. **Authentication** - User management and API tokens
8. **Secret Management** - Encrypted secrets storage
9. **GitHub Webhooks** - Trigger builds from GitHub events
10. **RBAC** - Role-based access control

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│   Server    │────▶│   Agents    │
│  (Submit)   │     │   (API)     │     │  (Execute)  │
└─────────────┘     └─────────────┘     └─────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │  Database   │
                   │ (Jobs/Logs) │
                   └─────────────┘
```

## Project Structure

```
ci-engine/
├── ci_engine/              # Main package
│   ├── server/             # FastAPI server
│   │   ├── main.py         # App entry, routes
│   │   ├── models.py       # DB models & Pydantic schemas
│   │   ├── db.py           # Database setup
│   │   ├── dashboard.py    # Web UI routes
│   │   ├── auth.py         # Authentication & RBAC
│   │   └── webhooks.py     # GitHub webhook integration
│   ├── agent/              # Build agent
│   │   └── agent.py        # Agent implementation
│   ├── core/               # Core logic
│   │   ├── pipeline.py     # Pipeline parsing
│   │   ├── scheduler.py    # Job scheduling
│   │   ├── executor.py     # Command execution
│   │   └── secrets.py      # Secret management
│   └── cli.py              # CLI tool
├── tests/                  # Test suite (26 tests)
│   ├── unit/               # Unit tests
│   └── conftest.py         # Shared fixtures
├── pyproject.toml          # Project config
├── README.md               # This file
└── AGENTS.md              # AI agent development guide
```

## Quick Start

### Start Server
```bash
cd ci-engine
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn ci_engine.server.main:app --reload
```

### Run Tests
```bash
# All tests
.venv/bin/python -m pytest tests/ -v

# With coverage
.venv/bin/python -m pytest tests/ --cov=ci_engine --cov-report=term-missing

# Lint
ruff check ci_engine/ tests/
```

### Register Agent
```bash
python -m ci_engine.agent.agent --register http://localhost:8000 --name my-agent
```

### Create Pipeline
```yaml
# .ci-engine.yml
steps:
  - label: "Build"
    command: "echo 'Building...'"
  - label: "Test"
    command: "echo 'Testing...'"
```

### Trigger Build
```bash
curl -X POST http://localhost:8000/api/builds \
  -H "Content-Type: application/json" \
  -d '{"pipeline": ".ci-engine.yml", "branch": "main"}'
```

## Security Features

- **API Tokens** - Generate and manage API tokens for CI/CD integrations
- **Role-Based Access** - Admin, Developer, Viewer roles with appropriate permissions
- **Secret Management** - Encrypted storage for sensitive values like API keys and passwords
- **Webhook Verification** - HMAC signature verification for GitHub webhooks

## API Endpoints

### Builds
- `GET /api/builds` - List all builds
- `POST /api/builds` - Create new build
- `GET /api/builds/{id}` - Get build details

### Agents
- `GET /api/agents` - List registered agents
- `POST /api/agents/register` - Register new agent

### Auth (TODO)
- `POST /api/auth/register` - Create user
- `POST /api/auth/login` - Login
- `POST /api/auth/tokens` - Create API token

### Webhooks
- `POST /api/webhooks/github` - GitHub webhook endpoint

## Tech Stack

- **FastAPI** - REST API server
- **SQLAlchemy** - Database (SQLite by default)
- **WebSocket** - Real-time log streaming
- **Pydantic** - Data validation
- **Pytest** - Testing framework
- **Ruff** - Linting

## Development

See AGENTS.md for AI agent development instructions.