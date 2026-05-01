# SPDX-License-Identifier: MIT
# CI Engine - LLM provider configuration registry
#
# This module is intentionally implementation-free: it only holds provider
# configs (env var names, default model names, litellm call kwargs).
# All actual LLM calls go through litellm in ai_analyzer.py.
#
# ┌─────────────────────────────────────────────────────────────────────────┐
# │  Supported providers and env vars                                        │
# ├────────────────────────┬───────────────────────────────────────────────┤
# │  anthropic             │  CI_ENGINE_ANTHROPIC_API_KEY                   │
# │  openrouter            │  CI_ENGINE_OPENROUTER_API_KEY                  │
# │  openai                │  CI_ENGINE_OPENAI_API_KEY                      │
# │  groq                  │  CI_ENGINE_GROQ_API_KEY                        │
# │  together              │  CI_ENGINE_TOGETHER_API_KEY                    │
# │  mistral               │  CI_ENGINE_MISTRAL_API_KEY                     │
# │  cohere                │  CI_ENGINE_COHERE_API_KEY                      │
# │  gemini                │  CI_ENGINE_GEMINI_API_KEY                      │
# │  bedrock               │  AWS_ACCESS_KEY_ID (+ AWS_SECRET_ACCESS_KEY)   │
# │  ollama (local)        │  CI_ENGINE_OLLAMA_ENABLED=1                    │
# └────────────────────────┴───────────────────────────────────────────────┘
#
# Priority order: first key found wins.
# Force a provider: CI_ENGINE_LLM_PROVIDER=groq
# Override models:  CI_ENGINE_AI_ANALYSIS_MODEL / CI_ENGINE_AI_SUMMARY_MODEL

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Provider config dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """Declarative config for one LLM provider."""

    name: str
    # Environment variable that holds the API key (empty = keyless)
    api_key_env: str
    # litellm model strings (e.g. "groq/llama-3.1-8b-instant")
    analysis_model: str
    summary_model: str
    # Static litellm call kwargs (api_base, extra_headers, etc.)
    call_kwargs: dict = field(default_factory=dict)
    # If set, api_base is re-read from this env var at every call (dynamic providers like Ollama)
    base_url_env: str = ""
    # Human-readable description
    description: str = ""

    @property
    def api_key(self) -> Optional[str]:
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env) or None

    def is_available(self) -> bool:
        """True when the provider's credentials are present."""
        if not self.api_key_env:
            # Keyless providers (Ollama, Bedrock via IAM) have their own check
            return self._keyless_available()
        return bool(self.api_key)

    def _keyless_available(self) -> bool:
        if self.name == "ollama":
            return bool(
                os.environ.get("CI_ENGINE_OLLAMA_ENABLED", "").lower() in ("1", "true", "yes")
                or os.environ.get("CI_ENGINE_OLLAMA_BASE_URL")
            )
        if self.name == "bedrock":
            return bool(os.environ.get("AWS_ACCESS_KEY_ID"))
        return False

    def get_analysis_model(self) -> str:
        return os.environ.get("CI_ENGINE_AI_ANALYSIS_MODEL") or self.analysis_model

    def get_summary_model(self) -> str:
        return os.environ.get("CI_ENGINE_AI_SUMMARY_MODEL") or self.summary_model

    def litellm_kwargs(self, model: str, max_tokens: int) -> dict:
        """Build the full kwargs dict for a litellm.completion() call.

        Static call_kwargs are merged first; dynamic base_url_env (if set) is
        resolved at call time so runtime env changes are picked up correctly.
        """
        kw: dict = {"model": model, "max_tokens": max_tokens}
        if self.api_key:
            kw["api_key"] = self.api_key
        kw.update(self.call_kwargs)
        # Dynamic api_base: re-read from env at call time (e.g. Ollama URL)
        if self.base_url_env:
            runtime_url = os.environ.get(self.base_url_env)
            if runtime_url:
                kw["api_base"] = runtime_url
        return kw


# ---------------------------------------------------------------------------
# Provider registry — ordered by preference
# ---------------------------------------------------------------------------

_REGISTRY: list[ProviderConfig] = [
    ProviderConfig(
        name="anthropic",
        api_key_env="CI_ENGINE_ANTHROPIC_API_KEY",
        analysis_model="claude-haiku-4-5-20251001",
        summary_model="claude-sonnet-4-6",
        description="Anthropic Claude (direct API)",
    ),
    ProviderConfig(
        name="openrouter",
        api_key_env="CI_ENGINE_OPENROUTER_API_KEY",
        analysis_model="openrouter/anthropic/claude-haiku-4-5",
        summary_model="openrouter/anthropic/claude-sonnet-4-6",
        call_kwargs={
            "api_base": "https://openrouter.ai/api/v1",
            "extra_headers": {
                "HTTP-Referer": "https://github.com/ci-engine/ci-engine",
                "X-Title": "CI Engine",
            },
        },
        description="OpenRouter — 200+ models via one key",
    ),
    ProviderConfig(
        name="openai",
        api_key_env="CI_ENGINE_OPENAI_API_KEY",
        analysis_model="gpt-4o-mini",
        summary_model="gpt-4o",
        description="OpenAI GPT",
    ),
    ProviderConfig(
        name="groq",
        api_key_env="CI_ENGINE_GROQ_API_KEY",
        analysis_model="groq/llama-3.1-8b-instant",
        summary_model="groq/llama-3.3-70b-versatile",
        description="Groq — ultra-fast Llama inference",
    ),
    ProviderConfig(
        name="together",
        api_key_env="CI_ENGINE_TOGETHER_API_KEY",
        analysis_model="together_ai/meta-llama/Llama-3.2-3B-Instruct-Turbo",
        summary_model="together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
        description="Together AI — open-source model serving",
    ),
    ProviderConfig(
        name="mistral",
        api_key_env="CI_ENGINE_MISTRAL_API_KEY",
        analysis_model="mistral/mistral-small-latest",
        summary_model="mistral/mistral-large-latest",
        description="Mistral AI",
    ),
    ProviderConfig(
        name="cohere",
        api_key_env="CI_ENGINE_COHERE_API_KEY",
        analysis_model="command-r",
        summary_model="command-r-plus",
        description="Cohere Command",
    ),
    ProviderConfig(
        name="gemini",
        api_key_env="CI_ENGINE_GEMINI_API_KEY",
        analysis_model="gemini/gemini-1.5-flash",
        summary_model="gemini/gemini-1.5-pro",
        description="Google Gemini",
    ),
    ProviderConfig(
        name="bedrock",
        api_key_env="",   # uses AWS_ACCESS_KEY_ID / IAM role
        analysis_model="bedrock/anthropic.claude-haiku-4-5-20251001-v1:0",
        summary_model="bedrock/anthropic.claude-sonnet-4-6-20250514-v1:0",
        description="AWS Bedrock (uses AWS credentials)",
    ),
    ProviderConfig(
        name="ollama",
        api_key_env="",   # keyless — local
        analysis_model="ollama/llama3.2",
        summary_model="ollama/llama3.1:70b",
        call_kwargs={"api_base": "http://localhost:11434"},  # static default
        base_url_env="CI_ENGINE_OLLAMA_BASE_URL",            # overridden at call time
        description="Ollama — local self-hosted models",
    ),
]

# Index for O(1) lookup by name
_BY_NAME: dict[str, ProviderConfig] = {p.name: p for p in _REGISTRY}


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def discover_provider() -> Optional[ProviderConfig]:
    """Return the highest-priority available provider.

    Respects ``CI_ENGINE_LLM_PROVIDER`` for an explicit override.
    """
    forced = os.environ.get("CI_ENGINE_LLM_PROVIDER", "").strip().lower()
    if forced:
        cfg = _BY_NAME.get(forced)
        if cfg and cfg.is_available():
            return cfg
        if cfg and not cfg.is_available():
            import logging
            logging.getLogger(__name__).warning(
                "CI_ENGINE_LLM_PROVIDER=%r but no API key found (env: %s)",
                forced, cfg.api_key_env or "n/a",
            )
        else:
            import logging
            logging.getLogger(__name__).warning(
                "CI_ENGINE_LLM_PROVIDER=%r is not a known provider. "
                "Known: %s", forced, ", ".join(_BY_NAME),
            )
        return None

    for cfg in _REGISTRY:
        if cfg.is_available():
            return cfg
    return None


def list_available_providers() -> list[ProviderConfig]:
    return [p for p in _REGISTRY if p.is_available()]


def provider_status() -> dict[str, bool]:
    return {p.name: p.is_available() for p in _REGISTRY}


def get_provider(name: str) -> Optional[ProviderConfig]:
    return _BY_NAME.get(name)
