# SPDX-License-Identifier: MIT
# CI Engine - Git operations for agents

import os
import subprocess
from typing import Optional


class GitCloneError(Exception):
    """Raised when git clone fails."""

    pass


def clone_repository(
    repo_url: str,
    target_dir: str,
    ref: str = "main",
    depth: Optional[int] = None,
    ssh_key_path: Optional[str] = None,
) -> bool:
    """Clone a git repository to target directory.

    Args:
        repo_url: Git repository URL (HTTPS or SSH)
        target_dir: Directory to clone into
        ref: Git ref to checkout (branch, tag, commit)
        depth: Clone depth (for shallow clone)
        ssh_key_path: Path to SSH key for private repos

    Returns:
        True if successful

    Raises:
        GitCloneError: If clone fails
    """
    os.makedirs(target_dir, exist_ok=True)

    cmd = ["git", "clone"]

    if depth:
        cmd.extend(["--depth", str(depth)])

    cmd.extend(["--branch", ref, "--single-branch", repo_url, target_dir])

    env = os.environ.copy()
    if ssh_key_path and os.path.exists(ssh_key_path):
        env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key_path} -o StrictHostKeyChecking=no"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )

        if result.returncode != 0:
            raise GitCloneError(f"Clone failed: {result.stderr}")

        return True

    except subprocess.TimeoutExpired:
        raise GitCloneError("Clone timed out after 5 minutes")
    except FileNotFoundError:
        raise GitCloneError("git command not found - ensure git is installed")


def checkout_ref(target_dir: str, ref: str) -> bool:
    """Checkout a specific git ref in existing repo.

    Args:
        target_dir: Directory containing git repository
        ref: Git ref to checkout

    Returns:
        True if successful
    """
    try:
        result = subprocess.run(
            ["git", "fetch", "--all"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )

        result = subprocess.run(
            ["git", "checkout", ref],
            cwd=target_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )

        return result.returncode == 0

    except Exception:
        return False


def get_current_ref(target_dir: str) -> Optional[str]:
    """Get current git ref in directory.

    Args:
        target_dir: Directory containing git repository

    Returns:
        Current branch/tag or None
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            return result.stdout.strip()

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            return result.stdout.strip()[:8]

    except Exception:
        pass

    return None


def get_repository_info(repo_url: str) -> dict[str, str]:
    """Extract information from repository URL.

    Args:
        repo_url: Git repository URL

    Returns:
        Dict with 'owner', 'repo', 'provider' keys
    """
    info = {"owner": "", "repo": "", "provider": "unknown"}

    if not repo_url:
        return info

    if repo_url.startswith("git@"):
        parts = repo_url.split(":")
        if len(parts) >= 2:
            host_and_path = parts[1]
            if "/" in host_and_path:
                host, path = host_and_path.split("/", 1)
                info["provider"] = host.replace("github.com", "github").replace(
                    "gitlab.com", "gitlab"
                )
                info["owner"] = path.rsplit(".git", 1)[0] if ".git" in path else path

    elif "github.com" in repo_url:
        parts = repo_url.split("/")
        if len(parts) >= 2:
            info["provider"] = "github"
            info["owner"] = parts[-2]
            info["repo"] = parts[-1].replace(".git", "")

    elif "gitlab.com" in repo_url:
        parts = repo_url.split("/")
        if len(parts) >= 2:
            info["provider"] = "gitlab"
            info["owner"] = parts[-2]
            info["repo"] = parts[-1].replace(".git", "")

    return info
