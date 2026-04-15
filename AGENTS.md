# Agent Instructions for CI Engine

These instructions apply to all AI-assisted contributions to CI Engine.

## 1. Contribution Policy

### Before starting work
- Check existing issues and PRs to avoid duplication
- Explain your approach in comments if it's materially different from existing solutions

### No busywork PRs
Do not open one-off PRs for tiny edits. Bundle related changes together.

### Accountability
- All AI-assisted work requires human review
- PR descriptions must include:
  - Why this change is needed
  - Test commands and results
  - Statement that AI assistance was used

## 2. Development Workflow

### Environment Setup
```bash
cd ci-engine
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
```

### Running the Server
```bash
uvicorn ci_engine.server.main:app --reload --port 8000
```

### Running Tests
```bash
.venv/bin/python -m pytest tests/ -v
```

### Running Linters
```bash
ruff check .
ruff format .
```

## 3. Project Structure

```
ci_engine/
├── server/          # FastAPI server
│   ├── main.py      # App entry point
│   ├── models.py    # Pydantic models
│   ├── db.py        # Database setup
│   └── routes/     # API endpoints
├── agent/           # Build agent
│   └── agent.py     # Agent implementation
├── core/            # Core logic
│   ├── pipeline.py # Pipeline parsing
│   ├── scheduler.py# Job scheduling
│   └── executor.py # Command execution
└── tests/           # Test suite
```

## 4. Key Conventions

- Use Pydantic for all data validation
- Use SQLite with SQLAlchemy for persistence
- Use WebSocket for real-time log streaming
- Follow REST conventions for API design
- Use type hints everywhere

## 5. Commit Messages

Use Co-authored-by for AI assistance attribution:
```
Add new feature

Co-authored-by: Claude <noreply@anthropic.com>
```

## 6. Code Style

- 4 spaces indentation
- Max line length: 100
- Use f-strings for string formatting
- Use dataclasses for simple data structures
- Use Pydantic BaseModel for API schemas