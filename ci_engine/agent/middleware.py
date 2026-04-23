# SPDX-License-Identifier: MIT
# CI Engine - Agent Middleware System

from abc import ABC, abstractmethod
from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum


class MiddlewareOrder(str, Enum):
    """Middleware execution order."""

    FIRST = "first"
    EARLY = "early"
    NORMAL = "normal"
    LATE = "late"
    LAST = "last"


@dataclass
class MiddlewareContext:
    """Context passed through middleware chain."""

    job: dict
    result: Optional[tuple[int, str, str]] = None
    error: Optional[Exception] = None
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class AgentMiddleware(ABC):
    """Base class for agent middleware.

    Middleware provides a way to transform jobs and results through a chain
    of processors. Unlike plugins which are focused on hooks, middleware
    is focused on transformation.

    Example:
        ```python
        class EnvMiddleware(AgentMiddleware):
            '''Add environment variables to all jobs.'''
            order = MiddlewareOrder.NORMAL

            def pre_process(self, context: MiddlewareContext) -> MiddlewareContext:
                context.job["env_vars"] = context.job.get("env_vars", {})
                context.job["env_vars"]["CI_BUILD_TIME"] = str(time.time())
                return context
        ```
    """

    name: str = "base-middleware"
    order: MiddlewareOrder = MiddlewareOrder.NORMAL

    def __init__(self):
        self._enabled = True

    @property
    def enabled(self) -> bool:
        """Check if middleware is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable middleware."""
        self._enabled = value

    def pre_process(self, context: MiddlewareContext) -> MiddlewareContext:
        """Process job before execution.

        Args:
            context: Job context

        Returns:
            Modified context
        """
        return context

    def post_process(self, context: MiddlewareContext) -> MiddlewareContext:
        """Process job result after execution.

        Args:
            context: Job context with result

        Returns:
            Modified context
        """
        return context

    def on_error(self, context: MiddlewareContext) -> MiddlewareContext:
        """Process job error.

        Args:
            context: Job context with error

        Returns:
            Modified context
        """
        return context


class MiddlewareChain:
    """Chain of middleware processors.

    Processes middleware in order based on their order attribute.
    """

    def __init__(self):
        self._middleware: list[AgentMiddleware] = []

    def add(self, middleware: AgentMiddleware) -> None:
        """Add middleware to the chain.

        Args:
            middleware: Middleware to add
        """
        self._middleware.append(middleware)
        self._sort_middleware()

    def _sort_middleware(self) -> None:
        """Sort middleware by order."""
        order_map = {
            MiddlewareOrder.FIRST: 0,
            MiddlewareOrder.EARLY: 1,
            MiddlewareOrder.NORMAL: 2,
            MiddlewareOrder.LATE: 3,
            MiddlewareOrder.LAST: 4,
        }
        self._middleware.sort(key=lambda m: order_map.get(m.order, 2))

    def process_pre(self, job: dict) -> dict:
        """Process job before execution.

        Args:
            job: Job dictionary

        Returns:
            Modified job
        """
        context = MiddlewareContext(job=job)
        for middleware in self._middleware:
            if middleware.enabled:
                try:
                    context = middleware.pre_process(context)
                except Exception:
                    pass
        return context.job

    def process_post(self, job: dict, result: tuple[int, str, str]) -> tuple[int, str, str]:
        """Process job result after execution.

        Args:
            job: Job dictionary
            result: (exit_code, stdout, stderr)

        Returns:
            Modified result tuple
        """
        context = MiddlewareContext(job=job, result=result)
        for middleware in self._middleware:
            if middleware.enabled:
                try:
                    context = middleware.post_process(context)
                except Exception:
                    pass
        if context.result:
            return context.result
        return result

    def process_error(self, job: dict, error: Exception) -> None:
        """Process job error.

        Args:
            job: Job dictionary
            error: Exception that occurred
        """
        context = MiddlewareContext(job=job, error=error)
        for middleware in self._middleware:
            if middleware.enabled:
                try:
                    middleware.on_error(context)
                except Exception:
                    pass


class MiddlewareManager:
    """Manager for middleware chains.

    Allows organizing middleware into named chains for different purposes.
    """

    def __init__(self):
        self._chains: dict[str, MiddlewareChain] = {}
        self._default_chain = MiddlewareChain()

    def get_chain(self, name: str = "default") -> MiddlewareChain:
        """Get or create a middleware chain by name.

        Args:
            name: Chain name

        Returns:
            MiddlewareChain instance
        """
        if name not in self._chains:
            self._chains[name] = MiddlewareChain()
        return self._chains[name]

    def add_middleware(self, middleware: AgentMiddleware, chain: str = "default") -> None:
        """Add middleware to a chain.

        Args:
            middleware: Middleware to add
            chain: Chain name (default: "default")
        """
        chain_obj = self.get_chain(chain)
        chain_obj.add(middleware)

    def process_pre(self, job: dict, chain: str = "default") -> dict:
        """Process job through a chain.

        Args:
            job: Job dictionary
            chain: Chain name

        Returns:
            Modified job
        """
        return self.get_chain(chain).process_pre(job)

    def process_post(
        self, job: dict, result: tuple[int, str, str], chain: str = "default"
    ) -> tuple[int, str, str]:
        """Process result through a chain.

        Args:
            job: Job dictionary
            result: Result tuple
            chain: Chain name

        Returns:
            Modified result
        """
        return self.get_chain(chain).process_post(job, result)


class TransformMiddleware(AgentMiddleware):
    """Middleware that can transform both job and result."""

    name = "transform-middleware"
    order = MiddlewareOrder.NORMAL

    def transform_job(self, job: dict) -> dict:
        """Override to transform job. Default: no-op."""
        return job

    def transform_result(self, job: dict, result: tuple[int, str, str]) -> tuple[int, str, str]:
        """Override to transform result. Default: no-op."""
        return result

    def pre_process(self, context: MiddlewareContext) -> MiddlewareContext:
        context.job = self.transform_job(context.job)
        return context

    def post_process(self, context: MiddlewareContext) -> MiddlewareContext:
        if context.result is not None:
            context.result = self.transform_result(context.job, context.result)
        return context


class FilterMiddleware(AgentMiddleware):
    """Middleware that can filter (skip) jobs."""

    name = "filter-middleware"
    order = MiddlewareOrder.FIRST

    def should_skip(self, job: dict) -> bool:
        """Override to determine if job should be skipped.

        Returns:
            True to skip the job
        """
        return False

    def get_skip_reason(self, job: dict) -> str:
        """Get reason for skipping job."""
        return "Filtered by middleware"


class ValidationMiddleware(AgentMiddleware):
    """Middleware that validates job parameters."""

    name = "validation-middleware"
    order = MiddlewareOrder.FIRST

    def validate(self, job: dict) -> list[str]:
        """Override to validate job.

        Returns:
            List of validation errors (empty if valid)
        """
        return []

    def pre_process(self, context: MiddlewareContext) -> MiddlewareContext:
        errors = self.validate(context.job)
        if errors:
            raise ValueError(f"Validation failed: {', '.join(errors)}")
        return context
