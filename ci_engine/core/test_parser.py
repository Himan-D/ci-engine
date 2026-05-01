# SPDX-License-Identifier: MIT
# CI Engine — Test result parser
#
# Supported formats:
#   • JUnit XML  (pytest, Maven, Gradle, Jest — Content-Type: application/xml)
#   • CTRF JSON  (Common Test Report Format  — Content-Type: application/json)
#
# Both parsers return a list of dicts with the canonical keys:
#   test_name, test_suite, status, duration_ms, failure_message, failure_type

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Optional


# ---------------------------------------------------------------------------
# JUnit XML parser (lenient — handles pytest, Maven, Gradle, Jest variants)
# ---------------------------------------------------------------------------

def parse_junit_xml(content: str) -> list[dict]:
    """Parse JUnit XML content into a list of test-result dicts."""
    results: list[dict] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return results

    # Root may be <testsuite> or <testsuites> (containing multiple <testsuite>)
    suites: list[ET.Element] = []
    if root.tag == "testsuites":
        suites = list(root.iter("testsuite"))
    elif root.tag == "testsuite":
        suites = [root]
    else:
        # Try iterating for embedded suites
        suites = list(root.iter("testsuite")) or [root]

    for suite in suites:
        suite_name = suite.get("name", "")
        for tc in suite.iter("testcase"):
            name = tc.get("name", "unnamed")
            classname = tc.get("classname", "")
            full_name = f"{classname}.{name}" if classname else name
            duration_ms: Optional[float] = None
            time_s = tc.get("time")
            if time_s:
                try:
                    duration_ms = float(time_s) * 1000
                except ValueError:
                    pass

            # Determine status
            failure = tc.find("failure")
            error = tc.find("error")
            skipped = tc.find("skipped")

            if failure is not None:
                status = "failed"
                failure_message = (failure.get("message") or failure.text or "")[:2000]
                failure_type = failure.get("type", "")
            elif error is not None:
                status = "errored"
                failure_message = (error.get("message") or error.text or "")[:2000]
                failure_type = error.get("type", "")
            elif skipped is not None:
                status = "skipped"
                failure_message = None
                failure_type = None
            else:
                status = "passed"
                failure_message = None
                failure_type = None

            results.append({
                "test_name": full_name,
                "test_suite": suite_name or classname or None,
                "status": status,
                "duration_ms": duration_ms,
                "failure_message": failure_message,
                "failure_type": failure_type or None,
            })

    return results


# ---------------------------------------------------------------------------
# CTRF JSON parser (https://ctrf.io/)
# ---------------------------------------------------------------------------

def parse_ctrf_json(content: str) -> list[dict]:
    """Parse CTRF JSON content into a list of test-result dicts."""
    results: list[dict] = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return results

    report = data.get("results", data)  # handle both {results:{...}} and bare object
    tests = report.get("tests", [])

    for t in tests:
        name = t.get("name", "unnamed")
        suite = t.get("suite") or t.get("filePath") or None
        raw_status = t.get("status", "").lower()
        # Normalise CTRF statuses → our canonical set
        status = {
            "passed": "passed", "pass": "passed",
            "failed": "failed", "fail": "failed",
            "skipped": "skipped", "skip": "skipped",
            "pending": "skipped",
            "other": "errored",
        }.get(raw_status, "passed")

        duration_ms: Optional[float] = None
        dur = t.get("duration")
        if dur is not None:
            try:
                duration_ms = float(dur)
            except (ValueError, TypeError):
                pass

        failure_message = t.get("message") or t.get("trace") or None
        if failure_message:
            failure_message = str(failure_message)[:2000]

        results.append({
            "test_name": name,
            "test_suite": suite,
            "status": status,
            "duration_ms": duration_ms,
            "failure_message": failure_message,
            "failure_type": None,
        })

    return results


# ---------------------------------------------------------------------------
# Auto-detect format
# ---------------------------------------------------------------------------

def parse_test_results(content: str, content_type: str = "") -> list[dict]:
    """Parse test results, auto-detecting format from content_type or content."""
    ct = (content_type or "").lower()
    if "xml" in ct:
        return parse_junit_xml(content)
    if "json" in ct:
        return parse_ctrf_json(content)
    # Sniff: XML starts with '<', JSON with '{'
    stripped = content.lstrip()
    if stripped.startswith("<"):
        return parse_junit_xml(content)
    if stripped.startswith("{") or stripped.startswith("["):
        return parse_ctrf_json(content)
    return parse_junit_xml(content)  # default
