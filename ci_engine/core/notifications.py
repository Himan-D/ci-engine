# SPDX-License-Identifier: MIT
# CI Engine - Build Notifications (Slack/Discord/Email)

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from enum import Enum

import requests
from pydantic import BaseModel
from datetime import datetime, timezone


logger = logging.getLogger(__name__)


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


class EmailConfig(BaseModel):
    """Email notification configuration."""

    smtp_host: str
    smtp_port: int = 587
    smtp_user: str
    smtp_password: str
    email_from: str
    email_to: str
    events: list[NotificationEvent]
    enabled: bool = True


class NotificationService:
    """Service for sending build notifications."""

    def __init__(self):
        self._configs: list[NotificationConfig] = []
        self._email_config: Optional[EmailConfig] = None
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

        smtp_host = os.environ.get("SMTP_HOST")
        if smtp_host:
            events_str = os.environ.get("EMAIL_NOTIFY_EVENTS", "build.completed,build.failed")
            events = [NotificationEvent(e.strip()) for e in events_str.split(",")]
            self._email_config = EmailConfig(
                smtp_host=smtp_host,
                smtp_port=int(os.environ.get("SMTP_PORT", "587")),
                smtp_user=os.environ.get("SMTP_USER", ""),
                smtp_password=os.environ.get("SMTP_PASSWORD", ""),
                email_from=os.environ.get("EMAIL_FROM", os.environ.get("SMTP_USER", "")),
                email_to=os.environ.get("EMAIL_TO", ""),
                events=events,
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
            except Exception as e:
                logger.warning(f"Failed to send {config.type} notification: {e}")

        if self._email_config and event in self._email_config.events:
            try:
                self._send_email(event, data)
                sent += 1
            except Exception as e:
                logger.warning(f"Failed to send email notification: {e}")

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

        # Append AI analysis fields if present
        ai = data.get("ai_analysis")
        if ai:
            if ai.get("root_cause"):
                fields.append({"title": "AI Root Cause", "value": ai["root_cause"]})
            if ai.get("fixed_command") and ai.get("fix_applied"):
                fields.append({"title": "Auto-fix Applied", "value": f"`{ai['fixed_command']}`"})
            elif ai.get("fixed_command"):
                fields.append({"title": "AI Suggested Fix", "value": f"`{ai['fixed_command']}`"})
            if ai.get("pipeline_suggestion"):
                fields.append({"title": "AI Suggestion", "value": ai["pipeline_suggestion"]})

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

        # Append AI analysis fields if present
        ai = data.get("ai_analysis")
        if ai:
            if ai.get("root_cause"):
                fields.append({"name": "AI Root Cause", "value": ai["root_cause"], "inline": False})
            if ai.get("fixed_command") and ai.get("fix_applied"):
                fields.append({"name": "Auto-fix Applied", "value": f"`{ai['fixed_command']}`", "inline": False})
            elif ai.get("fixed_command"):
                fields.append({"name": "AI Suggested Fix", "value": f"`{ai['fixed_command']}`", "inline": False})
            if ai.get("pipeline_suggestion"):
                fields.append({"name": "AI Suggestion", "value": ai["pipeline_suggestion"], "inline": False})

        embed = {
            "description": description,
            "color": color,
            "fields": fields,
            "footer": {"text": "CI Engine"},
            "timestamp": data.get("timestamp"),
        }

        payload = {"embeds": [embed]}

        requests.post(config.webhook_url, json=payload, timeout=5)

    def _send_email(self, event: NotificationEvent, data: dict):
        """Send email notification."""
        if not self._email_config:
            return

        title = self._get_notification_title(event, data)
        body = self._format_email_body(event, data)

        msg = MIMEMultipart()
        msg["From"] = self._email_config.email_from
        msg["To"] = self._email_config.email_to
        msg["Subject"] = f"[CI Engine] {title}"

        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(
            self._email_config.smtp_host,
            self._email_config.smtp_port,
        ) as server:
            server.starttls()
            server.login(self._email_config.smtp_user, self._email_config.smtp_password)
            server.send_message(msg)

    def _format_email_body(self, event: NotificationEvent, data: dict) -> str:
        """Format email body HTML."""
        html = ["<html><body>"]

        if "build" in data:
            build = data["build"]
            html.append(f"<h2>Build #{build.get('id')}</h2>")
            html.append(f"<p><strong>Branch:</strong> {build.get('branch', 'N/A')}</p>")
            html.append(f"<p><strong>Status:</strong> {build.get('status', 'N/A')}</p>")
            html.append(
                f"<p><strong>Commit:</strong> {build.get('commit', 'N/A')[:8] if build.get('commit') else 'N/A'}</p>"
            )

        if "job" in data:
            job = data["job"]
            html.append(f"<h3>Job: {job.get('label', 'N/A')}</h3>")
            html.append(f"<p><strong>Exit Code:</strong> {job.get('exit_code', 'N/A')}</p>")

        html.append(f"<p><em>Timestamp: {data.get('timestamp', 'N/A')}</em></p>")
        html.append("</body></html>")

        return "".join(html)

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
    data = {
        "build": build_data,
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    notification_service.notify(event, data)


def send_job_notification(event: NotificationEvent, job_data: dict, build_data: dict):
    """Send job notification."""
    data = {
        "build": build_data,
        "job": job_data,
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    notification_service.notify(event, data)
