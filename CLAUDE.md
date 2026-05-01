# CI Engine — AI Agent Context

> **Session context**: https://app.warp.dev/session/6a336fd7-cc2e-4788-9a83-74c85f272516
>
> **Date**: 2026-04-30 | **Stack**: Python 3.12, FastAPI, SQLAlchemy 2, React/TypeScript, Docker, Kubernetes

---

## What This Project Is

CI Engine is a **self-hosted, production-grade CI/CD platform** — a Buildkite alternative — with:

- FastAPI server (`ci_engine/server/`) serving 50+ REST endpoints + WebSocket streams
- Distributed build agents (`ci_engine/agent/`) with container isolation (Docker/Podman)
- React + TypeScript frontend (`frontend/`) with real-time log streaming
- Kubernetes manifests (`k8s/`) for production deployment
- Plugin/middleware system for extensibility

**Primary users**: DevOps/platform engineers running self-hosted CI. The product competes with Buildkite, CircleCI, and GitHub Actions on configurability and self-hosting story.

---

## Architecture at a Glance

```
┌─────────────┐     REST/WS     ┌─────────────────────────────┐
│  Browser /  │ ◄─────────────► │  FastAPI Server              │
│  Frontend   │                 │  ci_engine/server/main.py    │
└─────────────┘                 │  (2340+ lines, 50+ endpoints)│
                                └──────────┬──────────────────┘
                                           │ HTTP polling
                               ┌───────────▼──────────────┐
                               │  Build Agents (N agents)  │
                               │  ci_engine/agent/agent.py │
                               │  (805 lines, plugin arch) │
                               └───────────┬──────────────┘
                                           │ exec
                               ┌───────────▼──────────────┐
                               │  Docker / Podman          │
                               │  ci_engine/core/container │
                               └──────────────────────────┘
```

**Data flow for a build**:
1. Client POSTs `/api/builds` with YAML pipeline → server creates `Build` + `Job` rows
2. Agent polls `GET /api/jobs/claim` → claims a job
3. Agent executes steps in Docker container, streams logs via WebSocket to `/ws/jobs/{id}/logs`
4. Agent POSTs completion to `/api/jobs/{id}/complete`
5. Server updates build status, broadcasts via `/ws/builds/{id}`

---

## File Map (All Key Files)

### Server

| File | Lines | Purpose |
|------|-------|---------|
| `ci_engine/server/main.py` | 2340 | **All API endpoints**, WebSocket manager, app startup/shutdown |
| `ci_engine/server/models.py` | ~600 | SQLAlchemy ORM models + Pydantic request/response schemas |
| `ci_engine/server/auth.py` | 384 | User model, JWT, API tokens, bcrypt, RBAC `Permission` class |
| `ci_engine/server/middleware.py` | ~200 | `AuthenticationMiddleware`, `create_access_token`, `verify_token`, `get_current_user`, rate limiter |
| `ci_engine/server/oidc.py` | ~300 | OIDC providers (AWS/GCP/Azure/GitHub), token exchange |
| `ci_engine/server/webhooks.py` | ~200 | GitHub/GitLab webhook parsing + HMAC verification |
| `ci_engine/server/dashboard.py` | ~150 | Jinja2 HTML dashboard router |
| `ci_engine/server/db.py` | ~50 | `get_db`, `init_db`, `SessionLocal`, `engine` |
| `ci_engine/server/github_oauth.py` | ~100 | GitHub OAuth flow |

### Agent

| File | Lines | Purpose |
|------|-------|---------|
| `ci_engine/agent/agent.py` | 805 | Core agent loop: poll → claim → execute → stream logs → complete |
| `ci_engine/agent/sdk.py` | 201 | User-friendly `CIEngineAgent` + `CIEnginePlugin` wrapper |
| `ci_engine/agent/plugins.py` | ~200 | Plugin registry + lifecycle hooks |
| `ci_engine/agent/middleware.py` | ~150 | Job transformation middleware chain |
| `ci_engine/agent/git.py` | ~100 | Git clone/checkout helpers |
| `ci_engine/agent/skills.py` | ~150 | Skill auto-detection (docker, python, node, etc.) |
| `ci_engine/agent/builtins.py` | ~150 | Built-in plugins (logging, metrics, env injection) |

### Core

| File | Lines | Purpose |
|------|-------|---------|
| `ci_engine/core/pipeline.py` | 373 | YAML parse, matrix expansion, conditional `if:`, step types |
| `ci_engine/core/executor.py` | 228 | `CommandSanitizer`, `Executor`, `ExecutionResult` |
| `ci_engine/core/container.py` | ~300 | Docker/Podman run, CPU/mem limits, volume mounts, cleanup |
| `ci_engine/core/scheduler.py` | ~250 | Agent selection, dependency resolution, retry logic |
| `ci_engine/core/artifacts.py` | ~150 | S3 upload/download via aiobotocore |
| `ci_engine/core/secrets.py` | ~200 | Fernet encryption, key versioning, secret rotation |
| `ci_engine/core/notifications.py` | ~200 | Slack/Discord/Email via webhooks + SMTP |
| `ci_engine/core/cache.py` | ~150 | Build cache: store/retrieve keyed by hash |
| `ci_engine/core/audit.py` | ~100 | Immutable audit log entries |
| `ci_engine/core/metrics.py` | ~100 | Prometheus counters/histograms |
| `ci_engine/core/tracing.py` | ~80 | OpenTelemetry setup |
| `ci_engine/core/logging.py` | ~80 | Structured JSON logging setup |
| `ci_engine/core/scaler.py` | ~150 | Agent pool auto-scaling |
| `ci_engine/core/triggers.py` | ~100 | Cron-based pipeline triggers |
| `ci_engine/core/environments.py` | ~100 | Environment variable groups |
| `ci_engine/core/ssh_keys.py` | ~80 | SSH key management |

### Infrastructure

| File | Purpose |
|------|---------|
| `Dockerfile.server` | Server image (Python 3.12-slim) |
| `Dockerfile.agent` | Agent image |
| `docker-compose.demo.yml` | Local dev stack |
| `k8s/infra.yaml` | Redis + ConfigMap + Secrets |
| `k8s/server-deployment.yaml` | Server Deployment + HPA + Ingress |
| `k8s/agent-deployment.yaml` | Agent DaemonSet/Deployment |
| `k8s/backup-cronjob.yaml` | Database backup CronJob |
| `pyproject.toml` | Dependencies, ruff config, pytest config |

---

## Database Models

All tables defined in `ci_engine/server/models.py` and `ci_engine/server/auth.py`:

| Table | Key Columns |
|-------|-------------|
| `builds` | id, pipeline_yaml, status (pending/running/passed/failed/cancelled), branch, commit_sha, created_at |
| `jobs` | id, build_id, name, command, status, agent_id, exit_code, started_at, completed_at |
| `job_logs` | id, job_id, line_number, content, timestamp |
| `agents` | id, name, hostname, status (idle/busy/offline/draining), tags, skills, pool_id |
| `agent_pools` | id, name, min_agents, max_agents, current_count |
| `agent_skills` | id, agent_id, skill, level (basic/intermediate/advanced) |
| `agent_labels` | id, agent_id, key, value |
| `users` | id, username, password_hash (bcrypt), role (admin/developer/viewer), is_active |
| `api_tokens` | id, token_hash (SHA256), name, user_id, expires_at, last_used, is_active |
| `secrets` | id, name, value (Fernet encrypted), scope, is_active |
| `artifacts` | id, build_id, job_id, name, s3_key, size_bytes, content_type |
| `webhook_configs` | id, url, secret, events, provider (github/gitlab) |
| `environment_groups` | id, name, variables (JSON) |
| `pipeline_triggers` | id, pipeline_yaml, cron_expression, last_run, is_active |
| `audit_entries` | id, user_id, action, resource_type, resource_id, timestamp, details |

**No Alembic migrations yet** — `init_db()` calls `Base.metadata.create_all()`. Adding Alembic is a high-priority task.

---

## API Endpoints (Complete)

All defined in `ci_engine/server/main.py`:

### Auth
- `POST /api/auth/register` — create user
- `POST /api/auth/login` — returns `access_token` (15 min) + `refresh_token` (7 days)
- `POST /api/auth/refresh` — exchange refresh token
- `POST /api/auth/tokens` — create API token
- `GET /api/auth/tokens` — list user tokens
- `DELETE /api/auth/tokens/{id}` — revoke token
- `POST /api/auth/oidc/{provider}` — OIDC token exchange

### Builds
- `POST /api/builds` — create build (accepts pipeline YAML)
- `GET /api/builds` — list builds (public, no auth)
- `GET /api/builds/{id}` — get build details + jobs
- `POST /api/builds/{id}/cancel` — cancel build
- `POST /api/builds/{id}/unblock` — unblock a blocked step
- `DELETE /api/builds` — cleanup old builds (admin)

### Jobs
- `GET /api/jobs/claim` — agent polls this to claim a job
- `POST /api/jobs/{id}/start` — agent marks job started
- `POST /api/jobs/{id}/complete` — agent marks complete (exit_code, logs)
- `POST /api/jobs/{id}/logs` — agent appends log chunk
- `GET /api/jobs/{id}/logs` — get job logs
- `POST /api/jobs/{id}/cancel` — cancel a running job

### Agents
- `POST /api/agents/register` — register new agent
- `GET /api/agents` — list agents with status
- `POST /api/agents/{id}/heartbeat` — keepalive
- `POST /api/agents/{id}/drain` — stop accepting jobs
- `POST /api/agents/{id}/undrain` — resume accepting jobs
- `POST /api/agents/{id}/upgrade` — trigger agent upgrade
- `GET /api/agents/{id}/skills` — list agent skills
- `GET /api/agents/{id}/labels` — list agent labels
- `GET /api/agents/{id}/metrics` — CPU/memory/disk

### Agent Pools
- `POST /api/agent-pools` — create pool
- `GET /api/agent-pools` — list pools
- `DELETE /api/agent-pools/{id}` — delete pool

### Secrets
- `POST /api/secrets` — create encrypted secret
- `GET /api/secrets` — list secrets (names only, no values)
- `GET /api/secrets/{id}` — get secret (decrypted, admin only)
- `PUT /api/secrets/{id}` — update secret
- `DELETE /api/secrets/{id}` — deactivate secret
- `POST /api/secrets/{id}/rotate` — rotate to new value

### Artifacts
- `POST /api/builds/{id}/artifacts` — upload artifact to S3
- `GET /api/builds/{id}/artifacts` — list artifacts
- `GET /api/artifacts/{id}/download` — download from S3

### Webhooks
- `POST /api/webhooks` — register webhook config
- `GET /api/webhooks` — list webhook configs
- `POST /api/webhooks/github` — receive GitHub events
- `POST /api/webhooks/gitlab` — receive GitLab events

### Cache
- `POST /api/cache` — store cache entry
- `GET /api/cache/{key}` — retrieve cache entry
- `DELETE /api/cache/{key}` — delete cache entry
- `GET /api/cache` — list cache entries

### Other
- `GET /api/environments` + `POST` + `DELETE /{id}` — environment groups
- `GET /api/triggers` + `POST` + `DELETE /{id}` — cron triggers
- `GET /api/audit-logs` — audit log (admin)
- `GET /api/stats` — build statistics
- `GET /health` — liveness probe
- `GET /health/deep` — readiness with DB + storage checks
- `GET /metrics` — Prometheus metrics
- `GET /` — Jinja2 dashboard

### WebSockets
- `WS /ws/jobs/{id}/logs` — real-time job log stream
- `WS /ws/builds/{id}` — build status updates
- `WS /ws/builds` — all builds stream

---

## Known Issues & Production Gaps

These are **confirmed problems** in the current code. Fix these before shipping:

### Critical

1. **CommandSanitizer blocks valid shell** (`ci_engine/core/executor.py:33-44`)
   - Patterns `&&`, `||`, `;` block `make build && make test`, `npm ci; npm test`, etc.
   - **Fix**: Run commands via `bash -c "<cmd>"` in container, not bare `shlex.split`. The container provides isolation, not the regex.

2. **No Alembic migrations** (`ci_engine/server/db.py`)
   - `init_db()` calls `Base.metadata.create_all()` — any schema change on existing DB loses data
   - **Fix**: `pip install alembic`, run `alembic init`, generate migration from current models

3. **OIDC falls back to unverified decode** (`ci_engine/server/oidc.py:~150`)
   - If JWKS endpoint is unavailable, token is accepted without signature check
   - **Fix**: Fail closed — reject token if signature cannot be verified

4. **Secrets not scoped to repository** (`ci_engine/core/secrets.py:~182`)
   - All active secrets are injected into every build
   - **Fix**: Add `repository` and `scope` columns; filter by build repo at inject time

### High Priority

5. **WebSocket manager is in-memory** (`ci_engine/server/main.py:175-200`)
   - Multi-replica deployments lose subscriptions — user connects to replica A, job runs on replica B
   - **Fix**: Use Redis pub/sub as the broadcast backend

6. **Agent polling is synchronous** (`ci_engine/agent/agent.py:141-157`)
   - At scale, N agents × polling interval = hammering the server
   - **Fix**: Long-polling endpoint or SSE push for job assignment

7. **Dashboard is publicly accessible** (`ci_engine/server/main.py:146-158`)
   - `/` is in `public_paths` — anyone can see the dashboard
   - **Fix**: Remove `/` from public_paths, redirect unauthenticated users to `/login`

8. **CORS wildcard in production** (`ci_engine/server/main.py:136-142`)
   - `CORS_ORIGINS` defaults to `"*"` — must be set to exact origins in prod
   - **Fix**: Require `CORS_ORIGINS` env var to be set explicitly, no default wildcard

### Medium Priority

9. **No test coverage for OIDC, webhooks, scaler, plugins**
10. **No rate limiting on `POST /api/builds`** — DoS vector
11. **No dead letter queue** — failed jobs after max retries are silently dropped
12. **No circuit breakers** — mentioned in original CLAUDE.md but not implemented
13. **SQLite in dev, PostgreSQL required in prod** — connection pooling not configured
14. **No Helm chart** — raw k8s manifests only; no kustomize overlays for staging/prod

---

## Rules for AI Agents

### MUST DO
1. **Run tests before every commit**: `pytest tests/ -v`
2. **Run linter before every commit**: `ruff check ci_engine/ tests/`
3. **Add type hints** on every function you write or modify
4. **Write tests** for every new feature — put in `tests/unit/` or `tests/integration/`
5. **Never break existing tests** — check with `pytest tests/ -v` before proposing changes
6. **Use `shlex.split()` for subprocess** — never `shell=True`
7. **Use environment variables for all config** — never hardcode URLs, credentials, or ports
8. **For DB schema changes** — update models AND write an Alembic migration (once Alembic is set up)
9. **Scope secrets correctly** — any secret-related change must respect the `repository` scope column

### MUST NOT
1. **Never commit directly to master** — always create a feature branch + PR
2. **Never skip tests** even for single-line changes
3. **Never use `shell=True`** in subprocess — use `shlex.split()` or pass list directly
4. **Never hardcode secrets** or credentials — always use environment variables
5. **Never add `||true` or error suppression** to make tests pass — fix the root cause
6. **Never widen the public_paths list** without security review
7. **Never expand CORS to `*`** in any environment configuration
8. **Never store plaintext secrets** in DB — always encrypt via `ci_engine/core/secrets.py`

### Code Patterns

**Adding a new API endpoint**:
```python
# In ci_engine/server/main.py
@app.post("/api/your-resource", response_model=YourResponse)
async def create_resource(
    body: YourCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> YourResponse:
    if not Permission.can_do_thing(current_user.role):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    # ... implementation
```

**Adding a new agent plugin**:
```python
# In ci_engine/agent/builtins.py or a new file
from ci_engine.agent.sdk import CIEnginePlugin

class MyPlugin(CIEnginePlugin):
    name = "my-plugin"

    def pre_execute(self, context: dict, job: dict) -> dict:
        # transform job before execution
        return job

    def post_execute(self, context: dict, result: dict) -> dict:
        # react to job result
        return result
```

**Adding a new core feature**:
- Create `ci_engine/core/your_feature.py`
- Add corresponding test in `tests/unit/test_your_feature.py`
- Wire up endpoints in `ci_engine/server/main.py`
- Export from `ci_engine/__init__.py` if part of public API

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific module
pytest tests/unit/test_pipeline.py -v

# Run with coverage report
pytest tests/ --cov=ci_engine --cov-report=term-missing

# Run only unit tests
pytest tests/unit/ -v

# Run only integration tests
pytest tests/integration/ -v

# Lint (check only)
ruff check ci_engine/ tests/

# Lint (auto-fix)
ruff check --fix ci_engine/ tests/

# Format
ruff format ci_engine/ tests/
```

**Test files that exist** (do not delete or break):
- `tests/unit/test_auth.py` — auth, JWT, tokens
- `tests/unit/test_executor.py` — command execution, sanitizer
- `tests/unit/test_pipeline.py` — YAML parsing, matrix expansion
- `tests/unit/test_scheduler.py` — agent selection, retries
- `tests/unit/test_cache.py` — cache store/retrieve
- `tests/unit/test_secrets.py` — Fernet encryption, rotation
- `tests/unit/test_plugins.py` — plugin hooks
- `tests/integration/test_api.py` — full API integration

**Test fixtures** are in `tests/conftest.py` — check before creating duplicate fixtures.

---

## Running Locally

```bash
# Install deps
pip install -e ".[dev]"

# Start server (SQLite, no external deps)
uvicorn ci_engine.server.main:app --reload --port 8000

# Start agent (separate terminal)
python -m ci_engine.agent.agent --server http://localhost:8000 --name local-agent

# Start frontend dev server
cd frontend && npm install && npm run dev  # proxies /api to :8000

# Full stack with Docker
docker compose -f docker-compose.demo.yml up
```

**Default admin credentials (demo only)**:
- Username: `admin`
- Password: `admin123`

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Prod | `sqlite:///ci_engine.db` | PostgreSQL: `postgresql://user:pass@host/db` |
| `CI_ENGINE_JWT_SECRET_KEY` | Yes | — | Min 32 chars, random string for JWT signing |
| `CI_ENGINE_FERNET_KEY` | Secrets | — | Fernet key for secret encryption (generate: `from cryptography.fernet import Fernet; Fernet.generate_key()`) |
| `CI_ENGINE_S3_BUCKET` | Artifacts | — | S3 bucket name for artifact storage |
| `CI_ENGINE_S3_ENDPOINT_URL` | Artifacts | AWS default | Override for MinIO/localstack |
| `AWS_ACCESS_KEY_ID` | Artifacts | — | S3 credentials |
| `AWS_SECRET_ACCESS_KEY` | Artifacts | — | S3 credentials |
| `SLACK_WEBHOOK_URL` | No | — | Slack notifications |
| `DISCORD_WEBHOOK_URL` | No | — | Discord notifications |
| `SMTP_HOST` | No | — | Email notifications |
| `SMTP_PORT` | No | `587` | SMTP port |
| `SMTP_USER` | No | — | SMTP username |
| `SMTP_PASSWORD` | No | — | SMTP password |
| `AWS_OIDC_ISSUER` | No | — | OIDC: AWS issuer URL |
| `GCP_OIDC_ISSUER` | No | — | OIDC: GCP issuer URL |
| `AZURE_OIDC_ISSUER` | No | — | OIDC: Azure issuer URL |
| `CORS_ORIGINS` | Prod | `*` | Comma-separated allowed origins — SET THIS in production |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR) |
| `LOG_FORMAT` | No | `""` | Set to `json` for structured JSON logs |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | — | OpenTelemetry collector endpoint |
| `CI_ENGINE_SERVER_URL` | Agent | `http://localhost:8000` | Agent → server URL |
| `CI_ENGINE_AGENT_TOKEN` | Agent | — | API token for agent auth |

---

## Deployment

### Docker (local/staging)
```bash
docker build -f Dockerfile.server -t ci-engine-server .
docker build -f Dockerfile.agent -t ci-engine-agent .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://... \
  -e CI_ENGINE_JWT_SECRET_KEY=... \
  ci-engine-server
```

### Kubernetes (production)
```bash
# Apply all manifests
kubectl apply -k k8s/

# Or individually
kubectl apply -f k8s/infra.yaml        # Redis, ConfigMap, Secrets
kubectl apply -f k8s/server-deployment.yaml  # Server + HPA + Ingress
kubectl apply -f k8s/agent-deployment.yaml   # Agents
kubectl apply -f k8s/backup-cronjob.yaml     # DB backup
```

**K8s prerequisites**: PostgreSQL (via Helm or managed service), Redis (in infra.yaml), cert-manager for TLS.

---

## Production Deployment Checklist

```
[ ] Set DATABASE_URL to PostgreSQL (not SQLite)
[ ] Set CI_ENGINE_JWT_SECRET_KEY (32+ chars, random)
[ ] Set CI_ENGINE_FERNET_KEY (generated Fernet key)
[ ] Set CORS_ORIGINS to exact frontend domain (not *)
[ ] Configure TLS/HTTPS (cert-manager or load balancer)
[ ] Set up Alembic migrations
[ ] Configure S3 bucket for artifacts
[ ] Set up PostgreSQL backups (k8s/backup-cronjob.yaml)
[ ] Configure Redis for WebSocket pub/sub (multi-replica)
[ ] Set LOG_FORMAT=json for log aggregation
[ ] Configure OTEL endpoint for tracing
[ ] Set resource limits in k8s manifests
[ ] Enable HPA (already in server-deployment.yaml)
[ ] Configure ingress with rate limiting
[ ] Rotate all secrets after first deploy
[ ] Verify health checks: GET /health, GET /health/deep
```

---

## Troubleshooting

### Tests fail
1. Check `ruff check --fix ci_engine/ tests/` first — many failures are lint errors
2. Ensure all modules exist: `python -c "import ci_engine.server.main"`
3. Check fixtures in `tests/conftest.py` match what tests expect
4. For async test failures: check `asyncio_mode = "auto"` in `pyproject.toml`

### Agent won't connect
1. Server must be running: `curl http://localhost:8000/health`
2. Agent needs valid API token in `CI_ENGINE_AGENT_TOKEN`
3. Check Docker is available: `docker ps`
4. Check firewall: agent must reach server on port 8000

### Docker build fails
1. Verify Python 3.12 base image: `python:3.12-slim`
2. Check all deps in `pyproject.toml` — no implicit deps
3. `psycopg2-binary` requires libpq — check Dockerfile installs `libpq-dev`

### WebSocket disconnects
1. Check nginx timeout config — must allow long-lived connections
2. Ping-pong keepalive is implemented (30s timeout) — check proxy isn't closing earlier
3. In k8s, check ingress annotations: `nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"`

### Build stuck in pending
1. Check at least one agent is registered and idle: `GET /api/agents`
2. Check agent tags match pipeline `agents:` field
3. Check scheduler logs for dependency resolution errors

---

## Feature Roadmap (Prioritized)

### Immediate (fix before production)
- [ ] Add Alembic migrations
- [ ] Fix CommandSanitizer — allow `&&`, `||`, `;` via container exec (not regex blocks)
- [ ] Fix OIDC fallback — fail closed on unverified tokens
- [ ] Scope secrets to repositories
- [ ] Add Redis pub/sub for WebSocket broadcast
- [ ] Protect dashboard route with auth

### Short-term
- [ ] Dead letter queue for failed jobs (after max retries)
- [ ] Circuit breakers for external service calls (S3, SMTP, webhooks)
- [ ] Rate limiting on `POST /api/builds`
- [ ] Helm chart for k8s deployment
- [ ] E2E tests with Playwright
- [ ] Pipeline versioning + rollback
- [ ] Artifact retention/cleanup policies

### Medium-term
- [ ] Long-polling or SSE for agent job assignment (replace busy-poll)
- [ ] Multi-region support (geo-distributed agents)
- [ ] Advanced job scheduling (affinity, topology constraints)
- [ ] Built-in deployment integrations (AWS ECS, GCP Cloud Run)
- [ ] GitHub App integration (status checks, PR comments)
- [ ] Audit log export (CSV, SIEM integration)

---

## SDK Usage

```python
from ci_engine.agent.sdk import CIEngineAgent, CIEnginePlugin

class SlackPlugin(CIEnginePlugin):
    name = "slack-notify"

    def post_execute(self, context: dict, result: dict) -> dict:
        if result.get("exit_code") != 0:
            # send slack alert
            pass
        return result

agent = CIEngineAgent(
    server_url="https://ci.example.com",
    api_token="your-token",
    name="production-agent",
    tags=["docker", "linux", "production"],
    plugins=[SlackPlugin()],
    max_parallel_jobs=4,
)
agent.run()
```

---

## Common Mistakes (learned from history)

1. **Don't add `&&` to CommandSanitizer patterns** — it's already there breaking things; the fix is to remove it
2. **Don't hardcode `localhost:8000`** in agent — use `CI_ENGINE_SERVER_URL` env var
3. **Don't add new public_paths** without documenting why
4. **Don't run `Base.metadata.create_all()` in production** after Alembic is set up — it will be in conflict
5. **Don't use `asyncio.create_task()` outside an async context** — it fails silently at startup
6. **Don't store raw tokens** — always SHA256 hash before storing in `api_tokens` table

---

*Last updated: 2026-04-30. Warp session: https://app.warp.dev/session/6a336fd7-cc2e-4788-9a83-74c85f272516*
