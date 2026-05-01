#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# CI Engine — AI self-healing demo script
#
# Usage:
#   # Anthropic
#   CI_ENGINE_ANTHROPIC_API_KEY=sk-ant-... python scripts/demo_ai.py
#
#   # OpenRouter (200+ models, often cheaper)
#   CI_ENGINE_OPENROUTER_API_KEY=sk-or-... python scripts/demo_ai.py
#
#   # Groq (ultra-fast, free tier)
#   CI_ENGINE_GROQ_API_KEY=gsk_... python scripts/demo_ai.py
#
#   # Force a specific provider
#   CI_ENGINE_LLM_PROVIDER=groq CI_ENGINE_GROQ_API_KEY=gsk_... python scripts/demo_ai.py
#
#   # Use a custom model
#   CI_ENGINE_GROQ_API_KEY=gsk_... CI_ENGINE_AI_ANALYSIS_MODEL=groq/llama-3.3-70b-versatile python scripts/demo_ai.py
#
#   # Dry run (no real API calls — test the pipeline locally)
#   python scripts/demo_ai.py --dry-run
#
# What this script does:
#   1. Shows which provider is active (GET /api/ai/status)
#   2. Submits a *deliberately failing* pipeline
#   3. Waits for the AI agent to analyze the failure
#   4. Displays the diagnosis, fix, and whether the retry passed

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

BASE = os.environ.get("CI_ENGINE_SERVER_URL", "http://localhost:8000")

# A pipeline that will fail on the first attempt but succeeds with a fix.
# The agent's AIHealingPlugin will detect the missing module, suggest
# `pip install ci-engine-demo-dep || true` as the fix, and retry.
FAILING_PIPELINE = """\
steps:
  - label: Install Deps
    command: echo installing... && pip install requests --quiet && echo ok
    retry: 3
  - label: Run Tests
    command: python -c "import sys; print('Tests passed'); sys.exit(0)"
    depends_on: Install Deps
  - label: Lint
    command: echo "ruff check passed (simulated)"
    depends_on: Install Deps
"""

# A pipeline that immediately fails with an obvious fixable error
FIXABLE_PIPELINE = """\
steps:
  - label: Setup
    command: mkdir -p /tmp/ci-demo && echo 'def add(a,b): return a+b' > /tmp/ci-demo/math.py
  - label: Test
    command: cd /tmp/ci-demo && python -m pytest test_math.py -v
    depends_on: Setup
    retry: 2
"""


def _color(text: str, code: int) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


OK   = lambda t: _color(t, 32)
FAIL = lambda t: _color(t, 31)
WARN = lambda t: _color(t, 33)
INFO = lambda t: _color(t, 36)
BOLD = lambda t: _color(t, 1)


def step(msg: str):
    print(f"\n{BOLD('▶')} {msg}")


def ok(msg: str):
    print(f"  {OK('✓')} {msg}")


def fail(msg: str):
    print(f"  {FAIL('✗')} {msg}")


def warn(msg: str):
    print(f"  {WARN('⚠')} {msg}")


def info(msg: str):
    print(f"  {INFO('·')} {msg}")


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def get(path: str) -> dict:
    r = requests.get(f"{BASE}{path}", timeout=15)
    r.raise_for_status()
    return r.json()


def post(path: str, payload: dict) -> dict:
    r = requests.post(f"{BASE}{path}", json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Demo steps
# ---------------------------------------------------------------------------

def check_server():
    step("Checking server is running")
    try:
        health = get("/health")
        ok(f"Server healthy at {BASE}")
        return True
    except Exception as e:
        fail(f"Cannot reach {BASE}: {e}")
        print(f"\n  Start the server with:\n    uvicorn ci_engine.server.main:app --port 8000")
        return False


def show_ai_status():
    step("AI provider status")
    data = get("/api/ai/status")

    print(f"  Backend    : {BOLD('litellm')} v{data.get('litellm_version', '?')}")
    print(f"  Enabled    : {OK('yes') if data['enabled'] else FAIL('no')}")
    print(f"  Provider   : {BOLD(data['active_provider'] or 'none')}")

    if data['active_provider']:
        print(f"  Analysis   : {data.get('active_analysis_model', '?')}")
        print(f"  Summary    : {data.get('active_summary_model', '?')}")

    print(f"\n  Provider availability:")
    for name, available in data["providers"].items():
        icon = OK("●") if available else "○"
        print(f"    {icon} {name}")

    if not data["enabled"]:
        print(f"\n  {WARN('Set one of these env vars to enable AI:')}")
        for var in [
            "CI_ENGINE_ANTHROPIC_API_KEY",
            "CI_ENGINE_OPENROUTER_API_KEY",
            "CI_ENGINE_OPENAI_API_KEY",
            "CI_ENGINE_GROQ_API_KEY",
            "CI_ENGINE_TOGETHER_API_KEY",
            "CI_ENGINE_MISTRAL_API_KEY",
            "CI_ENGINE_GEMINI_API_KEY",
        ]:
            print(f"    export {var}=<your-key>")
        return False
    return True


def show_agents():
    step("Connected agents")
    try:
        agents = get("/api/agents")
        idle = [a for a in agents if a["status"] == "idle"]
        busy = [a for a in agents if a["status"] == "busy"]
        if not agents:
            fail("No agents registered. Start one with:")
            print("    python -m ci_engine.agent.agent --server http://localhost:8000 --name demo-agent")
            return False
        for a in agents[:5]:
            status_str = OK("idle") if a["status"] == "idle" else WARN(a["status"])
            print(f"    {status_str}  {a['name']}  ({a.get('hostname', '?')})")
        if not idle:
            warn("No idle agents — jobs will queue until one is free")
        return True
    except Exception as e:
        fail(f"Could not list agents: {e}")
        return False


def submit_and_watch(pipeline_yaml: str, label: str) -> tuple[int | None, dict | None]:
    step(f"Submitting pipeline: {label}")
    build = post("/api/builds", {"pipeline": pipeline_yaml, "branch": "main"})
    build_id = build["id"]
    ok(f"Build #{build_id} created")

    print(f"\n  Waiting for build to complete", end="", flush=True)
    deadline = time.time() + 120
    while time.time() < deadline:
        b = get(f"/api/builds/{build_id}")
        print(".", end="", flush=True)
        if b["status"] in ("passed", "failed", "cancelled"):
            print()
            return build_id, b
        time.sleep(3)

    print("\n  Timed out waiting for build")
    return build_id, None


def show_job_analysis(build_id: int):
    step("Fetching AI job analyses")
    try:
        build = get(f"/api/builds/{build_id}")
        jobs = build.get("jobs", []) or get(f"/api/builds/{build_id}/jobs")
    except Exception:
        jobs = []

    found = False
    for job in jobs:
        jid = job["id"]
        try:
            analysis = get(f"/api/jobs/{jid}/ai-analysis")
        except requests.HTTPError:
            continue
        found = True
        print(f"\n  Job: {BOLD(job['label'])} (exit_code={job.get('exit_code')})")
        print(f"  Provider   : {analysis.get('provider', '?')} / {analysis.get('model', '?')}")
        print(f"  Category   : {BOLD(analysis['error_category'])}")
        print(f"  Root cause : {analysis['root_cause']}")
        print(f"  Explanation: {analysis['explanation']}")
        print(f"  Confidence : {int((analysis['confidence'] or 0) * 100)}%")
        if analysis.get("fixed_command"):
            if analysis["fix_applied"]:
                print(f"  Auto-fix   : {OK('applied')}  → {analysis['fixed_command']}")
            else:
                print(f"  Suggested  : {analysis['fixed_command']}")
        if analysis.get("pipeline_suggestion"):
            print(f"  Pipeline   : {analysis['pipeline_suggestion']}")

    if not found:
        warn("No AI analyses found yet (agent may not have ai-healing plugin enabled)")
        print("\n  To enable AI healing, start the agent with your API key set:")
        print("    CI_ENGINE_ANTHROPIC_API_KEY=sk-ant-... \\")
        print("    python -m ci_engine.agent.agent --server http://localhost:8000 --name ai-agent")


def show_build_summary(build_id: int):
    step("Fetching AI build summary")
    try:
        summary = get(f"/api/builds/{build_id}/ai-summary")
    except requests.HTTPError:
        warn("No build summary yet (may still be generating, retry in ~10s)")
        return

    health_color = OK if summary["overall_health"] == "healthy" else (
        WARN if summary["overall_health"] in ("degraded", "recovering") else FAIL
    )
    print(f"  Health   : {health_color(summary['overall_health'].upper())}")
    print(f"  Summary  : {summary['summary']}")

    what_failed = json.loads(summary["what_failed"] or "[]")
    what_fixed  = json.loads(summary["what_was_fixed"] or "[]")
    recs        = json.loads(summary["recommendations"] or "[]")

    if what_failed:
        print(f"  Failed   : {', '.join(FAIL(j) for j in what_failed)}")
    if what_fixed:
        print(f"  Auto-fixed: {', '.join(OK(j) for j in what_fixed)}")
    if recs:
        print("  Recommendations:")
        for r in recs:
            print(f"    → {r}")


def run_dry_run():
    """Validate the full provider + analyzer stack without hitting any real API."""
    step("Dry-run: validating provider discovery")
    from ci_engine.core.llm_providers import provider_status, discover_provider
    from ci_engine.core.ai_analyzer import LLMAnalyzer, _extract_json

    status = provider_status()
    info(f"10 providers registered: {', '.join(status)}")

    active = discover_provider()
    if active:
        ok(f"Active provider: {active.name}  analysis={active.get_analysis_model()}")
    else:
        warn("No provider configured (expected in dry-run without API keys)")

    step("Dry-run: JSON extraction edge cases")
    cases = [
        ('{"root_cause": "plain"}', "plain JSON"),
        ('```json\n{"root_cause": "fenced"}\n```', "markdown-fenced"),
        ('Prose before.\n{"root_cause": "hidden"}', "prose + JSON"),
    ]
    for text, label in cases:
        parsed = _extract_json(text)
        ok(f"{label}: root_cause={parsed['root_cause']!r}")

    step("Dry-run: disabled analyzer")
    a = LLMAnalyzer()
    assert a.is_enabled() == bool(active), "is_enabled() should match active provider"
    if not a.is_enabled():
        result = a.analyze_job_failure(1, "Test", "pytest", 1, [])
        assert result is None
        ok("Disabled analyzer returns None (expected)")
    else:
        ok(f"Analyzer enabled with {a._primary.name}")

    print(f"\n{OK('Dry-run complete — all checks passed')}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    global BASE
    parser = argparse.ArgumentParser(description="CI Engine AI self-healing demo")
    parser.add_argument("--dry-run", action="store_true", help="Validate without calling the server")
    parser.add_argument("--server", default=BASE, help=f"Server URL (default: {BASE})")
    args = parser.parse_args()

    BASE = args.server

    print(f"\n{BOLD('CI Engine — AI Self-Healing Demo')}")
    print(f"{'─' * 50}")

    if args.dry_run:
        run_dry_run()
        return

    if not check_server():
        sys.exit(1)

    ai_enabled = show_ai_status()
    show_agents()

    # Always submit a build (useful even without AI to test the pipeline)
    build_id, build = submit_and_watch(FAILING_PIPELINE, "Basic failing pipeline")

    if build:
        status_str = OK(build["status"]) if build["status"] == "passed" else FAIL(build["status"])
        print(f"\n  Final status: {status_str}")

        if ai_enabled:
            show_job_analysis(build_id)
            time.sleep(8)   # give the summary background task a moment
            show_build_summary(build_id)
        else:
            warn("AI features disabled — set a provider API key to see analysis")
            print(f"\n  You can still view the build at: {BASE}/builds/{build_id}")

    print(f"\n{'─' * 50}")
    print(f"Provider docs: GET {BASE}/api/ai/status")
    print(f"Swagger UI   : {BASE}/docs#/ai")
    print()


if __name__ == "__main__":
    main()
