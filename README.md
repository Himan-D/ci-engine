# CI Engine - Buildkite Alternative

A modern CI/CD platform built with AI-first vibecoding approach.

## What is CI Engine?

CI Engine is a continuous integration/continuous deployment platform that runs build pipelines on distributed agents, similar to Buildkite but designed with AI agent collaboration in mind.

## Core Features

1. **Pipeline Orchestration** - Define builds in code (YAML)
2. **Agent Pool Management** - Register and manage build agents
3. **Job Distribution** - Distribute work across available agents
4. **Real-time Logging** - Stream build logs in real-time
5. **Build Artifacts** - Store build artifacts in S3
6. **Container Isolation** - Run jobs in Docker containers
7. **Web Dashboard** - Monitor and manage builds
8. **Authentication** - User management and API tokens
9. **Secret Management** - Encrypted secrets storage with Fernet
10. **GitHub Webhooks** - Trigger builds from GitHub events
11. **RBAC** - Role-based access control
12. **OIDC/SSO** - Cloud provider authentication (AWS, GCP, Azure)
13. **Distributed Tracing** - OpenTelemetry integration
14. **Dead Letter Queue** - Failed job handling
15. **Circuit Breakers** - Resilience patterns
16. **Audit Logging** - Compliance tracking

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
├── ci_engine/                    # Main package
│   ├── __init__.py
│   ├── cli.py                    # CLI tool
│   ├── agent/                    # Build agent
│   │   ├── __init__.py
│   │   ├── agent.py             # Agent implementation
│   │   └── git.py               # Git operations
│   ├── core/                    # Core logic
│   │   ├── __init__.py
│   │   ├── artifacts.py         # S3 artifact storage
│   │   ├── audit.py            # Audit logging
│   │   ├── container.py         # Docker executor
│   │   ├── environments.py      # Environment groups
│   │   ├── executor.py         # Command execution
│   │   ├── logging.py          # Structured logging
│   │   ├── metrics.py          # Prometheus metrics
│   │   ├── notifications.py    # Slack/Discord/Email
│   │   ├── pipeline.py         # YAML pipeline parsing
│   │   ├── scaler.py           # Auto-scaling
│   │   ├── scheduler.py        # Job scheduling
│   │   ├── secrets.py          # Fernet encryption
│   │   ├── ssh_keys.py         # SSH key management
│   │   └── triggers.py         # Pipeline triggers
│   └── server/                  # FastAPI server
│       ├── __init__.py
│       ├── auth.py              # JWT/bcrypt auth
│       ├── dashboard.py         # Web UI routes
│       ├── db.py               # Database setup
│       ├── github_oauth.py     # GitHub OAuth
│       ├── main.py             # API routes
│       ├── middleware.py       # Rate limiting
│       ├── models.py           # SQLAlchemy models
│       └── webhooks.py         # GitHub webhooks
├── tests/                       # Test suite (26 tests)
│   ├── conftest.py
│   └── unit/
│       ├── test_auth.py
│       ├── test_executor.py
│       └── test_pipeline.py
├── Dockerfile.server            # Docker image
├── Dockerfile.agent            # Agent Docker image
├── docker-compose.yml         # Local development
├── docker-compose.prod.yml    # Production config
├── pyproject.toml            # Project config
├── README.md                  # This file
└── AGENTS.md                  # AI agent guide
```

## Quick Start

### 1. Start Server
```bash
cd ci-engine
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn ci_engine.server.main:app --reload
```

### 2. Start Agent (in another terminal)
```bash
python -m ci_engine.agent.agent --server http://localhost:8000 --name build-agent-1
```

### 3. Create a Build
```bash
# Using the API
curl -X POST http://localhost:8000/api/builds \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": "steps:\n  - label: \"Build\"\n    command: \"echo Building...\"\n  - label: \"Test\"\n    command: \"echo Testing...\"",
    "branch": "main"
  }'
```

### 4. With Container Support
```yaml
# Pipeline with container
steps:
  - label: "Build"
    command: "npm install && npm run build"
    container:
      image: "node:18"
      cpu: "1"
      memory: "1g"
  - label: "Test"  
    command: "npm test"
    container: "node:18"
```

### 5. Kubernetes Deployment
```bash
# Deploy to Kubernetes
kubectl apply -k k8s/
```

### Environment Variables
```bash
# Required
DATABASE_URL=postgresql://user:pass@localhost/ci_engine
CI_ENGINE_JWT_SECRET_KEY=your-secret-key

# Optional - Artifact Storage
CI_ENGINE_S3_BUCKET=ci-engine-artifacts
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
AWS_REGION=us-east-1

# Optional - Notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
DISCORD_WEBHOOK_URL=https://discord.com/...

# Optional - OIDC (AWS/GCP/Azure)
AWS_OIDC_ISSUER=https://your-oidc-issuer
GCP_OIDC_ISSUER=https://accounts.google.com
AZURE_TENANT_ID=your-tenant-id
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