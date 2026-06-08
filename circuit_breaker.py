"""Circuit breaker for MuninnDB network calls."""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Simple circuit breaker for network calls."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, threshold: int = 5, timeout_s: float = 60.0):
        self._threshold = threshold
        self._timeout_s = timeout_s
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure = 0.0
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._state == self.OPEN:
                if time.time() - self._last_failure > self._timeout_s:
                    self._state = self.HALF_OPEN
                    return False
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure = time.time()
            if self._failure_count >= self._threshold:
                self._state = self.OPEN
                logger.warning(
                    "MuninnDB circuit breaker OPEN after %d failures",
                    self._failure_count,
                )
