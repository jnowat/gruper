"""
Three-strike circuit breaker — mirrors Gruper core's agent auto-disable pattern.

CLOSED: normal operation.
OPEN:   three consecutive Ollama failures; new tasks queued, not dispatched.
        Resets to CLOSED on first successful Ollama call (auto-recovery).
"""

import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_THRESHOLD = 3


class CircuitBreaker:
    def __init__(
        self,
        on_open: Callable[[], Awaitable[None]] | None = None,
        on_close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._failures = 0
        self._is_open = False
        self._on_open = on_open    # called when circuit trips open
        self._on_close = on_close  # called when circuit recovers

    @property
    def is_open(self) -> bool:
        return self._is_open

    async def record_failure(self) -> None:
        self._failures += 1
        logger.warning("Ollama failure %d/%d", self._failures, _THRESHOLD)
        if self._failures >= _THRESHOLD and not self._is_open:
            self._is_open = True
            logger.error(
                "Circuit opened after %d consecutive Ollama failures — marking degraded",
                _THRESHOLD,
            )
            if self._on_open:
                await self._on_open()

    async def record_success(self) -> None:
        was_open = self._is_open
        self._failures = 0
        self._is_open = False
        if was_open:
            logger.info("Circuit closed after successful Ollama call — marking idle")
            if self._on_close:
                await self._on_close()

    def reset(self) -> None:
        self._failures = 0
        self._is_open = False
