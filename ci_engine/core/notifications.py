# SPDX-License-Identifier: MIT
# CI Engine - Build Notifications (Slack/Discord)

import os
from typing import Optional
from enum import Enum

import requests
from pydantic import BaseModel


class NotificationType(str, Enum):
    """Notification types."""

    SLACK = "slack"
    DISCORD = "discord"
    EMAIL = "email"


class NotificationEvent(str, Enum):
    """Notification events."""

    BUILD_STARTED = "build.started"
    BUILD_COMPLETED = "build.completed"
    BUILD_FAILED = "build.failed"
    JOB_STARTED = "job.started"
    JOB_COMPLETED = "job.completed"
    JOB_FAILED = "job.failed"
    AGENT_OFFLINE = "agent.offline"
    AGENT_ONLINE = "agent.online"


class NotificationConfig(BaseModel):
    """Notification configuration."""

    type: NotificationType
    webhook_url: str
    events: list[NotificationEvent]
    enabled: bool = True
    channel: Optional[str] = None
    username: Optional[str] = None


class NotificationService:
    """Service for sending build notifications."""

    def __init__(self):
        self._configs: list[NotificationConfig] = []
        self._load_configs()

    def _load_configs(self):
        """Load notification configs from environment."""
        slack_url = os.environ.get("SLACK_WEBHOOK_URL")
        if slack_url:
            events_str = os.environ.get("SLACK_NOTIFY_EVENTS", "build.completed,build.failed")
            events = [NotificationEvent(e.strip()) for e in events_str.split(",")]
            self._configs.append(
                NotificationConfig(
                    type=NotificationType.SLACK,
                    webhook_url=slack_url,
                    events=events,
                    channel=os.environ.get("SLACK_CHANNEL"),
                    username=os.environ.get("SLACK_USERNAME", "CI Engine"),
                )
            )

        discord_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if discord_url:
            events_str = os.environ.get("DISCORD_NOTIFY_EVENTS", "build.completed,build.failed")
            events = [NotificationEvent(e.strip()) for e in events_str.split(",")]
            self._configs.append(
                NotificationConfig(
                    type=NotificationType.DISCORD,
                    webhook_url=discord_url,
                    events=events,
                )
            )

    def notify(self, event: NotificationEvent, data: dict) -> int:
        """Send notification for an event."""
        sent = 0

        for config in self._configs:
            if not config.enabled or event not in config.events:
                continue

            try:
                if config.type == NotificationType.SLACK:
                    self._send_slack(config, event, data)
                elif config.type == NotificationType.DISCORD:
                    self._send_discord(config, event, data)
                sent += 1
            except Exception:
                pass

        return sent

    def _send_slack(self, config: NotificationConfig, event: NotificationEvent, data: dict):
        """Send Slack notification."""
        color = self._get_status_color(event, data)
        status_emoji = self._get_status_emoji(event)

        fields = []
        if "build" in data:
            build = data["build"]
            fields.append({"title": "Build", "value": f"#{build.get('id', 'N/A')}"})
            fields.append({"title": "Branch", "value": build.get("branch", "N/A")})
            fields.append(
                {"title": "Status", "value": f"{status_emoji} {build.get('status', 'N/A')}"}
            )

        if "job" in data:
            job = data["job"]
            fields.append({"title": "Job", "value": job.get("label", "N/A")})
            fields.append({"title": "Exit Code", "value": str(job.get("exit_code", "N/A"))})

        payload = {
            "channel": config.channel,
            "username": config.username or "CI Engine",
            "attachments": [
                {
                    "color": color,
                    "title": self._get_notification_title(event, data),
                    "fields": fields,
                    "footer": "CI Engine",
                    "ts": data.get("timestamp", int(__import__("time").time())),
                }
            ],
        }

        requests.post(config.webhook_url, json=payload, timeout=5)

    def _send_discord(self, config: NotificationConfig, event: NotificationEvent, data: dict):
        """Send Discord notification."""
        color = self._get_discord_color(event, data)
        status_emoji = self._get_status_emoji(event)

        description = self._get_notification_title(event, data)

        fields = []
        if "build" in data:
            build = data["build"]
            fields.append({"name": "Build", "value": f"#{build.get('id', 'N/A')}", "inline": True})
            fields.append({"name": "Branch", "value": build.get("branch", "N/A"), "inline": True})
            fields.append(
                {
                    "name": "Status",
                    "value": f"{status_emoji} {build.get('status', 'N/A')}",
                    "inline": True,
                }
            )

        if "job" in data:
            job = data["job"]
            fields.append({"name": "Job", "value": job.get("label", "N/A")})

        embed = {
            "description": description,
            "color": color,
            "fields": fields,
            "footer": {"text": "CI Engine"},
            "timestamp": data.get("timestamp"),
        }

        payload = {"embeds": [embed]}

        requests.post(config.webhook_url, json=payload, timeout=5)

    def _get_notification_title(self, event: NotificationEvent, data: dict) -> str:
        """Get notification title based on event."""
        titles = {
            NotificationEvent.BUILD_STARTED: "Build Started",
            NotificationEvent.BUILD_COMPLETED: "Build Passed",
            NotificationEvent.BUILD_FAILED: "Build Failed",
            NotificationEvent.JOB_STARTED: "Job Started",
            NotificationEvent.JOB_COMPLETED: "Job Passed",
            NotificationEvent.JOB_FAILED: "Job Failed",
            NotificationEvent.AGENT_OFFLINE: "Agent Offline",
            NotificationEvent.AGENT_ONLINE: "Agent Online",
        }
        return titles.get(event, "CI Engine Notification")

    def _get_status_emoji(self, event: NotificationEvent) -> str:
        """Get status emoji based on event."""
        if "completed" in event.value or "passed" in event.value:
            return "✅"
        if "failed" in event.value:
            return "❌"
        if "started" in event.value:
            return "🔄"
        if "offline" in event.value:
            return "🔴"
        if "online" in event.value:
            return "🟢"
        return "📢"

    def _get_status_color(self, event: NotificationEvent, data: dict) -> str:
        """Get Slack color based on event."""
        if "failed" in event.value:
            return "#FF0000"
        if "completed" in event.value or "passed" in event.value:
            return "#00FF00"
        if "started" in event.value:
            return "#FFFF00"
        if "offline" in event.value:
            return "#FF0000"
        if "online" in event.value:
            return "#00FF00"
        return "#808080"

    def _get_discord_color(self, event: NotificationEvent, data: dict) -> int:
        """Get Discord color based on event."""
        if "failed" in event.value:
            return 16711680
        if "completed" in event.value or "passed" in event.value:
            return 65280
        if "started" in event.value:
            return 16776960
        if "offline" in event.value:
            return 16711680
        if "online" in event.value:
            return 65280
        return 8421504


notification_service = NotificationService()


def send_build_notification(event: NotificationEvent, build_data: dict):
    """Send build notification."""
    from datetime import datetime

    data = {
        "build": build_data,
        "timestamp": int(datetime.utcnow().timestamp()),
    }
    notification_service.notify(event, data)


def send_job_notification(event: NotificationEvent, job_data: dict, build_data: dict):
    """Send job notification."""
    from datetime import datetime

    data = {
        "build": build_data,
        "job": job_data,
        "timestamp": int(datetime.utcnow().timestamp()),
    }
    notification_service.notify(event, data)
