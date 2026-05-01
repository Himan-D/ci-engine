# SPDX-License-Identifier: MIT
# Tests for ci_engine/core/ai_analyzer.py

import json
import os
import pytest
from unittest.mock import MagicMock, patch

from ci_engine.core.ai_analyzer import (
    LLMAnalyzer,
    AnalysisResult,
    BuildSummaryResult,
    _extract_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(**kw):
    return patch.dict(os.environ, kw, clear=False)


def _no_keys():
    keys_to_clear = {
        k: ""
        for k in os.environ
        if k.startswith("CI_ENGINE_") and ("API_KEY" in k or k in (
            "CI_ENGINE_LLM_PROVIDER",
            "CI_ENGINE_OLLAMA_ENABLED",
            "CI_ENGINE_OLLAMA_BASE_URL",
            "CI_ENGINE_AI_ANALYSIS_MODEL",
            "CI_ENGINE_AI_SUMMARY_MODEL",
        ))
    }
    return patch.dict(os.environ, keys_to_clear, clear=False)


def _make_litellm_response(content: str) -> MagicMock:
    """Build a fake litellm response object."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


_VALID_ANALYSIS_JSON = json.dumps({
    "root_cause": "The package 'pytest-missing' is not installed",
    "error_category": "dependency_missing",
    "explanation": "pip could not find pytest-missing in PyPI.",
    "fixed_command": "pip install pytest-missing && pytest tests/",
    "confidence": 0.92,
    "pipeline_suggestion": "Add a dedicated dependency install step before tests.",
})

_VALID_SUMMARY_JSON = json.dumps({
    "overall_health": "recovering",
    "summary": "Build failed on the test step due to a missing package. AI auto-fix was applied.",
    "what_failed": ["Test"],
    "what_was_fixed": ["Test"],
    "recommendations": ["Pin all test dependencies in requirements-dev.txt"],
})


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_plain_json(self):
        data = _extract_json('{"key": "value"}')
        assert data["key"] == "value"

    def test_json_with_surrounding_prose(self):
        text = "Here is the analysis:\n\n{\"root_cause\": \"missing dep\"}"
        data = _extract_json(text)
        assert data["root_cause"] == "missing dep"

    def test_markdown_fenced_json(self):
        text = "```json\n{\"error_category\": \"timeout\"}\n```"
        data = _extract_json(text)
        assert data["error_category"] == "timeout"

    def test_markdown_fenced_no_language_tag(self):
        text = "```\n{\"confidence\": 0.8}\n```"
        data = _extract_json(text)
        assert data["confidence"] == 0.8

    def test_nested_object(self):
        data = _extract_json('{"outer": {"inner": 42}}')
        assert data["outer"]["inner"] == 42

    def test_raises_on_no_json(self):
        with pytest.raises(ValueError, match="No valid JSON"):
            _extract_json("This is just plain text with no JSON at all.")

    def test_handles_extra_whitespace(self):
        data = _extract_json("   \n  {\"x\": 1}  \n  ")
        assert data["x"] == 1

    def test_handles_list_inside_object(self):
        data = _extract_json('{"items": [1, 2, 3]}')
        assert data["items"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# LLMAnalyzer — disabled state
# ---------------------------------------------------------------------------

class TestAnalyzerDisabled:
    def test_is_disabled_without_any_key(self):
        with _no_keys():
            a = LLMAnalyzer()
            assert not a.is_enabled()

    def test_analyze_returns_none_when_disabled(self):
        with _no_keys():
            a = LLMAnalyzer()
            result = a.analyze_job_failure(
                job_id=1, label="Test", command="pytest", exit_code=1, log_lines=[]
            )
            assert result is None

    def test_summary_returns_none_when_disabled(self):
        with _no_keys():
            a = LLMAnalyzer()
            result = a.generate_build_summary(
                build_id=1, branch="main", status="failed", jobs=[]
            )
            assert result is None

    def test_legacy_api_key_arg_enables_anthropic(self):
        with _no_keys():
            a = LLMAnalyzer(api_key="sk-ant-injected")
            assert a.is_enabled()
            assert a._primary.name == "anthropic"

    def test_provider_key_in_env_enables_analyzer(self):
        with _no_keys():
            with _env(CI_ENGINE_GROQ_API_KEY="gsk_test"):
                a = LLMAnalyzer()
                assert a.is_enabled()
                assert a._primary.name == "groq"


# ---------------------------------------------------------------------------
# LLMAnalyzer — analyze_job_failure
# ---------------------------------------------------------------------------

class TestAnalyzeJobFailure:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Each test in this class gets an enabled analyzer with Groq key."""
        with _no_keys():
            with _env(CI_ENGINE_GROQ_API_KEY="gsk_test"):
                self.analyzer = LLMAnalyzer()
        yield

    def test_returns_analysis_result(self):
        mock_resp = _make_litellm_response(_VALID_ANALYSIS_JSON)
        with patch("litellm.completion", return_value=mock_resp):
            result = self.analyzer.analyze_job_failure(
                job_id=42,
                label="Test",
                command="pytest tests/",
                exit_code=1,
                log_lines=["ERROR: No module named pytest_missing"],
            )
        assert isinstance(result, AnalysisResult)
        assert result.job_id == 42
        assert result.error_category == "dependency_missing"
        assert result.fixed_command == "pip install pytest-missing && pytest tests/"
        assert result.confidence == pytest.approx(0.92)
        assert result.provider == "groq"

    def test_passes_correct_model_to_litellm(self):
        mock_resp = _make_litellm_response(_VALID_ANALYSIS_JSON)
        with patch("litellm.completion", return_value=mock_resp) as mock_call:
            self.analyzer.analyze_job_failure(
                job_id=1, label="Test", command="pytest", exit_code=1, log_lines=[]
            )
        kw = mock_call.call_args.kwargs
        assert "model" in kw
        assert "llama" in kw["model"]   # Groq default model contains "llama"

    def test_model_env_override_is_respected(self):
        mock_resp = _make_litellm_response(_VALID_ANALYSIS_JSON)
        with _env(CI_ENGINE_AI_ANALYSIS_MODEL="groq/llama-3.3-70b-versatile"):
            with patch("litellm.completion", return_value=mock_resp) as mock_call:
                self.analyzer.analyze_job_failure(
                    job_id=1, label="Test", command="pytest", exit_code=1, log_lines=[]
                )
        kw = mock_call.call_args.kwargs
        assert kw["model"] == "groq/llama-3.3-70b-versatile"

    def test_log_lines_truncated_to_max(self):
        """LLM should only receive the last N lines, not the full list."""
        huge_logs = [f"line {i}" for i in range(500)]
        mock_resp = _make_litellm_response(_VALID_ANALYSIS_JSON)
        # Patch the module-level constant so only the last 10 lines are sent
        with patch("ci_engine.core.ai_analyzer._MAX_LOG_LINES", 10):
            with patch("litellm.completion", return_value=mock_resp) as mock_call:
                self.analyzer.analyze_job_failure(
                    job_id=1, label="Test", command="pytest",
                    exit_code=1, log_lines=huge_logs,
                )
        kw = mock_call.call_args.kwargs
        user_msg = kw["messages"][1]["content"]
        # The tail (lines 490-499) should be present
        assert "line 499" in user_msg
        # The head should be absent
        assert "line 0\n" not in user_msg
        assert "line 1\n" not in user_msg

    def test_pipeline_yaml_included_in_prompt(self):
        mock_resp = _make_litellm_response(_VALID_ANALYSIS_JSON)
        with patch("litellm.completion", return_value=mock_resp) as mock_call:
            self.analyzer.analyze_job_failure(
                job_id=1, label="Test", command="pytest",
                exit_code=1, log_lines=[],
                pipeline_yaml="steps:\n  - label: Test\n    command: pytest",
            )
        user_msg = mock_call.call_args.kwargs["messages"][1]["content"]
        assert "steps:" in user_msg

    def test_null_fixed_command_becomes_none(self):
        payload = dict(json.loads(_VALID_ANALYSIS_JSON))
        payload["fixed_command"] = None
        mock_resp = _make_litellm_response(json.dumps(payload))
        with patch("litellm.completion", return_value=mock_resp):
            result = self.analyzer.analyze_job_failure(
                job_id=1, label="T", command="x", exit_code=1, log_lines=[]
            )
        assert result.fixed_command is None

    def test_malformed_json_returns_none(self):
        mock_resp = _make_litellm_response("Sorry, I cannot analyze this.")
        with patch("litellm.completion", return_value=mock_resp):
            result = self.analyzer.analyze_job_failure(
                job_id=1, label="T", command="x", exit_code=1, log_lines=[]
            )
        assert result is None

    def test_markdown_fenced_json_is_parsed(self):
        fenced = f"```json\n{_VALID_ANALYSIS_JSON}\n```"
        mock_resp = _make_litellm_response(fenced)
        with patch("litellm.completion", return_value=mock_resp):
            result = self.analyzer.analyze_job_failure(
                job_id=1, label="T", command="x", exit_code=1, log_lines=[]
            )
        assert result is not None
        assert result.error_category == "dependency_missing"

    def test_litellm_exception_returns_none(self):
        with patch("litellm.completion", side_effect=Exception("API timeout")):
            result = self.analyzer.analyze_job_failure(
                job_id=1, label="T", command="x", exit_code=1, log_lines=[]
            )
        assert result is None

    def test_system_message_is_passed(self):
        mock_resp = _make_litellm_response(_VALID_ANALYSIS_JSON)
        with patch("litellm.completion", return_value=mock_resp) as mock_call:
            self.analyzer.analyze_job_failure(
                job_id=1, label="T", command="x", exit_code=1, log_lines=[]
            )
        messages = mock_call.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "CI/CD" in messages[0]["content"]
        assert messages[1]["role"] == "user"


# ---------------------------------------------------------------------------
# LLMAnalyzer — generate_build_summary
# ---------------------------------------------------------------------------

class TestGenerateBuildSummary:
    @pytest.fixture(autouse=True)
    def setup(self):
        with _no_keys():
            with _env(CI_ENGINE_GROQ_API_KEY="gsk_test"):
                self.analyzer = LLMAnalyzer()
        yield

    def test_returns_summary_result(self):
        mock_resp = _make_litellm_response(_VALID_SUMMARY_JSON)
        with patch("litellm.completion", return_value=mock_resp):
            result = self.analyzer.generate_build_summary(
                build_id=99,
                branch="main",
                status="failed",
                jobs=[{"label": "Test", "status": "failed", "command": "pytest"}],
            )
        assert isinstance(result, BuildSummaryResult)
        assert result.build_id == 99
        assert result.overall_health == "recovering"
        assert "Test" in result.what_failed
        assert result.provider == "groq"

    def test_uses_summary_model_not_analysis_model(self):
        """generate_build_summary should call get_summary_model(), not get_analysis_model()."""
        mock_resp = _make_litellm_response(_VALID_SUMMARY_JSON)
        analysis_model = self.analyzer._primary.get_analysis_model()
        summary_model = self.analyzer._primary.get_summary_model()

        with patch("litellm.completion", return_value=mock_resp) as mock_call:
            self.analyzer.generate_build_summary(
                build_id=1, branch="main", status="passed", jobs=[]
            )
        used_model = mock_call.call_args.kwargs["model"]
        assert used_model == summary_model
        # If models differ, make sure it didn't use the analysis model
        if analysis_model != summary_model:
            assert used_model != analysis_model

    def test_jobs_table_includes_auto_fix_tag(self):
        mock_resp = _make_litellm_response(_VALID_SUMMARY_JSON)
        with patch("litellm.completion", return_value=mock_resp) as mock_call:
            self.analyzer.generate_build_summary(
                build_id=1, branch="main", status="passed",
                jobs=[
                    {"label": "Test", "status": "failed", "command": "pytest", "ai_fix_applied": True},
                    {"label": "Build", "status": "passed", "command": "make", "ai_fix_applied": False},
                ],
            )
        user_msg = mock_call.call_args.kwargs["messages"][1]["content"]
        assert "[auto-fixed]" in user_msg
        assert "Test" in user_msg
        assert "Build" in user_msg

    def test_empty_lists_when_none_in_response(self):
        payload = {
            "overall_health": "healthy",
            "summary": "All passed.",
            "what_failed": None,
            "what_was_fixed": None,
            "recommendations": None,
        }
        mock_resp = _make_litellm_response(json.dumps(payload))
        with patch("litellm.completion", return_value=mock_resp):
            result = self.analyzer.generate_build_summary(
                build_id=1, branch="main", status="passed", jobs=[]
            )
        assert result.what_failed == []
        assert result.what_was_fixed == []
        assert result.recommendations == []


# ---------------------------------------------------------------------------
# LLMAnalyzer — fallback chain
# ---------------------------------------------------------------------------

class TestFallbackChain:
    def test_falls_back_to_second_provider_on_error(self):
        with _no_keys():
            with _env(
                CI_ENGINE_ANTHROPIC_API_KEY="sk-ant-test",
                CI_ENGINE_GROQ_API_KEY="gsk_test",
            ):
                analyzer = LLMAnalyzer()

        # Primary (Anthropic) fails; secondary (Groq) succeeds
        mock_resp = _make_litellm_response(_VALID_ANALYSIS_JSON)
        call_count = [0]

        def side_effect(**kw):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Anthropic rate limited")
            return mock_resp

        with patch("litellm.completion", side_effect=side_effect):
            result = analyzer.analyze_job_failure(
                job_id=1, label="T", command="x", exit_code=1, log_lines=[]
            )

        assert result is not None
        assert call_count[0] == 2

    def test_returns_none_when_all_providers_fail(self):
        with _no_keys():
            with _env(CI_ENGINE_GROQ_API_KEY="gsk_test"):
                analyzer = LLMAnalyzer()

        with patch("litellm.completion", side_effect=Exception("network error")):
            result = analyzer.analyze_job_failure(
                job_id=1, label="T", command="x", exit_code=1, log_lines=[]
            )
        assert result is None

    def test_primary_provider_is_tried_first(self):
        with _no_keys():
            with _env(CI_ENGINE_ANTHROPIC_API_KEY="sk-ant-test"):
                analyzer = LLMAnalyzer()
        assert analyzer._primary.name == "anthropic"

    def test_fallbacks_list_excludes_primary(self):
        with _no_keys():
            with _env(
                CI_ENGINE_ANTHROPIC_API_KEY="sk-ant-test",
                CI_ENGINE_GROQ_API_KEY="gsk_test",
            ):
                analyzer = LLMAnalyzer()
        assert analyzer._primary not in analyzer._fallbacks
        fallback_names = {p.name for p in analyzer._fallbacks}
        assert "groq" in fallback_names
        assert "anthropic" not in fallback_names


# ---------------------------------------------------------------------------
# LLMAnalyzer — litellm not installed
# ---------------------------------------------------------------------------

class TestLitellmNotInstalled:
    def test_returns_none_gracefully_when_litellm_missing(self):
        with _no_keys():
            with _env(CI_ENGINE_GROQ_API_KEY="gsk_test"):
                analyzer = LLMAnalyzer()

        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "litellm":
                raise ImportError("litellm not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = analyzer.analyze_job_failure(
                job_id=1, label="T", command="x", exit_code=1, log_lines=[]
            )
        assert result is None
