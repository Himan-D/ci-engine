# SPDX-License-Identifier: MIT
# CI Engine — Outbound GitHub / GitLab commit status reporter
#
# Sends build status back to GitHub/GitLab so PR authors see CI results
# directly on their pull requests.
#
# Configuration (env vars):
#   GITHUB_TOKEN              — personal access token (fallback)
#   GITHUB_APP_ID             — GitHub App ID (preferred)
#   GITHUB_APP_PRIVATE_KEY    — PEM string of the App private key
#   GITHUB_APP_INSTALLATION_ID— Installation ID for the target org/repo
#   GITLAB_TOKEN              — GitLab personal access token
#   CI_ENGINE_PUBLIC_URL      — base URL shown in the "Details" link on PR checks
#                               (e.g. https://ci.example.com)

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_PUBLIC_URL = os.environ.get("CI_ENGINE_PUBLIC_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# GitHub App JWT + installation token
# ---------------------------------------------------------------------------

def _get_github_app_token() -> Optional[str]:
    """Generate a GitHub App installation token using RS256 JWT."""
    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")

    if not (app_id and private_key and installation_id):
        return None

    try:
        import jwt  # PyJWT[crypto] — already in pyproject.toml
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}
        jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

        resp = httpx.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("token")
    except Exception as exc:
        logger.debug("GitHub App token generation failed: %s", exc)
        return None


def _get_github_token() -> Optional[str]:
    """Return GitHub token: try App installation token first, then PAT."""
    return _get_github_app_token() or os.environ.get("GITHUB_TOKEN") or None


# ---------------------------------------------------------------------------
# Status reporter
# ---------------------------------------------------------------------------

class GitStatusReporter:
    """Reports build/job status back to GitHub or GitLab.

    All methods are no-ops when the relevant token is not configured.
    All HTTP errors are caught and logged — never propagated to the caller.
    """

    # GitHub status states
    GH_PENDING = "pending"
    GH_SUCCESS = "success"
    GH_FAILURE = "failure"
    GH_ERROR = "error"

    def report_build_started(
        self,
        build_id: int,
        head_sha: Optional[str],
        external_repo: Optional[str],
    ) -> None:
        """POST 'pending' status when a build starts."""
        if not head_sha or not external_repo:
            return
        self._github_status(
            repo=external_repo,
            sha=head_sha,
            state=self.GH_PENDING,
            description="CI Engine build started",
            context="ci-engine/build",
            target_url=f"{_PUBLIC_URL}/builds/{build_id}",
        )

    def report_build_completed(
        self,
        build_id: int,
        head_sha: Optional[str],
        external_repo: Optional[str],
        passed: bool,
    ) -> None:
        """POST success/failure status when a build finishes."""
        if not head_sha or not external_repo:
            return
        state = self.GH_SUCCESS if passed else self.GH_FAILURE
        desc = "Build passed" if passed else "Build failed"
        self._github_status(
            repo=external_repo,
            sha=head_sha,
            state=state,
            description=desc,
            context="ci-engine/build",
            target_url=f"{_PUBLIC_URL}/builds/{build_id}",
        )
        # Also post to GitLab if token available
        self._gitlab_status(
            repo=external_repo,
            sha=head_sha,
            state="success" if passed else "failed",
            name="ci-engine/build",
            target_url=f"{_PUBLIC_URL}/builds/{build_id}",
        )

    def report_job_status(
        self,
        job_id: int,
        job_label: str,
        build_id: int,
        head_sha: Optional[str],
        external_repo: Optional[str],
        state: str,  # pending / success / failure
    ) -> None:
        """Report individual job status as a GitHub Check Run context."""
        if not head_sha or not external_repo:
            return
        self._github_status(
            repo=external_repo,
            sha=head_sha,
            state=state,
            description=f"Job: {job_label}",
            context=f"ci-engine/{job_label.lower().replace(' ', '-')}",
            target_url=f"{_PUBLIC_URL}/builds/{build_id}",
        )

    # ------------------------------------------------------------------
    # GitHub
    # ------------------------------------------------------------------

    def _github_status(
        self,
        repo: str,
        sha: str,
        state: str,
        description: str,
        context: str,
        target_url: str,
    ) -> None:
        token = _get_github_token()
        if not token:
            return
        url = f"https://api.github.com/repos/{repo}/statuses/{sha}"
        payload = {
            "state": state,
            "target_url": target_url,
            "description": description[:140],  # GitHub cap
            "context": context,
        }
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10,
            )
            if resp.status_code not in (200, 201):
                logger.debug(
                    "GitHub status POST returned %s for %s@%s: %s",
                    resp.status_code, repo, sha[:8], resp.text[:200],
                )
        except Exception as exc:
            logger.debug("GitHub status failed: %s", exc)

    def post_pr_comment(
        self,
        external_repo: Optional[str],
        pr_number: Optional[int],
        build_id: int,
        passed: bool,
        failed_jobs: Optional[list[str]] = None,
    ) -> None:
        """Post a summary comment on a GitHub PR when a build completes.

        Only fires when ``GITHUB_TOKEN`` / GitHub App is configured and
        ``pr_number`` is non-null on the build.
        """
        if not external_repo or not pr_number:
            return
        token = _get_github_token()
        if not token:
            return

        status_emoji = "✅" if passed else "❌"
        status_text = "passed" if passed else "failed"
        body_lines = [
            f"{status_emoji} **CI Engine build #{build_id} {status_text}**",
            "",
            f"[View build details]({_PUBLIC_URL}/builds/{build_id})",
        ]
        if not passed and failed_jobs:
            body_lines += ["", "**Failed jobs:**"]
            for j in failed_jobs[:10]:
                body_lines.append(f"- {j}")
            if len(failed_jobs) > 10:
                body_lines.append(f"- … and {len(failed_jobs) - 10} more")

        body = "\n".join(body_lines)
        url = f"https://api.github.com/repos/{external_repo}/issues/{pr_number}/comments"
        try:
            resp = httpx.post(
                url,
                json={"body": body},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10,
            )
            if resp.status_code not in (200, 201):
                logger.debug(
                    "GitHub PR comment returned %s for %s#%s",
                    resp.status_code, external_repo, pr_number,
                )
        except Exception as exc:
            logger.debug("GitHub PR comment failed: %s", exc)

    # ------------------------------------------------------------------
    # GitLab
    # ------------------------------------------------------------------

    def _gitlab_status(
        self,
        repo: str,
        sha: str,
        state: str,
        name: str,
        target_url: str,
    ) -> None:
        token = os.environ.get("GITLAB_TOKEN")
        if not token:
            return
        gitlab_url = os.environ.get("GITLAB_URL", "https://gitlab.com")
        # GitLab project path encoded for URL
        project = repo.replace("/", "%2F")
        url = f"{gitlab_url}/api/v4/projects/{project}/statuses/{sha}"
        payload = {
            "state": state,
            "name": name,
            "target_url": target_url,
        }
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={"PRIVATE-TOKEN": token},
                timeout=10,
            )
            if resp.status_code not in (200, 201):
                logger.debug(
                    "GitLab status POST returned %s for %s@%s",
                    resp.status_code, repo, sha[:8],
                )
        except Exception as exc:
            logger.debug("GitLab status failed: %s", exc)


# Module-level singleton
_reporter = GitStatusReporter()


def get_reporter() -> GitStatusReporter:
    return _reporter
