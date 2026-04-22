# SPDX-License-Identifier: MIT
# CI Engine - Structured Logging

import logging
import sys
import os
from datetime import datetime, timezone

from ci_engine.core.logging import get_logger

logger = get_logger("ci_engine.server")


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    service_name: str = "ci-engine-server",
) -> None:
    """Setup structured logging for the application."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if json_format or os.environ.get("LOG_FORMAT", "") == "json":
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
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


__all__ = ["setup_logging"]
