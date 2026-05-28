"""
Graceful degradation and failover modes
"""

import logging
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class FailureMode(Enum):
    """
    How rate limiting behaves when storage fails

    STRICT: Block everything (fail closed) - no unauthorized access
    OPEN: Allow everything (fail open) - service availability
    BYPASS: Skip rate limiting - for testing/emergency
    """

    STRICT = "strict"
    OPEN = "open"
    BYPASS = "bypass"


class FailoverHandler:
    """
    Handle storage failures gracefully
    """

    def __init__(
        self,
        failure_mode: FailureMode = FailureMode.STRICT,
        custom_handler: Optional[Callable] = None,
        max_failures: int = 5,
        failure_window: int = 60,
    ):
        """
        Initialize failover handler

        Args:
            failure_mode: How to handle failures
            custom_handler: Optional callback for custom handling
            max_failures: Max failures before triggering failover
            failure_window: Time window for failure count (seconds)
        """
        self.failure_mode = failure_mode
        self.custom_handler = custom_handler
        self.max_failures = max_failures
        self.failure_window = failure_window

        self._failure_count = 0
        self._failure_timestamps: list[float] = []
        self._in_failover = False

        logger.info(f"FailoverHandler: mode={failure_mode.value}, max_failures={max_failures}")

    def record_failure(self):
        """Record a storage failure"""
        import time

        now = time.time()

        # Remove old failures outside window
        self._failure_timestamps = [
            t for t in self._failure_timestamps if now - t < self.failure_window
        ]

        self._failure_timestamps.append(now)
        self._failure_count = len(self._failure_timestamps)

        if self._failure_count >= self.max_failures:
            self._in_failover = True
            logger.error(
                f"Failover triggered: {self._failure_count} failures "
                f"in {self.failure_window}s, mode={self.failure_mode.value}"
            )

            if self.custom_handler:
                try:
                    self.custom_handler(self.failure_mode)
                except Exception as e:
                    logger.error(f"Custom failover handler error: {e}")

    def record_success(self):
        """Record successful storage operation"""
        if self._in_failover:
            self._in_failover = False
            self._failure_count = 0
            self._failure_timestamps = []
            logger.info("Failover resolved - storage healthy again")

    def should_allow(self) -> bool:
        """Determine if request should be allowed"""
        if self.failure_mode == FailureMode.STRICT:
            return not self._in_failover  # Block if failing
        elif self.failure_mode == FailureMode.OPEN:
            return True  # Always allow
        elif self.failure_mode == FailureMode.BYPASS:
            return True  # No limiting

        return True  # Default to allow

    def get_status(self) -> dict:
        """Get failover status"""
        return {
            "in_failover": self._in_failover,
            "failure_count": self._failure_count,
            "failure_mode": self.failure_mode.value,
            "failures_in_window": len(self._failure_timestamps),
        }
