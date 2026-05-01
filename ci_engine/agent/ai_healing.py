# SPDX-License-Identifier: MIT
# CI Engine - Autonomous AI self-healing agent plugin

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from ci_engine.core.ai_analyzer import LLMAnalyzer
from ci_engine.agent.plugins import AgentPlugin, JobContext, JobResult

logger = logging.getLogger(__name__)


class AIHealingPlugin(AgentPlugin):
    """Agent plugin that autonomously diagnoses and fixes failed jobs.

    When a job fails:
    1. Fetches the job's log tail from the server
    2. Sends the logs + pipeline YAML to the LLM for analysis
    3. POSTs the analysis to /api/jobs/{id}/ai-analysis
    4. If a fix command was suggested and auto_fix=True, POSTs to /api/jobs/{id}/ai-fix
       which patches the command and retries the job via Scheduler.retry_job()

    Completely inert (zero overhead) when CI_ENGINE_ANTHROPIC_API_KEY is unset.
    """

    name = "ai-healing"

    def __init__(
        self,
        server_url: str,
        api_key: Optional[str] = None,
        auto_fix: Optional[bool] = None,
        max_log_lines: int = 200,
        token: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._server_url = server_url.rstrip("/")
        self._analyzer = LLMAnalyzer(api_key)
        if auto_fix is None:
            auto_fix = os.environ.get("CI_ENGINE_AI_AUTO_FIX", "true").lower() not in ("false", "0", "no")
        self._auto_fix = auto_fix
        self._max_log_lines = max_log_lines
        self._token = token or os.environ.get("CI_ENGINE_AGENT_TOKEN", "")
        self._headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def post_execute(self, context: JobContext, result: JobResult) -> JobResult:
        """Called by the agent after every job execution."""
        if not self._analyzer.is_enabled():
            return result

        if result.exit_code == 0:
            return result  # nothing to analyse

        job_id = context.job_id
        try:
            log_lines = self._fetch_logs(job_id)
            pipeline_yaml = self._fetch_pipeline_yaml(context.build_id)
            analysis = self._analyzer.analyze_job_failure(
                job_id=job_id,
                label=context.label,
                command=context.command,
                exit_code=result.exit_code,
                log_lines=log_lines,
                pipeline_yaml=pipeline_yaml,
            )
            if analysis:
                self._post_analysis(job_id, analysis)
                if self._auto_fix and analysis.fixed_command:
                    self._post_ai_fix(job_id, analysis.fixed_command)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AIHealingPlugin.post_execute error: %s", exc)

        return result

    def _fetch_logs(self, job_id: int) -> list[str]:
        try:
            resp = requests.get(
                f"{self._server_url}/api/jobs/{job_id}/logs",
                headers=self._headers,
                timeout=10,
            )
            if resp.ok:
                lines = [entry.get("content", "") for entry in resp.json().get("lines", [])]
                return lines[-self._max_log_lines:]
        except Exception as exc:
            logger.debug("AIHealingPlugin._fetch_logs: %s", exc)
        return []

    def _fetch_pipeline_yaml(self, build_id: int) -> str:
        if not build_id:
            return ""
        try:
            resp = requests.get(
                f"{self._server_url}/api/builds/{build_id}",
                headers=self._headers,
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                return data.get("pipeline_yaml") or data.get("pipeline") or ""
        except Exception as exc:
            logger.debug("AIHealingPlugin._fetch_pipeline_yaml: %s", exc)
        return ""

    def _post_analysis(self, job_id: int, analysis) -> None:
        try:
            requests.post(
                f"{self._server_url}/api/jobs/{job_id}/ai-analysis",
                headers=self._headers,
                json={
                    "root_cause": analysis.root_cause,
                    "error_category": analysis.error_category,
                    "explanation": analysis.explanation,
                    "fixed_command": analysis.fixed_command,
                    "confidence": analysis.confidence,
                    "pipeline_suggestion": analysis.pipeline_suggestion,
                    "provider": analysis.provider,
                    "model": analysis.model,
                },
                timeout=10,
            )
            logger.info(
                "AIHealingPlugin: stored analysis for job %s (category=%s)",
                job_id,
                analysis.error_category,
            )
        except Exception as exc:
            logger.warning("AIHealingPlugin._post_analysis: %s", exc)

    def _post_ai_fix(self, job_id: int, fixed_command: str) -> None:
        try:
            resp = requests.post(
                f"{self._server_url}/api/jobs/{job_id}/ai-fix",
                headers=self._headers,
                json={"fixed_command": fixed_command},
                timeout=10,
            )
            if resp.ok:
                logger.info("AIHealingPlugin: auto-fix triggered for job %s", job_id)
            else:
                logger.debug(
                    "AIHealingPlugin._post_ai_fix got %s: %s", resp.status_code, resp.text[:200]
                )
        except Exception as exc:
            logger.warning("AIHealingPlugin._post_ai_fix: %s", exc)
