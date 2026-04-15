# CI Engine - Buildkite Alternative

A modern CI/CD platform built with AI-first vibecoding approach.

## What is CI Engine?

CI Engine is a continuous integration/continuous deployment platform that runs build pipelines on distributed agents, similar to Buildkite but designed with AI agent collaboration in mind.

## Core Features

1. **Pipeline Orchestration** - Define builds in code (YAML/JSON)
2. **Agent Pool Management** - Register and manage build agents
3. **Job Distribution** - Distribute work across available agents
4. **Real-time Logging** - Stream build logs in real-time
5. **Artifact Storage** - Store build artifacts
6. **Web Dashboard** - Monitor and manage builds

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

## Quick Start

### Start Server
```bash
cd ci-engine
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
uvicorn ci_engine.server.main:app --reload
```

### Register Agent
```bash
python -m ci_engine.agent.agent --register http://localhost:8000
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

## API Endpoints

- `GET /api/builds` - List all builds
- `GET /api/builds/{id}` - Get build details
- `POST /api/builds` - Create new build
- `GET /api/builds/{id}/logs` - Stream build logs
- `GET /api/agents` - List registered agents
- `POST /api/agents/register` - Register new agent

## Tech Stack

- **FastAPI** - REST API server
- **SQLAlchemy** - Database (SQLite by default)
- **WebSocket** - Real-time log streaming
- **Pydantic** - Data validation
- **SQLite** - Default database

## Development

See AGENTS.md for AI agent development instructions.