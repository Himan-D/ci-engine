# SPDX-License-Identifier: MIT
# CI Engine - Structured Logging

import logging
import sys
import os
import json
from datetime import datetime, timezone
from typing import Any, Optional
from functools import wraps


class StructuredLogger:
    """Structured JSON logger for CI Engine."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name
        self.json_format = os.environ.get("LOG_FORMAT", "") == "json"

    def _format_message(self, message: str, **kwargs: Any) -> str:
        """Format message with context."""
        if self.json_format:
            log_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "level": "INFO",
                "logger": self.name,
                "message": message,
            }
            if kwargs:
                log_data["context"] = kwargs
            return json.dumps(log_data)
        return message

    def debug(self, message: str, **kwargs: Any):
        self.logger.debug(self._format_message(message, **kwargs), **kwargs)

    def info(self, message: str, **kwargs: Any):
        self.logger.info(self._format_message(message, **kwargs), **kwargs)

    def warning(self, message: str, **kwargs: Any):
        self.logger.warning(self._format_message(message, **kwargs), **kwargs)

    def error(self, message: str, **kwargs: Any):
        self.logger.error(self._format_message(message, **kwargs), **kwargs)

    def critical(self, message: str, **kwargs: Any):
        self.logger.critical(self._format_message(message, **kwargs), **kwargs)

    def log(self, level: int, message: str, **kwargs: Any):
        self.logger.log(level, self._format_message(message, **kwargs), **kwargs)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    return StructuredLogger(name)


class LogContext:
    """Context manager for adding logging context."""

    def __init__(self, logger: StructuredLogger, **context: Any):
        self.logger = logger
        self.context = context

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    service_name: str = "ci-engine-server",
) -> None:
    """Setup structured logging for the application."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    is_json = json_format or os.environ.get("LOG_FORMAT", "") == "json"

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if is_json:
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.WARNING)


def log_api_request(logger: StructuredLogger):
    """Decorator to log API requests."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger.info(f"API call: {func.__name__}", endpoint=func.__name__)
            try:
                result = await func(*args, **kwargs)
                logger.info(f"API success: {func.__name__}", endpoint=func.__name__)
                return result
            except Exception as e:
                logger.error(f"API error: {func.__name__}", endpoint=func.__name__, error=str(e))
                raise

        return wrapper

    return decorator


__all__ = ["setup_logging", "get_logger", "StructuredLogger", "LogContext"]
