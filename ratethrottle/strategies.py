"""
RateThrottle - Rate Limiting Strategies

Production-grade implementations of various rate limiting algorithms
with comprehensive error handling and edge case management.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Tuple

from .core import RateThrottleRule, RateThrottleStatus
from .exceptions import StorageError
from .storage_backend import StorageBackend

logger = logging.getLogger(__name__)


class RateLimitStrategy(ABC):
    """
    Abstract base class for rate limiting strategies

    All strategies must implement the is_allowed method with proper
    error handling and return a tuple of (allowed, status).
    """

    @abstractmethod
    def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: StorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        """
        Check if request is allowed under this strategy

        Args:
            identifier: Client identifier
            rule: Rate limiting rule to apply
            storage: Storage backend for state

        Returns:
            Tuple of (allowed: bool, status: RateThrottleStatus)

        Raises:
            StorageError: If storage operation fails
        """
        pass

    def get_name(self) -> str:
        """Get strategy name"""
        return self.__class__.__name__.replace("Strategy", "").lower()


class TokenBucketStrategy(RateLimitStrategy):
    """
    Token Bucket algorithm implementation

    Tokens are added to a bucket at a constant rate. Each request consumes
    one token. If no tokens available, request is blocked.

    Features:
        - Allows traffic bursts up to bucket capacity
        - Smooth long-term rate limiting
        - Refills tokens continuously based on time

    Best for:
        - APIs that allow occasional bursts
        - Services with varying load patterns
        - Rate limits where some burst is acceptable

    Example:
        limit=100, window=60, burst=150
        - Allows 100 requests per minute normally
        - Can burst up to 150 requests if bucket is full
        - Refills at ~1.67 tokens per second
    """

    def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: StorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        """Check if request is allowed"""
        key = f"tb:{rule.name}:{identifier}"
        now = time.time()

        try:
            # Get current state
            state = storage.get(key)

            if state is None:
                # Initialize new bucket
                state = {"tokens": float(rule.burst), "last_update": now}
                logger.debug(f"Initialized token bucket for {identifier}: " f"{rule.burst} tokens")

            # Validate state structure
            if not isinstance(state, dict) or "tokens" not in state or "last_update" not in state:
                logger.warning(f"Invalid token bucket state for {identifier}, reinitializing")
                state = {"tokens": float(rule.burst), "last_update": now}

            # Calculate refill
            time_passed = now - state["last_update"]
            refill_rate = rule.limit / rule.window
            tokens_to_add = time_passed * refill_rate

            # Update tokens (cap at burst limit)
            state["tokens"] = min(float(rule.burst), state["tokens"] + tokens_to_add)
            state["last_update"] = now

            # Check if we have tokens available
            if state["tokens"] >= 1.0:
                # Consume one token
                state["tokens"] -= 1.0

                # Save state
                storage.set(key, state, rule.window * 2)

                logger.debug(
                    f"Token bucket allowed for {identifier}: "
                    f"{state['tokens']:.2f} tokens remaining"
                )

                return True, RateThrottleStatus(
                    allowed=True,
                    remaining=int(state["tokens"]),
                    limit=rule.limit,
                    reset_time=int(now + rule.window),
                    rule_name=rule.name,
                )
            else:
                # No tokens available
                # Calculate when next token will be available
                time_until_token = (1.0 - state["tokens"]) / refill_rate
                retry_after = max(1, int(time_until_token))

                # Save state (don't consume token)
                storage.set(key, state, rule.window * 2)

                logger.debug(
                    f"Token bucket blocked {identifier}: "
                    f"no tokens available, retry after {retry_after}s"
                )

                return False, RateThrottleStatus(
                    allowed=False,
                    remaining=0,
                    limit=rule.limit,
                    reset_time=int(now + retry_after),
                    retry_after=retry_after,
                    rule_name=rule.name,
                    blocked=True,
                )

        except Exception as e:
            logger.error(f"Token bucket strategy error: {e}")
            raise StorageError(f"Token bucket check failed: {e}") from e


class LeakyBucketStrategy(RateLimitStrategy):
    """
    Leaky Bucket algorithm implementation

    Requests are added to a queue. The queue "leaks" at a constant rate.
    If queue is full, requests are rejected.

    Features:
        - Enforces smooth output rate
        - Absorbs bursts with queue
        - Predictable processing rate

    Best for:
        - Services requiring smooth traffic flow
        - Systems with limited processing capacity
        - Rate limits where bursts are problematic

    Example:
        limit=100, window=60
        - Processes requests at constant rate (1.67/sec)
        - Queue can hold up to 100 pending requests
        - Rejects requests if queue is full
    """

    def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: StorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        """Check if request is allowed"""
        queue_key = f"lb:q:{rule.name}:{identifier}"
        now = time.time()

        try:
            # Get queue of request timestamps
            queue = storage.get(queue_key)

            if queue is None:
                queue = []

            # Validate queue structure
            if not isinstance(queue, list):
                logger.warning(f"Invalid leaky bucket queue for {identifier}, reinitializing")
                queue = []

            # Remove requests outside the window (leaked out)
            cutoff_time = now - rule.window
            queue = [ts for ts in queue if isinstance(ts, (int, float)) and ts > cutoff_time]

            # Check if we can add to queue
            if len(queue) < rule.limit:
                # Add request to queue
                queue.append(now)
                storage.set(queue_key, queue, rule.window + 60)

                remaining = rule.limit - len(queue)
                logger.debug(
                    f"Leaky bucket allowed for {identifier}: " f"{remaining} slots remaining"
                )

                return True, RateThrottleStatus(
                    allowed=True,
                    remaining=remaining,
                    limit=rule.limit,
                    reset_time=int(now + rule.window),
                    rule_name=rule.name,
                )
            else:
                # Queue is full
                # Calculate when oldest request will leak out
                if queue:
                    oldest_request = min(queue)
                    retry_after = max(1, int((oldest_request + rule.window) - now))
                else:
                    retry_after = rule.window

                logger.debug(
                    f"Leaky bucket blocked {identifier}: " f"queue full, retry after {retry_after}s"
                )

                return False, RateThrottleStatus(
                    allowed=False,
                    remaining=0,
                    limit=rule.limit,
                    reset_time=int(now + retry_after),
                    retry_after=retry_after,
                    rule_name=rule.name,
                    blocked=True,
                )

        except Exception as e:
            logger.error(f"Leaky bucket strategy error: {e}")
            raise StorageError(f"Leaky bucket check failed: {e}") from e


class FixedWindowStrategy(RateLimitStrategy):
    """
    Fixed Window algorithm implementation

    Divides time into fixed windows. Counts requests in current window.

    Features:
        - Simple and efficient
        - Low memory usage
        - Atomic counter operations

    Limitations:
        - Vulnerable to edge case (2x rate at window boundaries)
        - Not perfectly accurate across boundaries

    Best for:
        - High-throughput scenarios
        - When simplicity is important
        - When edge case is acceptable

    Example:
        limit=100, window=60
        - Window 1: 00:00-00:59 (max 100 requests)
        - Window 2: 01:00-01:59 (max 100 requests)
        - Edge case: 99 req at 00:59, 100 req at 01:00 = 199 in 1 second
    """

    def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: StorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        """Check if request is allowed"""
        now = time.time()

        # Calculate window start (aligned to window boundaries)
        window_start = int(now / rule.window) * rule.window
        key = f"fw:{rule.name}:{identifier}:{window_start}"

        try:
            # Get current count
            count = storage.get(key)

            if count is None:
                count = 0

            # Validate count
            if not isinstance(count, (int, float)):
                logger.warning(f"Invalid fixed window count for {identifier}, resetting to 0")
                count = 0

            count = int(count)

            # Check if under limit
            if count < rule.limit:
                # Increment counter with TTL
                new_count = storage.increment(key, 1, rule.window + 10)
                remaining = rule.limit - new_count

                logger.debug(
                    f"Fixed window allowed for {identifier}: " f"{remaining} remaining in window"
                )

                return True, RateThrottleStatus(
                    allowed=True,
                    remaining=max(0, remaining),
                    limit=rule.limit,
                    reset_time=window_start + rule.window,
                    rule_name=rule.name,
                )
            else:
                # Limit exceeded in this window
                reset_time = window_start + rule.window
                retry_after = max(1, int(reset_time - now))

                logger.debug(
                    f"Fixed window blocked {identifier}: "
                    f"limit exceeded, retry after {retry_after}s"
                )

                return False, RateThrottleStatus(
                    allowed=False,
                    remaining=0,
                    limit=rule.limit,
                    reset_time=reset_time,
                    retry_after=retry_after,
                    rule_name=rule.name,
                    blocked=True,
                )

        except Exception as e:
            logger.error(f"Fixed window strategy error: {e}")
            raise StorageError(f"Fixed window check failed: {e}") from e


class SlidingWindowStrategy(RateLimitStrategy):
    """
    Sliding Window Log algorithm implementation

    Maintains a log of all request timestamps within the window.
    Counts requests in a sliding time window.

    Features:
        - Most accurate rate limiting
        - No edge case issues
        - True sliding window

    Limitations:
        - Higher memory usage (stores all timestamps)
        - More complex operations

    Best for:
        - When accuracy is critical
        - When memory is not constrained
        - APIs requiring precise rate limiting

    Example:
        limit=100, window=60
        - At any time T, counts requests from [T-60, T]
        - No edge case issues
        - Perfectly accurate
    """

    def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: StorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        """Check if request is allowed"""
        key = f"sw:{rule.name}:{identifier}"
        now = time.time()
        window_start = now - rule.window

        try:
            # Get request timestamps
            timestamps = storage.get(key)

            if timestamps is None:
                timestamps = []

            # Validate timestamps structure
            if not isinstance(timestamps, list):
                logger.warning(
                    f"Invalid sliding window timestamps for {identifier}, reinitializing"
                )
                timestamps = []

            # Remove timestamps outside the window
            timestamps = [
                ts for ts in timestamps if isinstance(ts, (int, float)) and ts > window_start
            ]

            # Check if under limit
            if len(timestamps) < rule.limit:
                # Add current timestamp
                timestamps.append(now)

                # Save with extra TTL buffer
                storage.set(key, timestamps, rule.window + 60)

                remaining = rule.limit - len(timestamps)

                # Calculate reset time (when oldest timestamp expires)
                if timestamps:
                    oldest_ts = min(timestamps)
                    reset_time = int(oldest_ts + rule.window)
                else:
                    reset_time = int(now + rule.window)

                logger.debug(f"Sliding window allowed for {identifier}: " f"{remaining} remaining")

                return True, RateThrottleStatus(
                    allowed=True,
                    remaining=remaining,
                    limit=rule.limit,
                    reset_time=reset_time,
                    rule_name=rule.name,
                )
            else:
                # Limit exceeded
                # Calculate when oldest request will expire
                if timestamps:
                    oldest = min(timestamps)
                    retry_after = max(1, int((oldest + rule.window) - now))
                    reset_time = int(oldest + rule.window)
                else:
                    retry_after = rule.window
                    reset_time = int(now + rule.window)

                logger.debug(
                    f"Sliding window blocked {identifier}: "
                    f"limit exceeded, retry after {retry_after}s"
                )

                return False, RateThrottleStatus(
                    allowed=False,
                    remaining=0,
                    limit=rule.limit,
                    reset_time=reset_time,
                    retry_after=retry_after,
                    rule_name=rule.name,
                    blocked=True,
                )

        except Exception as e:
            logger.error(f"Sliding window strategy error: {e}")
            raise StorageError(f"Sliding window check failed: {e}") from e
