# Changelog

All notable changes to CI Engine will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-04-27

### Added

#### Core Engine
- **Plugin System** - Hook into job execution lifecycle (pre_execute, post_execute, on_error, on_heartbeat, on_shutdown)
- **Middleware System** - Transform jobs before/after execution
- **Agent SDK** - Create custom agents with Python SDK
- **Built-in Plugins** - Logging, metrics, caching, timeout, environment, validation

#### Security
- **Secrets Injection** - Fernet-encrypted secrets with get_build_env_vars() for builds
- **Command Sanitization** - CommandInjectionError prevents shell injection attacks
- **OIDC Verification** - JWT signature verification for cloud providers
- **Audit Logging** - Full audit trail for compliance

#### Kubernetes
- **HorizontalPodAutoscaler** - Scale agents based on CPU/memory
- **PodDisruptionBudget** - Ensure high availability during upgrades
- **Ingress** - External access with TLS

#### Monitoring
- **Prometheus Rules** - Alerting rules for high error rate, queue time, agent offline
- **Recording Rules** - Pre-aggregate metrics for efficient queries
- **Grafana Dashboard** - Production overview with job stats, CPU, memory
- **AlertManager** - Slack/Discord webhook integration

#### Backup & Recovery
- **Automated Backups** - CronJob for daily encrypted database backups
- **S3 Integration** - Store backups in S3 with encryption
- **Restore Script** - Point-in-time recovery

#### API Enhancements
- Real-time **WebSocket** log streaming
- **Agent pools** with scaling policies
- **Agent labels** for flexible job matching
- **Drain mode** for graceful agent shutdown
- **Artifact storage** with S3 backend
- **Cross-step cache** for dependency caching

### Changed

- Migrated from deprecated `@app.on_event` to **FastAPI lifespan** handlers
- Added **slowapi rate limiting** for API endpoints
- Updated `datetime.utcnow()` to `datetime.now(timezone.utc)` (Python 3.12+)
- Updated Pydantic to use `model_config = ConfigDict(from_attributes=True)`

### Fixed

- Error handling in executor with proper timeout
- Database connection cleanup on shutdown
- WebSocket connection draining on graceful shutdown

### Deprecated

- OIDC implementation (still needs testing)

---

## [0.0.5] - 2024-03-15

### Added
- Visual pipeline editor with React Flow
- RBAC enforcement to admin endpoints
- RemoteCache with S3 backend

---

## [0.0.4] - 2024-02-01

### Added
- Custom agent integration
- WebSocket streaming
- Kubernetes manifests

---

## [0.0.3] - 2024-01-15

### Added
- Tracing, logging, metrics (OpenTelemetry)
- Comprehensive test suite

---

## [0.0.2] - 2024-01-01

### Added
- Agent skills system (100 skills)
- Kubernetes auto-scaling

---

## [0.0.1] - 2023-12-01

### Added
- Initial release
- FastAPI server
- Build agents
- Pipeline execution