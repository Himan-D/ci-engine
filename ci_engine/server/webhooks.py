# SPDX-License-Identifier: MIT
# CI Engine - Webhook Integration

import hashlib
import hmac
from typing import Optional
from datetime import datetime

from pydantic import BaseModel


class WebhookEvent(BaseModel):
    """Generic webhook event."""

    event_type: str
    payload: dict


class GitHubPushEvent(BaseModel):
    """GitHub push event."""

    ref: str
    before: str
    after: str
    repository: dict
    pusher: dict
    commits: list[dict]


class GitHubPREvent(BaseModel):
    """GitHub pull request event."""

    action: str
    number: int
    pull_request: dict
    repository: dict


class WebhookService:
    """Service for handling webhook events."""

    @staticmethod
    def verify_github_signature(payload: bytes, secret: str, signature: str) -> bool:
        """Verify GitHub webhook signature."""
        if not signature:
            return False
        expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def verify_gitlab_token(token: str, secret: str) -> bool:
        """Verify GitLab webhook token."""
        if not token or not secret:
            return False
        return hmac.compare_digest(token, secret)

    @staticmethod
    def parse_github_event(payload: dict, event_type: str) -> Optional[WebhookEvent]:
        """Parse GitHub webhook payload."""
        if event_type == "push":
            return WebhookEvent(
                event_type="push",
                payload=payload,
            )
        elif event_type == "pull_request":
            return WebhookEvent(
                event_type="pull_request",
                payload=payload,
            )
        elif event_type == "pull_request_review":
            return WebhookEvent(
                event_type="pull_request_review",
                payload=payload,
            )
        elif event_type == "pull_request_review_comment":
            return WebhookEvent(
                event_type="pull_request_review_comment",
                payload=payload,
            )
        elif event_type == "create":
            # Branch or tag created
            ref_type = payload.get("ref_type")
            if ref_type == "branch":
                return WebhookEvent(
                    event_type="branch_created",
                    payload=payload,
                )
            elif ref_type == "tag":
                return WebhookEvent(
                    event_type="tag_created",
                    payload=payload,
                )
        elif event_type == "delete":
            # Branch or tag deleted
            ref_type = payload.get("ref_type")
            if ref_type == "branch":
                return WebhookEvent(
                    event_type="branch_deleted",
                    payload=payload,
                )
            elif ref_type == "tag":
                return WebhookEvent(
                    event_type="tag_deleted",
                    payload=payload,
                )
        elif event_type == "release":
            return WebhookEvent(
                event_type="release",
                payload=payload,
            )
        elif event_type == "workflow_run":
            return WebhookEvent(
                event_type="workflow_run",
                payload=payload,
            )
        elif event_type == "ping":
            return WebhookEvent(
                event_type="ping",
                payload=payload,
            )
        return None

    @staticmethod
    def parse_gitlab_event(payload: dict, event_name: str) -> Optional[WebhookEvent]:
        """Parse GitLab webhook payload."""
        if event_name == "push hook":
            return WebhookEvent(
                event_type="push",
                payload=payload,
            )
        elif event_name in ("merge_request_hook", "merge request hook"):
            return WebhookEvent(
                event_type="merge_request",
                payload=payload,
            )
        elif event_name == "tag push hook":
            return WebhookEvent(
                event_type="tag",
                payload=payload,
            )
        elif event_name == "note hook":
            return WebhookEvent(
                event_type="note",
                payload=payload,
            )
        elif event_name == "pipeline hook":
            return WebhookEvent(
                event_type="pipeline",
                payload=payload,
            )
        elif event_name == "build hook":
            return WebhookEvent(
                event_type="build",
                payload=payload,
            )
        elif event_name == "deployment hook":
            return WebhookEvent(
                event_type="deployment",
                payload=payload,
            )
        elif event_name == "release hook":
            return WebhookEvent(
                event_type="release",
                payload=payload,
            )
        return None

    @staticmethod
    def extract_build_info(event: WebhookEvent) -> Optional[dict]:
        """Extract build information from webhook event."""
        if event.event_type == "push":
            payload = event.payload
            ref = payload.get("ref", "")

            # Only trigger on pushes to main/master branches
            if ref not in ("refs/heads/main", "refs/heads/master"):
                return None

            return {
                "branch": ref.replace("refs/heads/", ""),
                "commit": payload.get("after"),
                "repository": payload.get("repository", {}).get("full_name")
                or payload.get("project", {}).get("path_with_namespace"),
                "pusher": payload.get("pusher", {}).get("name") or payload.get("user_username"),
            }

        elif event.event_type in ("pull_request", "merge_request"):
            payload = event.payload

            if event.event_type == "pull_request":
                action = payload.get("action")
                if action not in ("opened", "synchronize", "reopened"):
                    return None
                pr = payload.get("pull_request", {})
                return {
                    "branch": pr.get("head", {}).get("ref"),
                    "commit": pr.get("head", {}).get("sha"),
                    "repository": payload.get("repository", {}).get("full_name"),
                    "pr_number": payload.get("number"),
                    "is_pr": True,
                }
            else:
                # GitLab merge request
                attrs = payload.get("object_attributes", {})
                action = attrs.get("action")
                if action not in ("open", "update", "reopen"):
                    return None
                return {
                    "branch": attrs.get("source_branch"),
                    "commit": attrs.get("last_commit", {}).get("id"),
                    "repository": payload.get("project", {}).get("path_with_namespace"),
                    "mr_number": attrs.get("iid"),
                    "is_mr": True,
                }

        elif event.event_type == "tag":
            payload = event.payload
            ref = payload.get("ref", "")
            return {
                "branch": ref.replace("refs/tags/", ""),
                "commit": payload.get("after"),
                "repository": payload.get("repository", {}).get("full_name")
                or payload.get("project", {}).get("path_with_namespace"),
                "is_tag": True,
            }

        elif event.event_type == "release":
            payload = event.payload
            action = payload.get("action")
            if action == "published":
                return {
                    "branch": payload.get("release", {}).get("target_commitish", "main"),
                    "commit": payload.get("release", {}).get("target_commitish"),
                    "repository": payload.get("repository", {}).get("full_name"),
                    "is_release": True,
                    "tag": payload.get("release", {}).get("tag_name"),
                }
            return None

        elif event.event_type == "workflow_run":
            payload = event.payload
            action = payload.get("action")
            if action == "completed":
                return {
                    "branch": payload.get("workflow_run", {}).get("head_branch"),
                    "commit": payload.get("workflow_run", {}).get("head_sha"),
                    "repository": payload.get("repository", {}).get("full_name"),
                    "is_workflow": True,
                    "workflow_name": payload.get("workflow_run", {}).get("name"),
                }
            return None

        elif event.event_type == "branch_created":
            payload = event.payload
            return {
                "branch": payload.get("ref"),
                "repository": payload.get("repository", {}).get("full_name"),
                "is_branch": True,
            }

        elif event.event_type == "tag_created":
            payload = event.payload
            ref = payload.get("ref", "") or ""
            return {
                "branch": ref.replace("refs/tags/", ""),
                "repository": payload.get("repository", {}).get("full_name"),
                "is_tag": True,
                "tag": ref.replace("refs/tags/", ""),
            }

        return None


class WebhookEndpoint:
    """Webhook endpoint configuration."""

    def __init__(self, name: str, url: str, events: list[str], secret: Optional[str] = None):
        self.name = name
        self.url = url
        self.events = events
        self.secret = secret
        self.created_at = datetime.utcnow()
        self.is_active = True


# In-memory storage for webhooks (would be in database in production)
_webhooks: dict[str, WebhookEndpoint] = {}


def register_webhook(
    name: str, url: str, events: list[str], secret: Optional[str] = None
) -> WebhookEndpoint:
    """Register a new webhook."""
    webhook = WebhookEndpoint(name, url, events, secret)
    _webhooks[name] = webhook
    return webhook


def get_webhook(name: str) -> Optional[WebhookEndpoint]:
    """Get a webhook by name."""
    return _webhooks.get(name)


def list_webhooks() -> list[WebhookEndpoint]:
    """List all registered webhooks."""
    return list(_webhooks.values())


def trigger_webhook_builds(event: WebhookEvent):
    """Trigger builds based on webhook event."""
    # This would create builds in the database
    # Implementation depends on the build creation API
    pass
