"""
Three-strike circuit breaker with half-open recovery.

CLOSED:    normal operation.
OPEN:      three consecutive Ollama failures. New work FAILS FAST (with a
           clear "Ollama has been failing" error) instead of hanging.
HALF-OPEN: after a short cooldown, exactly one trial call is allowed through.
           Success closes the circuit; failure re-opens it and restarts the
           cooldown.

The half-open state is the load-bearing part. A previous version could only
close on a successful Ollama call — but while open it never *attempted* any
call, so three transient failures (Ollama restarting, machine waking from
sleep) locked the agent into a permanent silent no-Ollama state: it kept
heartbeating, kept looking "ready", and quietly swallowed every task forever.
That was the root cause of "agents appear to think but Ollama is never used".
"""

import logging
import time
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_THRESHOLD = 3
_COOLDOWN_S = 20.0


class CircuitBreaker:
    def __init__(
        self,
        on_open: Callable[[], Awaitable[None]] | None = None,
        on_close: Callable[[], Awaitable[None]] | None = None,
        cooldown_s: float = _COOLDOWN_S,
    ) -> None:
        self._failures = 0
        self._is_open = False
        self._opened_at = 0.0
        self._cooldown_s = cooldown_s
        self._trial_in_flight = False
        self._on_open = on_open    # called when circuit trips open
        self._on_close = on_close  # called when circuit recovers

    @property
    def is_open(self) -> bool:
        return self._is_open

    def should_attempt(self) -> bool:
        """True if a call may be made now.

        Closed → always. Open → only once the cooldown has elapsed, and then
        only ONE trial at a time (the half-open probe); everything else fails
        fast until the probe settles.
        """
        if not self._is_open:
            return True
        if self._trial_in_flight:
            return False
        if time.monotonic() - self._opened_at >= self._cooldown_s:
            self._trial_in_flight = True
            logger.info("Circuit half-open — allowing one trial Ollama call")
            return True
        return False

    async def record_failure(self) -> None:
        self._trial_in_flight = False
        self._failures += 1
        logger.warning("Ollama failure %d/%d", self._failures, _THRESHOLD)
        if self._failures >= _THRESHOLD:
            first_open = not self._is_open
            self._is_open = True
            self._opened_at = time.monotonic()  # (re)start the cooldown
            if first_open:
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
        self._trial_in_flight = False
        if was_open:
            logger.info("Circuit closed after successful Ollama call — marking idle")
            if self._on_close:
                await self._on_close()

    def reset(self) -> None:
        self._failures = 0
        self._is_open = False
        self._trial_in_flight = False
