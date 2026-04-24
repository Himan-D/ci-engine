# SPDX-License-Identifier: MIT
# CI Engine - Unit tests for scheduler module

import pytest
from ci_engine.core.scheduler import Scheduler


class TestScheduler:
    """Tests for Scheduler class."""

    @pytest.fixture
    def scheduler(self):
        """Create scheduler instance."""
        return Scheduler()

    def test_scheduler_init(self, scheduler):
        """Test scheduler initialization."""
        assert scheduler is not None
