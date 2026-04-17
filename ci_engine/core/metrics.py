# SPDX-License-Identifier: MIT
# CI Engine - Prometheus Metrics Export


from prometheus_client import Counter, Gauge, Histogram, Info, CollectorRegistry, generate_latest


class MetricsRegistry:
    """Prometheus metrics registry for CI Engine."""

    def __init__(self):
        self.registry = CollectorRegistry()

        self.builds_total = Counter(
            "ci_engine_builds_total",
            "Total number of builds",
            ["status"],
            registry=self.registry,
        )

        self.jobs_total = Counter(
            "ci_engine_jobs_total",
            "Total number of jobs",
            ["status"],
            registry=self.registry,
        )

        self.build_duration_seconds = Histogram(
            "ci_engine_build_duration_seconds",
            "Build duration in seconds",
            registry=self.registry,
        )

        self.job_duration_seconds = Histogram(
            "ci_engine_job_duration_seconds",
            "Job duration in seconds",
            registry=self.registry,
        )

        self.agents_total = Gauge(
            "ci_engine_agents_total",
            "Total number of agents",
            ["status"],
            registry=self.registry,
        )

        self.jobs_pending = Gauge(
            "ci_engine_jobs_pending",
            "Number of pending jobs",
            registry=self.registry,
        )

        self.jobs_running = Gauge(
            "ci_engine_jobs_running",
            "Number of running jobs",
            registry=self.registry,
        )

        self.builds_running = Gauge(
            "ci_engine_builds_running",
            "Number of running builds",
            registry=self.registry,
        )

        self.queue_depth = Gauge(
            "ci_engine_queue_depth",
            "Number of jobs in queue",
            registry=self.registry,
        )

        self.agent_info = Info(
            "ci_engine_agent",
            "Agent information",
            registry=self.registry,
        )

        self.server_info = Info(
            "ci_engine_server",
            "CI Engine server information",
            registry=self.registry,
        )

        self.server_info.info({"version": "0.1.0", "name": "ci-engine"})

    def record_build(self, status: str):
        """Record a build completion."""
        self.builds_total.labels(status=status).inc()

    def record_job(self, status: str):
        """Record a job completion."""
        self.jobs_total.labels(status=status).inc()

    def record_build_duration(self, duration: float):
        """Record build duration."""
        self.build_duration_seconds.observe(duration)

    def record_job_duration(self, duration: float):
        """Record job duration."""
        self.job_duration_seconds.observe(duration)

    def update_agents(self, idle: int, busy: int, offline: int):
        """Update agent counts."""
        self.agents_total.labels(status="idle").set(idle)
        self.agents_total.labels(status="busy").set(busy)
        self.agents_total.labels(status="offline").set(offline)

    def update_jobs(self, pending: int, running: int):
        """Update job counts."""
        self.jobs_pending.set(pending)
        self.jobs_running.set(running)
        self.queue_depth.set(pending + running)

    def update_builds_running(self, count: int):
        """Update running builds count."""
        self.builds_running.set(count)

    def generate_metrics(self) -> bytes:
        """Generate Prometheus metrics output."""
        return generate_latest(self.registry)


metrics = MetricsRegistry()


def update_metrics_from_db(db):
    """Update metrics from database."""
    from ci_engine.server.models import Job, JobStatus, Agent, AgentStatus, Build, BuildStatus

    pending = db.query(Job).filter(Job.status == JobStatus.PENDING).count()
    running = db.query(Job).filter(Job.status == JobStatus.RUNNING).count()

    idle = db.query(Agent).filter(Agent.status == AgentStatus.IDLE).count()
    busy = db.query(Agent).filter(Agent.status == AgentStatus.BUSY).count()
    offline = db.query(Agent).filter(Agent.status == AgentStatus.OFFLINE).count()

    builds_running = db.query(Build).filter(Build.status == BuildStatus.RUNNING).count()

    metrics.update_jobs(pending, running)
    metrics.update_agents(idle, busy, offline)
    metrics.update_builds_running(builds_running)


class MetricsEndpoint:
    """FastAPI endpoint for Prometheus metrics."""

    @staticmethod
    def get_metrics():
        """Get Prometheus metrics."""
        from ci_engine.server.db import SessionLocal

        db = SessionLocal()
        try:
            update_metrics_from_db(db)
        finally:
            db.close()

        return metrics.generate_metrics()


metrics_endpoint = MetricsEndpoint()
