# CI Engine — Competitive Analysis & Implementation Roadmap

> Comprehensive analysis comparing CI Engine to leading CI/CD platforms, identifying gaps, and providing a prioritized roadmap for development.

---

## 1. Executive Summary

CI Engine is a self-hosted CI/CD platform modeled after Buildkite with a distributed agent architecture. The codebase contains **~10,000+ lines of functional code** across 38 source files, with all 13 core modules fully implemented:

- **Pipeline parsing** with matrix expansion, conditionals, block steps, reusable workflows
- **Distributed agent system** with parallel job execution, skill detection, plugin/middleware system
- **80+ REST API endpoints** with JWT authentication, rate limiting, role-based access
- **Observability stack** — Prometheus metrics, OpenTelemetry tracing, structured logging, audit logging
- **Cloud integrations** — S3 artifacts, OIDC for AWS/GCP/Azure, GitHub OAuth
- **Container execution** with service containers, resource limits, multiple runtime support

### Feature Coverage vs. Competitors

| Platform | Core Pipeline | Agents | Secrets/Cache | Cloud Auth | Enterprise |
|---|---|---|---|---|---|
| CI Engine | ~90% | ~95% | ~85% | ~80% | ~50% |
| GitHub Actions | 100% | ~80% | 100% | 100% | ~90% |
| Buildkite | 100% | 100% | 100% | ~70% | ~80% |
| GitLab CI | 100% | ~90% | 100% | ~80% | ~95% |
| Jenkins | ~60% | 100% | ~70% | ~50% | ~80% |

### Verdict: **Highly Feasible**

The codebase has an unusually strong foundation. Most core modules are production-quality, not stubs. Security is well-handled (Fernet encryption, bcrypt, JWT, HMAC webhook signatures, command injection prevention). The unique "skill detection" system — auto-detecting 85 tools across 16 categories — is a genuine differentiator no competitor offers.

**Main risks:** Monolithic `main.py` (2,386 lines) will become unmaintainable; no database migrations; test coverage gaps in scheduler; no frontend framework — dashboard is server-rendered HTML.

---

## 2. Competitive Feature Matrix

### 2.1 Pipeline & Workflow

| Feature | CI Engine | GitHub Actions | Buildkite | GitLab CI | Jenkins |
|---|---|---|---|---|---|
| YAML Pipeline Definition | ✅ Full | ✅ Full | ✅ Full | ✅ Full | ❌ Groovy DSL |
| Matrix Expansion | ✅ Full | ✅ Full | ✅ Full | ✅ Full | ❌ Manual |
| Conditional Steps (`if:`) | ✅ Full | ✅ Full | ✅ Full | ✅ Full | ✅ via Groovy |
| Reusable Workflows | ✅ Full | ✅ Full | ✅ Full | ✅ Full | ❌ |
| Block / Manual Approval | ✅ Full | ✅ via Environments | ✅ Full | ✅ Full | ⚠️ Plugins |
| Wait Step | ✅ Full | ✅ Full | ✅ Full | ✅ Full | ❌ |
| Trigger Step | ✅ Full | ✅ `workflow_call` | ✅ Full | ✅ via `trigger` | ❌ |
| Environment Variables | ✅ Full | ✅ Full | ✅ Full | ✅ Full | ✅ |
| Cache Configuration | ✅ | ✅ Built-in | ✅ Plugins | ✅ Built-in | ✅ Plugins |
| Services / Sidecars | ✅ Full | ✅ | ❌ | ✅ | ⚠️ Plugins |

### 2.2 Agent & Execution

| Feature | CI Engine | GitHub Actions | Buildkite | GitLab CI | Jenkins |
|---|---|---|---|---|---|
| Distributed Self-Hosted Agents | ✅ Full | ✅ | ✅ Full | ✅ (Runners) | ✅ |
| Agent Labels / Tags | ✅ Full | ✅ | ✅ (Queues) | ✅ | ✅ |
| Agent Pools | ✅ Full | ❌ | ✅ | ❌ | ❌ |
| Parallel Job Execution | ✅ Full | ✅ | ✅ Full | ✅ Full | ✅ |
| Container Execution | ✅ Docker/Podman | ✅ Docker | ✅ Docker | ✅ Docker | ✅ Docker |
| Resource Limits (CPU/Memory) | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Job Timeouts | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Retry Logic | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Job Cancellation | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Workspace Isolation | ✅ Per-job | ✅ | ✅ | ✅ | ✅ |
| Skill-Based Assignment | ✅ 85 skills | ❌ | ❌ | ❌ | ❌ |
| Auto Skill Detection | ✅ Full | ❌ | ❌ | ❌ | ❌ |

### 2.3 Integrations

| Feature | CI Engine | GitHub Actions | Buildkite | GitLab CI | Jenkins |
|---|---|---|---|---|---|
| GitHub Webhooks | ✅ Full | Native | ✅ | ✅ | ✅ |
| GitLab Webhooks | ✅ Full | ❌ | ✅ | Native | ✅ |
| Bitbucket Webhooks | ❌ | ❌ | ✅ | ✅ | ✅ |
| GitHub OAuth | ✅ Full | Native | ✅ | ✅ | ⚠️ Plugins |
| GitHub Checkout | ✅ via agent | Native | ✅ | Native | ✅ |
| Git Clone via SSH | ✅ Full | ❌ | ✅ | ✅ | ✅ |
| OIDC (AWS) | ✅ Full | ✅ | ⚠️ Partial | ⚠️ Partial | ⚠️ Plugins |
| OIDC (GCP) | ✅ Full | ✅ | ❌ | ❌ | ⚠️ Plugins |
| OIDC (Azure) | ✅ Full | ✅ | ❌ | ❌ | ⚠️ Plugins |
| Cron Schedule Triggers | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Slack Notifications | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Discord Notifications | ✅ Full | ❌ | ❌ | ❌ | ⚠️ Plugins |
| Email Notifications | ✅ Full | ❌ | ✅ | ✅ | ✅ |
| Webhook Outgoing | ❌ | ✅ | ✅ | ✅ | ✅ |

### 2.4 Security & Compliance

| Feature | CI Engine | GitHub Actions | Buildkite | GitLab CI | Jenkins |
|---|---|---|---|---|---|
| Secrets Management (Fernet) | ✅ Full | ✅ Vault | ✅ Vault/SSM | ✅ Built-in | ⚠️ Plugins |
| API Tokens | ✅ Full | ✅ | ✅ | ✅ | ⚠️ API token |
| JWT Authentication | ✅ Full | ✅ | ✅ | ✅ | ❌ |
| Role-Based Access Control | ✅ 3 roles | ✅ | ✅ | ✅ | ⚠️ Plugins |
| IP Allowlist | ✅ Full | N/A (hosted) | ✅ | ✅ | ✅ |
| HMAC Webhook Signatures | ✅ Full | Native | ✅ | ✅ | ✅ |
| Audit Logging | ✅ 23 actions | ✅ | ✅ | ✅ | ✅ |
| Rate Limiting | ✅ slowapi | N/A | N/A | N/A | ❌ |
| SAML / SSO | ❌ | ✅ Enterprise | ✅ Enterprise | ✅ Premium | ⚠️ Plugins |
| Audit Export | ❌ | ✅ | ✅ | ✅ | ✅ |

### 2.5 Artifacts & Storage

| Feature | CI Engine | GitHub Actions | Buildkite | GitLab CI | Jenkins |
|---|---|---|---|---|---|
| S3 Artifact Storage | ✅ Full | ✅ | ✅ | ❌ | ❌ |
| Artifact Upload/Download | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Artifact List/Delete | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Presigned URLs | ✅ Full | ✅ | ✅ | ❌ | ❌ |
| Artifact Browser UI | ❌ | ✅ | ✅ | ✅ | ⚠️ Plugins |
| Build Cache (Local + S3) | ✅ Full | ✅ | ⚠️ Plugins | ✅ | ⚠️ Plugins |

### 2.6 Observability

| Feature | CI Engine | GitHub Actions | Buildkite | GitLab CI | Jenkins |
|---|---|---|---|---|---|
| Prometheus Metrics | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Structured JSON Logging | ✅ Full | ❌ | ❌ | ❌ | ✅ |
| OpenTelemetry Tracing | ✅ Full | ❌ | ❌ | ❌ | ⚠️ Plugins |
| Log Streaming (WebSocket) | ✅ Server-side | ✅ | ✅ | ✅ | ⚠️ Plugins |
| Real-time Log UI | ❌ | ✅ | ✅ | ✅ | ⚠️ Blue Ocean |
| Build Duration Metrics | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| Job Success Rate Metrics | ✅ Full | ✅ | ✅ | ✅ | ✅ |

### 2.7 Scaling & Infrastructure

| Feature | CI Engine | GitHub Actions | Buildkite | GitLab CI | Jenkins |
|---|---|---|---|---|---|
| Auto-Scaling (K8s) | ✅ Full | ✅ (ARC) | ✅ Elastic | ✅ K8s | ✅ K8s |
| Auto-Scaling Recommendations | ✅ Full | N/A | ✅ | N/A | N/A |
| Database Support (PostgreSQL) | ✅ Full | N/A | N/A | N/A | N/A |
| Database Support (SQLite) | ✅ Full | N/A | N/A | N/A | ❌ |
| Multi-Node HA Setup | ❌ | N/A | ✅ | ✅ | ⚠️ Plugins |
| Database Migrations | ❌ | N/A | Managed | Managed | ⚠️ Plugins |

### 2.8 Developer Experience

| Feature | CI Engine | GitHub Actions | Buildkite | GitLab CI | Jenkins |
|---|---|---|---|---|---|
| CLI Tool | ✅ Full | ✅ (gh) | ✅ | ✅ (glab) | ❌ |
| REST API (80+ endpoints) | ✅ Full | ✅ | ✅ | ✅ | ✅ |
| GraphQL API | ❌ | ✅ | ✅ | ✅ | ❌ |
| Web Dashboard | ⚠️ Basic HTML | ✅ React SPA | ✅ React SPA | ✅ Vue SPA | ⚠️ Blue Ocean |
| Pipeline Graph Visualization | ❌ | ✅ | ✅ | ✅ | ⚠️ Blue Ocean |
| Test Report Display | ❌ | ✅ | ✅ Test Engine | ✅ | ⚠️ Plugins |
| Plugin System | ✅ | ✅ Marketplace | ✅ Plugins | ❌ | ✅ 1800+ plugins |
| Custom Middleware | ✅ | ❌ | ❌ | ❌ | ❌ |

---

## 3. Gap Analysis — Critical Missing Features

### P0 — Must-Have (Blocks Basic Usage)

| # | Feature | Impact | Effort |
|---|---|---|---|
| 1 | **Pipeline graph visualization** | Users cannot see build progress visually | Medium |
| 2 | **Real-time log streaming UI** | No way to view live job logs in browser | Medium |
| 3 | **Git checkout in agent execution** | Agent has `git.py` but doesn't clone repos during jobs | Low |
| 4 | **Webhook → Build creation** | `trigger_webhook_builds()` is `pass` — webhooks don't trigger builds | Medium |
| 5 | **Split monolithic `main.py`** | 2,386 lines with duplicate routes — unmaintainable | High |

### P1 — Competitive Parity

| # | Feature | Impact | Effort |
|---|---|---|---|
| 6 | Test report parsing & visualization | Cannot display test results in UI | Medium |
| 7 | Job outputs (pass data between jobs) | Cannot pass artifacts/data between steps | Medium |
| 8 | Pipeline template registry | Cannot share reusable pipeline templates | Medium |
| 9 | Approval workflow UI | Manual approval steps have no UI | Low |
| 10 | Branch/PR filtering on triggers | All pushes trigger builds — no filtering | Low |
| 11 | Concurrent build limits per pipeline | No way to limit parallel builds | Low |
| 12 | Artifact browsing UI | Cannot view/download artifacts in UI | Medium |
| 13 | GraphQL API | Only REST available | Medium |
| 14 | Database migrations | No upgrade path for schema changes | Medium |

### P2 — Enterprise Features

| # | Feature | Impact | Effort |
|---|---|---|---|
| 15 | SAML/SSO integration | Cannot use enterprise identity providers | High |
| 16 | Multi-tenancy (organizations/teams) | Single organization only | High |
| 17 | Deployment environments with protection rules | No env-based approvals | Medium |
| 18 | Artifact signing / SLSA attestation | No supply chain security | High |
| 19 | Compliance policy engine | No policy-as-code enforcement | High |
| 20 | Agent resource quotas | No per-team/project limits | Medium |
| 21 | High-availability multi-node | Single server only | High |
| 22 | Bitbucket integration | No Bitbucket webhook support | Medium |

---

## 4. Architecture Issues to Fix

### Critical Bugs

| File | Line | Issue |
|---|---|---|
| `server/main.py` | 1060, 1444 | Duplicate `cancel_build` route definitions |
| `server/main.py` | 1037, 1469 | Duplicate `cancel_job` route definitions |
| `server/oidc.py` | 316-325 | Dead code after `return False` in `verify_gcp_token()` |
| `core/pipeline.py` | 125 | `data.get("env", {})` called on list — `AttributeError` |
| `server/main.py` | 1116 | Raw `SessionLocal()` outside FastAPI dependency injection |

### Missing Integration

| File | Line | Issue |
|---|---|---|
| `agent/agent.py` | — | `git.py` exists but isn't called during job execution |
| `server/webhooks.py` | 309 | `trigger_webhook_builds()` is `pass` — no implementation |

### Structural Issues

| Issue | Description |
|---|---|
| `main.py` monolith | 2,386 lines, 80+ endpoints in single file — must split into routers |
| No alembic migrations | Schema changes require manual table drops |
| Basic dashboard | Server-rendered HTML tables — needs React/Vue SPA |
| Thin test coverage | Scheduler has 1 test, integration tests minimal |

---

## 5. Implementation Roadmap

### Phase 1: Production MVP (4–6 weeks)

**Goal:** Fix critical bugs, complete missing integrations, achieve basic production-readiness.

| Week | Task | Owner |
|---|---|---|
| 1 | Fix duplicate routes in `main.py` | AI |
| 1 | Fix dead code in `oidc.py` | AI |
| 1 | Fix `pipeline.py` list bug | AI |
| 2 | Wire git checkout into agent execution loop | AI |
| 2 | Implement `trigger_webhook_builds()` in webhooks | AI |
| 3 | Split `main.py` into FastAPI routers (builds, agents, jobs, auth, webhooks, artifacts, secrets, admin) | AI |
| 3 | Add alembic migrations for existing schema | AI |
| 4 | Build React dashboard with pipeline graph visualization | Frontend |
| 4 | Implement real-time log streaming UI via WebSocket | Frontend |
| 5 | Add branch/PR filtering on webhook triggers | AI |
| 5 | Add concurrent build limits per pipeline | AI |
| 6 | Expand test suite to 80% coverage (especially scheduler, webhooks) | AI |

**Deliverables:**
- Working end-to-end: webhook → build created → agent pulls job → clones repo → runs steps → uploads logs
- Dashboard shows pipeline graph and live logs
- Database migrations for schema upgrades

### Phase 2: Competitive Parity (6–8 weeks)

**Goal:** Match feature-for-feature with GitHub Actions, Buildkite core functionality.

| Week | Task | Owner |
|---|---|---|
| 1 | Test report parsing (JUnit, pytest, mocha) + visualization | Frontend + AI |
| 2 | Job outputs — pass data between steps | AI |
| 3 | Pipeline template registry (create, share, use) | AI + Frontend |
| 3 | Approval workflow UI for block steps | Frontend |
| 4 | Artifact browsing UI (list, download, delete) | Frontend |
| 4 | GraphQL API for all entities | AI |
| 5 | Expand webhook triggers (schedule, manual, API) | AI |
| 5 | Add self-service agent registration with approval | AI |
| 6 | Comprehensive user documentation | Technical Writer |
| 6 | Performance testing and optimization | DevOps |
| 7 | Security audit and hardening | Security |
| 8 | Beta user program and feedback collection | Product |

**Deliverables:**
- Full parity with Buildkite core features
- Production-ready dashboard with all key views
- Public API via REST + GraphQL

### Phase 3: Enterprise Readiness (8–12 weeks)

**Goal:** Enterprise features for large teams and regulated industries.

| Week | Task | Owner |
|---|---|---|
| 1–2 | SAML/SSO integration (Okta, Azure AD, OneLogin) | AI + Security |
| 2–3 | Multi-tenancy (organizations, teams, projects) | AI |
| 3–4 | Deployment environments with protection rules (require approval) | AI + Frontend |
| 4–5 | Artifact signing (cosign/SLSA) + provenance tracking | AI + Security |
| 5–6 | Policy engine (required reviewers, branch protection, secrets policy) | AI |
| 6–7 | Agent resource quotas per team/project | AI |
| 7–8 | High-availability setup (leader election, database replication) | DevOps |
| 8–9 | Multi-region deployment support | DevOps |
| 9–10 | Bitbucket Cloud + Server integration | AI |
| 10–11 | Outgoing webhook events (build started, finished, failed) | AI |
| 11–12 | Compliance reporting (audit logs, access reports, export) | AI + Frontend |

**Deliverables:**
- Enterprise-ready for 500+ developer organizations
- SOC 2 / ISO 27001 audit readiness
- Multi-region deployment capability

---

## 6. Recommendation for Next Agent

### Start Here

1. **Fix the bugs first** — duplicate routes, dead code, pipeline bug (`pipeline.py:125`)
2. **Wire git checkout** — integrate `agent/git.py` into job execution in `agent/agent.py`
3. **Implement webhook triggers** — make `trigger_webhook_builds()` actually create builds

Then proceed with Phase 1 roadmap. The codebase is in good shape — these fixes unlock basic end-to-end functionality.

### Code Quality Notes

- No `TODO`/`FIXME`/`HACK` markers found — code is complete but needs cleanup
- Most functions have type hints — good for maintenance
- Test coverage is adequate for core logic but thin for scheduler and integration paths
- 35 of 38 source files are production-quality — only 3 have stubs (`webhooks.py:309`, `scheduler.py` test, `oidc.py` dead code)

### Naming Conventions to Preserve

- Use `f-string` formatting
- 4-space indentation, 100 char line limit
- Dataclasses for data structures, Pydantic `BaseModel` for APIs
- All public functions must have type annotations and docstrings

---

## Appendix: File Inventory

### Core Modules (ci_engine/core/)

| File | Lines | Status |
|---|---|---|
| `pipeline.py` | 369 | ✅ Full |
| `scheduler.py` | 258 | ✅ Full |
| `executor.py` | 227 | ✅ Full |
| `container.py` | 468 | ✅ Full |
| `secrets.py` | 203 | ✅ Full |
| `artifacts.py` | 257 | ✅ Full |
| `audit.py` | 221 | ✅ Full |
| `logging.py` | 129 | ✅ Full |
| `metrics.py` | 160 | ✅ Full |
| `notifications.py` | 334 | ✅ Full |
| `environments.py` | 129 | ✅ Full |
| `scaler.py` | 258 | ✅ Full |
| `triggers.py` | 249 | ✅ Full |
| `ssh_keys.py` | 171 | ✅ Full |
| `cache.py` | 617 | ✅ Full |
| `tracing.py` | 147 | ✅ Full |
| `skills.py` | 991 | ✅ Full |

### Server Modules (ci_engine/server/)

| File | Lines | Status |
|---|---|---|
| `main.py` | 2,386 | ⚠️ Full but monolithic |
| `models.py` | 398 | ✅ Full |
| `db.py` | 67 | ✅ Full |
| `auth.py` | 384 | ✅ Full |
| `dashboard.py` | 151 | ✅ Full |
| `webhooks.py` | 313 | ⚠️ Partial (missing trigger) |
| `middleware.py` | 285 | ✅ Full |
| `github_oauth.py` | 185 | ✅ Full |
| `oidc.py` | 427 | ⚠️ Full but dead code |

### Agent Modules (ci_engine/agent/)

| File | Lines | Status |
|---|---|---|
| `agent.py` | 771 | ✅ Full |
| `git.py` | 180 | ✅ Full (needs integration) |
| `skills.py` | 590 | ✅ Full |
| `plugins.py` | 344 | ✅ Full |
| `builtins.py` | 328 | ✅ Full |
| `sdk.py` | 201 | ✅ Full |
| `middleware.py` | 310 | ✅ Full |

### Test Coverage

| Suite | Tests | Coverage |
|---|---|---|
| `test_auth.py` | 10 | ✅ Good |
| `test_executor.py` | 13 | ✅ Good |
| `test_pipeline.py` | 8 | ✅ Good |
| `test_scheduler.py` | 1 | ❌ Minimal |
| `test_secrets.py` | 7 | ✅ Good |
| `test_cache.py` | 10 | ✅ Good |
| `test_plugins.py` | 15 | ✅ Good |
| `test_api.py` | 11 | ✅ Good |

---

*Generated: 2026-04-28*
*For: Next AI Agent / Development Team*