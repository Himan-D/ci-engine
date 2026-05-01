# SPDX-License-Identifier: MIT
# CI Engine - LLM-powered failure analysis and build summarization
#
# Backed by litellm — a unified interface to 100+ LLM providers.
# Provider selection, model routing, and fallback logic live here.
#
# Env vars:
#   CI_ENGINE_LLM_PROVIDER        force a specific provider (default: auto)
#   CI_ENGINE_AI_ANALYSIS_MODEL   override per-job analysis model
#   CI_ENGINE_AI_SUMMARY_MODEL    override build summary model
#   CI_ENGINE_AI_MAX_LOG_LINES    lines of logs sent to LLM (default: 200)
#   CI_ENGINE_AI_AUTO_FIX         apply fixes automatically (default: true)

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from ci_engine.core.llm_providers import (
    ProviderConfig,
    discover_provider,
    list_available_providers,
)

logger = logging.getLogger(__name__)

_MAX_LOG_LINES = int(os.environ.get("CI_ENGINE_AI_MAX_LOG_LINES", "200"))

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_JOB_FAILURE_SYSTEM = (
    "You are an expert CI/CD engineer. Analyze the failed build job and respond "
    "with a single JSON object only. No markdown fences, no prose — raw JSON."
)

_JOB_FAILURE_PROMPT = """\
A CI/CD job has failed. Diagnose it and respond with JSON only.

PIPELINE YAML:
{pipeline_yaml}

FAILED JOB:
  label      : {label}
  command    : {command}
  exit_code  : {exit_code}

LAST {log_count} LOG LINES:
{log_tail}

Respond with this EXACT JSON schema (no extra keys):
{{
  "root_cause"         : "<one-sentence root cause>",
  "error_category"     : "<one of: dependency_missing | syntax_error | test_failure | permission_error | network_error | timeout | config_error | unknown>",
  "explanation"        : "<2-4 sentences explaining the failure>",
  "fixed_command"      : "<corrected command that would fix this, or null if no safe automated fix is possible>",
  "confidence"         : <float 0.0–1.0 representing confidence in fixed_command>,
  "pipeline_suggestion": "<optional pipeline-level improvement, or null>"
}}"""

_BUILD_SUMMARY_SYSTEM = (
    "You are a senior DevOps engineer writing a concise post-build report. "
    "Respond with a single JSON object only. No markdown fences, no prose — raw JSON."
)

_BUILD_SUMMARY_PROMPT = """\
A CI/CD build has completed. Write a brief summary.

BUILD #{build_id}  branch={branch}  status={status}

JOBS (status / label / command excerpt / auto-fix applied):
{jobs_table}

Respond with this EXACT JSON schema:
{{
  "overall_health" : "<one of: healthy | degraded | failed | recovering>",
  "summary"        : "<2-3 sentences describing what happened>",
  "what_failed"    : [<list of job labels that failed — empty list if none>],
  "what_was_fixed" : [<list of job labels where AI auto-fix was applied — empty list if none>],
  "recommendations": [<1-3 concrete actionable recommendation strings>]
}}"""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    job_id: int
    root_cause: str
    error_category: str
    explanation: str
    fixed_command: Optional[str]
    confidence: float
    pipeline_suggestion: Optional[str]
    provider: str = ""
    model: str = ""


@dataclass
class BuildSummaryResult:
    build_id: int
    overall_health: str
    summary: str
    what_failed: list[str] = field(default_factory=list)
    what_was_fixed: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""


# ---------------------------------------------------------------------------
# LLMAnalyzer
# ---------------------------------------------------------------------------

class LLMAnalyzer:
    """CI-specific wrapper around litellm.

    Responsibilities:
    - Provider/model selection via ProviderConfig registry
    - Ordered fallback: primary → next available → … → give up
    - Prompt construction and JSON response parsing
    - Graceful no-op when no provider is configured

    All actual HTTP calls go through ``litellm.completion()``, which handles
    request signing, retries on 429s, and provider-specific quirks.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        # Legacy: bare api_key always means Anthropic
        if api_key and not os.environ.get("CI_ENGINE_ANTHROPIC_API_KEY"):
            os.environ["CI_ENGINE_ANTHROPIC_API_KEY"] = api_key

        self._primary: Optional[ProviderConfig] = discover_provider()
        self._fallbacks: list[ProviderConfig] = [
            p for p in list_available_providers() if p is not self._primary
        ]

        if self._primary:
            logger.info(
                "LLMAnalyzer ready  provider=%s  fallbacks=[%s]",
                self._primary.name,
                ", ".join(p.name for p in self._fallbacks),
            )
        else:
            logger.debug(
                "LLMAnalyzer disabled — set one of: "
                "CI_ENGINE_ANTHROPIC_API_KEY, CI_ENGINE_OPENROUTER_API_KEY, "
                "CI_ENGINE_OPENAI_API_KEY, CI_ENGINE_GROQ_API_KEY, "
                "CI_ENGINE_TOGETHER_API_KEY, CI_ENGINE_MISTRAL_API_KEY, "
                "CI_ENGINE_COHERE_API_KEY, CI_ENGINE_GEMINI_API_KEY, "
                "or CI_ENGINE_OLLAMA_ENABLED=1"
            )

    def is_enabled(self) -> bool:
        return self._primary is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_job_failure(
        self,
        job_id: int,
        label: str,
        command: str,
        exit_code: int,
        log_lines: list[str],
        pipeline_yaml: str = "",
    ) -> Optional[AnalysisResult]:
        """Diagnose a failed job using the fast/cheap analysis model."""
        if not self.is_enabled():
            return None

        tail = log_lines[-_MAX_LOG_LINES:]
        user = _JOB_FAILURE_PROMPT.format(
            pipeline_yaml=(pipeline_yaml[:2000] or "(unavailable)"),
            label=label,
            command=command or "(none)",
            exit_code=exit_code,
            log_count=len(tail),
            log_tail="\n".join(tail) or "(no logs)",
        )

        completion = self._call(
            system=_JOB_FAILURE_SYSTEM,
            user=user,
            use_summary_model=False,
            max_tokens=1024,
        )
        if not completion:
            return None

        text, provider_name, model_name = completion
        try:
            data = _extract_json(text)
            return AnalysisResult(
                job_id=job_id,
                root_cause=str(data.get("root_cause", "")),
                error_category=str(data.get("error_category", "unknown")),
                explanation=str(data.get("explanation", "")),
                fixed_command=data.get("fixed_command") or None,
                confidence=float(data.get("confidence", 0.5)),
                pipeline_suggestion=data.get("pipeline_suggestion") or None,
                provider=provider_name,
                model=model_name,
            )
        except Exception as exc:
            logger.warning(
                "LLMAnalyzer: JSON parse error for job %s: %s  raw=%r",
                job_id, exc, text[:300],
            )
            return None

    def generate_build_summary(
        self,
        build_id: int,
        branch: str,
        status: str,
        jobs: list[dict],
    ) -> Optional[BuildSummaryResult]:
        """Produce a build-level summary using the capable summary model."""
        if not self.is_enabled():
            return None

        rows = []
        for j in jobs:
            label = j.get("label") or j.get("name") or f"job-{j.get('id')}"
            cmd = (j.get("command") or "")[:80]
            tag = " [auto-fixed]" if j.get("ai_fix_applied") else ""
            rows.append(f"  [{j.get('status','?')}] {label}: {cmd}{tag}".rstrip())

        user = _BUILD_SUMMARY_PROMPT.format(
            build_id=build_id,
            branch=branch or "unknown",
            status=status,
            jobs_table="\n".join(rows) or "  (no jobs)",
        )

        completion = self._call(
            system=_BUILD_SUMMARY_SYSTEM,
            user=user,
            use_summary_model=True,
            max_tokens=2048,
        )
        if not completion:
            return None

        text, provider_name, model_name = completion
        try:
            data = _extract_json(text)
            return BuildSummaryResult(
                build_id=build_id,
                overall_health=str(data.get("overall_health", "unknown")),
                summary=str(data.get("summary", "")),
                what_failed=list(data.get("what_failed") or []),
                what_was_fixed=list(data.get("what_was_fixed") or []),
                recommendations=list(data.get("recommendations") or []),
                provider=provider_name,
                model=model_name,
            )
        except Exception as exc:
            logger.warning(
                "LLMAnalyzer: JSON parse error for build summary %s: %s  raw=%r",
                build_id, exc, text[:300],
            )
            return None

    # ------------------------------------------------------------------
    # Internal — litellm call with ordered fallback
    # ------------------------------------------------------------------

    def _call(
        self,
        system: str,
        user: str,
        use_summary_model: bool,
        max_tokens: int,
    ) -> Optional[tuple[str, str, str]]:
        """Make a litellm completion call, falling back through all providers.

        Returns (response_text, provider_name, model_name) or None.
        """
        try:
            import litellm  # type: ignore[import]
            litellm.suppress_debug_info = True
            litellm.set_verbose = False
        except ImportError:
            logger.error(
                "litellm is not installed. Run: pip install 'ci-engine[ai]'"
            )
            return None

        providers_to_try = [self._primary] + self._fallbacks if self._primary else []
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ]

        for cfg in providers_to_try:
            model = cfg.get_summary_model() if use_summary_model else cfg.get_analysis_model()
            kw = cfg.litellm_kwargs(model=model, max_tokens=max_tokens)
            kw["messages"] = messages

            try:
                resp = litellm.completion(**kw)
                text = (resp.choices[0].message.content or "").strip()
                logger.debug(
                    "LLMAnalyzer: %s/%s responded (%d chars)",
                    cfg.name, model, len(text),
                )
                return text, cfg.name, model
            except Exception as exc:
                logger.warning(
                    "LLMAnalyzer: provider=%r model=%r failed: %s — trying next",
                    cfg.name, model, exc,
                )

        logger.error("LLMAnalyzer: all %d provider(s) failed", len(providers_to_try))
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Extract the first JSON object from an LLM response.

    Handles:
    - Raw JSON
    - ```json … ``` fences
    - Prose followed by JSON
    """
    text = text.strip()

    # Fast path: already valid JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

    # Find outermost { … }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON in response: {text[:200]!r}")
