# Agent Instructions for CI Engine

These instructions apply to **all AI-assisted contributions** to CI Engine.

## 1. Contribution Policy

### Before Starting Work
- Check existing issues and PRs to avoid duplication
- Read this entire file first
- Understand the project structure and existing tests
- Plan your changes with proper testing strategy

### Code Quality Standards
- **NEVER write code without tests** - Every new feature needs unit tests
- **NEVER break existing tests** - Run full test suite before committing
- **NEVER skip linting** - All code must pass ruff checks
- **Use type hints** - All functions must have type annotations
- **Document public APIs** - Add docstrings to all public functions
- **Follow existing patterns** - Match the code style in the codebase

### No Busywork PRs
- Bundle related changes together
- Don't open one-off typo fixes without substantive work

### Accountability
- All AI-assisted work requires human review
- PR descriptions must include:
  - Why this change is needed
  - Test commands run and results
  - Statement that AI assistance was used

## 2. Project Structure

```
ci-engine/
├── ci_engine/              # Main package
│   ├── server/             # FastAPI server
│   │   ├── main.py         # App entry, routes
│   │   ├── models.py       # DB models & Pydantic schemas
│   │   ├── db.py           # Database setup
│   │   ├── dashboard.py    # Web UI routes
│   │   └── auth.py         # Authentication (TODO)
│   ├── agent/              # Build agent
│   │   └── agent.py        # Agent implementation
│   ├── core/               # Core logic
│   │   ├── pipeline.py     # Pipeline parsing
│   │   ├── scheduler.py    # Job scheduling
│   │   ├── executor.py     # Command execution
│   │   └── artifacts.py    # Artifact storage (TODO)
│   └── cli.py              # CLI tool
├── tests/                  # Test suite
│   ├── conftest.py         # Shared fixtures
│   ├── unit/               # Unit tests
│   └── integration/        # Integration tests
├── pyproject.toml          # Project config
├── README.md               # Documentation
└── AGENTS.md              # This file
```

## 3. Development Workflow

### Environment Setup
```bash
cd ci-engine
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
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

### Running Linters
```bash
# Check linting
ruff check ci_engine/ tests/

# Format code
ruff format ci_engine/ tests/

# Type checking (if mypy configured)
ruff check --select I ci_engine/
```

### Running the Server
```bash
uvicorn ci_engine.server.main:app --reload --port 8000
```

### Creating New Features

**Step 1: Plan and Document**
- Write what the feature should do
- Identify what tests are needed
- Plan the module structure

**Step 2: Write Tests First (TDD)**
- Create test file in appropriate location
- Write failing tests for the expected behavior

**Step 3: Implement the Feature**
- Add the implementation
- Make tests pass

**Step 4: Verify**
- Run full test suite
- Run linting
- Check for type errors

**Step 5: Commit with Proper Message**
```
Add <feature_name>

Description of what was added and why.

Tests:
- Unit tests for core functionality
- Integration tests for API endpoints

Co-authored-by: Claude <noreply@anthropic.com>
```

## 4. Module Responsibility

### ci_engine/core/
- **pipeline.py** - Parse YAML pipeline definitions
- **scheduler.py** - Distribute jobs to agents
- **executor.py** - Run commands in isolated environments

### ci_engine/server/
- **main.py** - REST API endpoints, WebSocket
- **models.py** - SQLAlchemy models + Pydantic schemas
- **db.py** - Database connection management
- **dashboard.py** - HTML web interface

### ci_engine/agent/
- **agent.py** - Agent that polls server for work

## 5. Testing Guidelines

### Test File Naming
- `test_<module_name>.py` for module tests
- Use `conftest.py` for shared fixtures

### Test Organization
```python
class Test<Component>:
    """Tests for <component>."""
    
    @pytest.fixture
    def component(self):
        """Create component for testing."""
        return Component()
        
    def test_<behavior>(self, component):
        """Test <expected behavior>."""
        result = component.do_something()
        assert result == expected
```

### Integration Tests
- Use the FastAPI TestClient
- Create a test app instance
- Test API endpoints end-to-end

## 6. Security Considerations

- Never hardcode secrets - use environment variables
- Validate all inputs with Pydantic models
- Use parameterized queries (SQLAlchemy handles this)
- Add rate limiting for public endpoints (TODO)

## 7. Commit Messages

Use Co-authored-by for AI assistance:
```
Add new feature

Detailed description of changes.

Tests:
- Unit tests for X
- Integration tests for Y

Co-authored-by: Claude <noreply@anthropic.com>
```

## 8. Code Style

- 4 spaces indentation
- Max line length: 100
- Use f-strings for string formatting
- Use dataclasses for simple data structures
- Use Pydantic BaseModel for API schemas
- Type hints everywhere (no `Any` unless necessary)

## 9. Before Submitting PR

1. ✅ All tests pass: `pytest tests/ -v`
2. ✅ Lint passes: `ruff check .`
3. ✅ Types correct: (no type errors)
4. ✅ Documentation updated if needed
5. ✅ Commit message has Co-authored-by