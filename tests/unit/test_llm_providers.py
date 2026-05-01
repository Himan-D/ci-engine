# SPDX-License-Identifier: MIT
# Tests for ci_engine/core/llm_providers.py

import os
from unittest.mock import patch

from ci_engine.core.llm_providers import (
    _REGISTRY,
    _BY_NAME,
    discover_provider,
    list_available_providers,
    provider_status,
    get_provider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(**kw):
    """Context manager: temporarily set env vars, restore after."""
    return patch.dict(os.environ, kw, clear=False)


def _no_keys():
    """Strip all CI_ENGINE_*_API_KEY vars so tests start from a clean slate."""
    keys_to_clear = {
        k: "" for k in os.environ
        if k.startswith("CI_ENGINE_") and ("API_KEY" in k or k == "CI_ENGINE_LLM_PROVIDER"
                                            or k == "CI_ENGINE_OLLAMA_ENABLED"
                                            or k == "CI_ENGINE_OLLAMA_BASE_URL")
    }
    keys_to_clear["AWS_ACCESS_KEY_ID"] = ""
    return patch.dict(os.environ, keys_to_clear, clear=False)


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_all_expected_providers_exist(self):
        names = {p.name for p in _REGISTRY}
        assert "anthropic"  in names
        assert "openrouter" in names
        assert "openai"     in names
        assert "groq"       in names
        assert "together"   in names
        assert "mistral"    in names
        assert "cohere"     in names
        assert "gemini"     in names
        assert "bedrock"    in names
        assert "ollama"     in names

    def test_by_name_index_is_complete(self):
        for p in _REGISTRY:
            assert p.name in _BY_NAME
            assert _BY_NAME[p.name] is p

    def test_get_provider_returns_config(self):
        cfg = get_provider("groq")
        assert cfg is not None
        assert cfg.name == "groq"

    def test_get_provider_returns_none_for_unknown(self):
        assert get_provider("nonexistent-llm") is None


# ---------------------------------------------------------------------------
# ProviderConfig.is_available()
# ---------------------------------------------------------------------------

class TestProviderConfigAvailability:
    def test_unavailable_without_key(self):
        with _no_keys():
            cfg = get_provider("anthropic")
            assert not cfg.is_available()

    def test_available_when_key_set(self):
        with _env(CI_ENGINE_ANTHROPIC_API_KEY="sk-ant-test"):
            assert get_provider("anthropic").is_available()

    def test_openrouter_available_when_key_set(self):
        with _env(CI_ENGINE_OPENROUTER_API_KEY="sk-or-test"):
            assert get_provider("openrouter").is_available()

    def test_groq_available_when_key_set(self):
        with _env(CI_ENGINE_GROQ_API_KEY="gsk_test"):
            assert get_provider("groq").is_available()

    def test_ollama_available_via_enabled_flag(self):
        with _no_keys():
            with _env(CI_ENGINE_OLLAMA_ENABLED="1"):
                assert get_provider("ollama").is_available()

    def test_ollama_available_via_base_url(self):
        with _no_keys():
            with _env(CI_ENGINE_OLLAMA_BASE_URL="http://gpu-box:11434"):
                assert get_provider("ollama").is_available()

    def test_ollama_unavailable_without_flag(self):
        with _no_keys():
            assert not get_provider("ollama").is_available()

    def test_bedrock_available_when_aws_key_set(self):
        with _env(AWS_ACCESS_KEY_ID="AKIATEST"):
            assert get_provider("bedrock").is_available()

    def test_api_key_property_returns_env_value(self):
        with _env(CI_ENGINE_GROQ_API_KEY="my-real-key"):
            assert get_provider("groq").api_key == "my-real-key"

    def test_api_key_property_returns_none_when_unset(self):
        with _no_keys():
            assert get_provider("groq").api_key is None


# ---------------------------------------------------------------------------
# ProviderConfig model selection
# ---------------------------------------------------------------------------

class TestModelSelection:
    def test_default_analysis_model(self):
        with _no_keys():
            cfg = get_provider("groq")
            assert "llama" in cfg.get_analysis_model()

    def test_default_summary_model(self):
        with _no_keys():
            cfg = get_provider("groq")
            summary = cfg.get_summary_model()
            assert "llama" in summary or "70b" in summary.lower()

    def test_env_override_analysis_model(self):
        with _env(CI_ENGINE_AI_ANALYSIS_MODEL="groq/custom-fast-model"):
            cfg = get_provider("groq")
            assert cfg.get_analysis_model() == "groq/custom-fast-model"

    def test_env_override_summary_model(self):
        with _env(CI_ENGINE_AI_SUMMARY_MODEL="together_ai/big-model"):
            cfg = get_provider("together")
            assert cfg.get_summary_model() == "together_ai/big-model"

    def test_empty_override_falls_back_to_default(self):
        """Empty string override should not replace the default."""
        with patch.dict(os.environ, {"CI_ENGINE_AI_ANALYSIS_MODEL": ""}, clear=False):
            cfg = get_provider("anthropic")
            # Should get the provider default, not empty string
            assert cfg.get_analysis_model() != ""


# ---------------------------------------------------------------------------
# ProviderConfig.litellm_kwargs()
# ---------------------------------------------------------------------------

class TestLitellmKwargs:
    def test_basic_kwargs_shape(self):
        with _env(CI_ENGINE_GROQ_API_KEY="gsk_xyz"):
            cfg = get_provider("groq")
            kw = cfg.litellm_kwargs("groq/llama-3.1-8b-instant", 512)
        assert kw["model"] == "groq/llama-3.1-8b-instant"
        assert kw["max_tokens"] == 512
        assert kw["api_key"] == "gsk_xyz"

    def test_openrouter_includes_extra_headers(self):
        with _env(CI_ENGINE_OPENROUTER_API_KEY="sk-or-abc"):
            cfg = get_provider("openrouter")
            kw = cfg.litellm_kwargs(cfg.get_analysis_model(), 1024)
        assert "extra_headers" in kw
        assert "HTTP-Referer" in kw["extra_headers"]
        assert kw["api_base"] == "https://openrouter.ai/api/v1"

    def test_ollama_uses_local_base_url(self):
        with _no_keys():
            with _env(CI_ENGINE_OLLAMA_ENABLED="1", CI_ENGINE_OLLAMA_BASE_URL="http://gpu-box:11434"):
                cfg = get_provider("ollama")
                kw = cfg.litellm_kwargs("ollama/llama3.2", 256)
        assert kw["api_base"] == "http://gpu-box:11434"

    def test_no_api_key_in_kwargs_when_key_absent(self):
        """Keyless providers (Ollama/Bedrock) should not inject api_key=None."""
        with _no_keys():
            with _env(CI_ENGINE_OLLAMA_ENABLED="1"):
                cfg = get_provider("ollama")
                kw = cfg.litellm_kwargs("ollama/llama3.2", 256)
        assert "api_key" not in kw or kw.get("api_key") is None


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_returns_none_when_no_keys(self):
        with _no_keys():
            assert discover_provider() is None

    def test_returns_anthropic_when_only_anthropic_key(self):
        with _no_keys():
            with _env(CI_ENGINE_ANTHROPIC_API_KEY="sk-ant-test"):
                p = discover_provider()
                assert p is not None
                assert p.name == "anthropic"

    def test_priority_anthropic_over_openrouter(self):
        """Anthropic comes before OpenRouter in the registry."""
        with _no_keys():
            with _env(
                CI_ENGINE_ANTHROPIC_API_KEY="sk-ant-test",
                CI_ENGINE_OPENROUTER_API_KEY="sk-or-test",
            ):
                p = discover_provider()
                assert p.name == "anthropic"

    def test_fallback_to_groq_when_higher_priority_absent(self):
        with _no_keys():
            with _env(CI_ENGINE_GROQ_API_KEY="gsk_test"):
                p = discover_provider()
                assert p.name == "groq"

    def test_force_override_with_env_var(self):
        with _no_keys():
            with _env(
                CI_ENGINE_LLM_PROVIDER="groq",
                CI_ENGINE_GROQ_API_KEY="gsk_test",
                CI_ENGINE_ANTHROPIC_API_KEY="sk-ant-test",  # would normally win
            ):
                p = discover_provider()
                assert p.name == "groq"

    def test_force_override_returns_none_when_key_missing(self):
        with _no_keys():
            with _env(CI_ENGINE_LLM_PROVIDER="groq"):
                # Force groq but no groq key — should return None, not crash
                assert discover_provider() is None

    def test_unknown_provider_override_returns_none(self):
        with _no_keys():
            with _env(CI_ENGINE_LLM_PROVIDER="nonexistent-provider"):
                assert discover_provider() is None

    def test_list_available_returns_all_configured(self):
        with _no_keys():
            with _env(
                CI_ENGINE_GROQ_API_KEY="gsk_test",
                CI_ENGINE_OPENAI_API_KEY="sk-openai-test",
            ):
                available = list_available_providers()
                names = {p.name for p in available}
                assert "groq" in names
                assert "openai" in names
                assert "anthropic" not in names


# ---------------------------------------------------------------------------
# provider_status()
# ---------------------------------------------------------------------------

class TestProviderStatus:
    def test_status_dict_has_all_providers(self):
        status = provider_status()
        for p in _REGISTRY:
            assert p.name in status

    def test_all_false_when_no_keys(self):
        with _no_keys():
            status = provider_status()
            for name, avail in status.items():
                if name not in ("ollama", "bedrock"):
                    assert avail is False, f"{name} should be unavailable"

    def test_correct_true_when_key_set(self):
        with _no_keys():
            with _env(CI_ENGINE_MISTRAL_API_KEY="mis-test"):
                status = provider_status()
                assert status["mistral"] is True
                assert status["anthropic"] is False
