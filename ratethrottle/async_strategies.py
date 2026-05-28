"""
RateThrottle - Async Rate Limiting Strategies

Implementations of various rate limiting algorithms
adapted for asynchronous execution.
"""

from __future__ import annotations

import logging
import math
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from .core import RateThrottleRule, RateThrottleStatus
    from .async_storage import AsyncStorageBackend, AsyncRedisStorage

from .exceptions import StorageError

logger = logging.getLogger(__name__)


class AsyncRateLimitStrategy(ABC):
    @abstractmethod
    async def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: AsyncStorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        pass

    def get_name(self) -> str:
        return self.__class__.__name__.replace("Strategy", "").lower()


class AsyncTokenBucketStrategy(AsyncRateLimitStrategy):
    async def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: AsyncStorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        from .core import RateThrottleStatus

        key = f"tb:{rule.name}:{identifier}"
        now = time.time()

        try:

            burst_val = float(rule.burst if rule.burst is not None else rule.limit)

            if isinstance(storage, AsyncRedisStorage):
                script = """
                local state_str = redis.call('get', KEYS[1])
                local now = tonumber(ARGV[3])
                local burst = tonumber(ARGV[1])
                local limit = tonumber(ARGV[4])
                local window = tonumber(ARGV[5])
                local refill_rate = limit / window
                local tokens = burst
                local last_update = now

                if state_str then
                    local state = cjson.decode(state_str)
                    tokens = tonumber(state.tokens)
                    last_update = tonumber(state.last_update)

                    local time_passed = now - last_update
                    local tokens_to_add = time_passed * refill_rate
                    tokens = math.min(burst, tokens + tokens_to_add)
                end

                if tokens >= 1.0 then
                    tokens = tokens - 1.0
                    local new_state = {tokens = tokens, last_update = now}
                    redis.call('setex', KEYS[1], tonumber(ARGV[2]), cjson.encode(new_state))
                    return {1, tokens}
                else
                    local time_until_token = (1.0 - tokens) / refill_rate
                    return {0, math.max(1, math.floor(time_until_token))}
                end
                """
                result = await storage.evaluate_lua(
                    script, [key], [burst_val, rule.window * 2, now, rule.limit, rule.window]
                )

                if result[0] == 1:
                    tokens_remaining = result[1]
                    return True, RateThrottleStatus(
                        allowed=True,
                        remaining=int(tokens_remaining),
                        limit=rule.limit,
                        reset_time=int(now + rule.window),
                        rule_name=rule.name,
                    )
                else:
                    retry_after = result[1]
                    return False, RateThrottleStatus(
                        allowed=False,
                        remaining=0,
                        limit=rule.limit,
                        reset_time=int(now + retry_after),
                        retry_after=retry_after,
                        rule_name=rule.name,
                        blocked=True,
                    )
            else:
                state = await storage.get(key)
                if state is None:
                    state = {"tokens": burst_val, "last_update": now}

                if (
                    not isinstance(state, dict)
                    or "tokens" not in state
                    or "last_update" not in state
                ):
                    state = {"tokens": burst_val, "last_update": now}

                time_passed = now - state["last_update"]
                refill_rate = rule.limit / rule.window
                tokens_to_add = time_passed * refill_rate

                state["tokens"] = min(burst_val, state["tokens"] + tokens_to_add)
                state["last_update"] = now

                if state["tokens"] >= 1.0:
                    state["tokens"] -= 1.0
                    await storage.set(key, state, rule.window * 2)
                    return True, RateThrottleStatus(
                        allowed=True,
                        remaining=int(state["tokens"]),
                        limit=rule.limit,
                        reset_time=int(now + rule.window),
                        rule_name=rule.name,
                    )
                else:
                    time_until_token = (1.0 - state["tokens"]) / refill_rate
                    retry_after = max(1, int(time_until_token))
                    await storage.set(key, state, rule.window * 2)
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
            logger.error(f"Async token bucket strategy error: {e}")
            raise StorageError(f"Async token bucket check failed: {e}") from e


class AsyncLeakyBucketStrategy(AsyncRateLimitStrategy):
    async def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: AsyncStorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        from .core import RateThrottleStatus

        queue_key = f"lb:{rule.name}:{identifier}"
        now = time.time()

        try:
            queue = await storage.get(queue_key)
            if queue is None:
                queue = []
            if not isinstance(queue, list):
                queue = []

            cutoff_time = now - rule.window
            queue = [ts for ts in queue if isinstance(ts, (int, float)) and ts > cutoff_time]

            if len(queue) < rule.limit:
                queue.append(now)
                await storage.set(queue_key, queue, rule.window + 60)
                remaining = rule.limit - len(queue)
                return True, RateThrottleStatus(
                    allowed=True,
                    remaining=remaining,
                    limit=rule.limit,
                    reset_time=int(now + rule.window),
                    rule_name=rule.name,
                )
            else:
                if queue:
                    oldest_request = min(queue)
                    retry_after = max(1, int((oldest_request + rule.window) - now))
                else:
                    retry_after = rule.window
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
            logger.error(f"Async leaky bucket strategy error: {e}")
            raise StorageError(f"Async leaky bucket check failed: {e}") from e


class AsyncFixedWindowStrategy(AsyncRateLimitStrategy):
    async def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: AsyncStorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        from .core import RateThrottleStatus

        now = time.time()
        window_start = int(now / rule.window) * rule.window
        key = f"fw:{rule.name}:{identifier}:{window_start}"

        try:
            count = await storage.get(key)
            if count is None:
                count = 0
            if not isinstance(count, (int, float)):
                count = 0
            count = int(count)

            if count < rule.limit:
                new_count = await storage.increment(key, 1, rule.window + 10)
                remaining = rule.limit - new_count
                return True, RateThrottleStatus(
                    allowed=True,
                    remaining=max(0, remaining),
                    limit=rule.limit,
                    reset_time=window_start + rule.window,
                    rule_name=rule.name,
                )
            else:
                reset_time = window_start + rule.window
                retry_after = max(1, int(reset_time - now))
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
            logger.error(f"Async fixed window strategy error: {e}")
            raise StorageError(f"Async fixed window check failed: {e}") from e


class AsyncSlidingWindowStrategy(AsyncRateLimitStrategy):
    async def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: AsyncStorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        from .core import RateThrottleStatus

        key = f"sw:{rule.name}:{identifier}"
        now = time.time()
        window_start = now - rule.window

        try:
            timestamps = await storage.get(key)
            if timestamps is None:
                timestamps = []
            if not isinstance(timestamps, list):
                timestamps = []

            timestamps = [
                ts for ts in timestamps if isinstance(ts, (int, float)) and ts > window_start
            ]

            if len(timestamps) < rule.limit:
                timestamps.append(now)
                await storage.set(key, timestamps, rule.window + 60)
                remaining = rule.limit - len(timestamps)

                if timestamps:
                    oldest_ts = min(timestamps)
                    reset_time = int(oldest_ts + rule.window)
                else:
                    reset_time = int(now + rule.window)

                return True, RateThrottleStatus(
                    allowed=True,
                    remaining=remaining,
                    limit=rule.limit,
                    reset_time=reset_time,
                    rule_name=rule.name,
                )
            else:
                if timestamps:
                    oldest = min(timestamps)
                    retry_after = max(1, int((oldest + rule.window) - now))
                    reset_time = int(oldest + rule.window)
                else:
                    retry_after = rule.window
                    reset_time = int(now + rule.window)

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
            logger.error(f"Async sliding window strategy error: {e}")
            raise StorageError(f"Async sliding window check failed: {e}") from e


class AsyncSlidingWindowCounterStrategy(AsyncRateLimitStrategy):
    async def is_allowed(
        self, identifier: str, rule: RateThrottleRule, storage: AsyncStorageBackend
    ) -> Tuple[bool, RateThrottleStatus]:
        from .core import RateThrottleStatus

        now = time.time()
        window_start = int(now / rule.window) * rule.window
        prev_window_start = window_start - rule.window

        current_key = f"swc:{rule.name}:{identifier}:{window_start}"
        prev_key = f"swc:{rule.name}:{identifier}:{prev_window_start}"

        current_count = await storage.get(current_key) or 0
        prev_count = await storage.get(prev_key) or 0

        elapsed_in_window = now - window_start
        window_progress = elapsed_in_window / rule.window

        weighted_count = math.ceil((prev_count * (1 - window_progress)) + current_count)

        if weighted_count < rule.limit:
            new_count = await storage.increment(current_key, 1, rule.window * 2)
            new_weighted = math.ceil((prev_count * (1 - window_progress)) + new_count)
            remaining = max(0, rule.limit - new_weighted)

            return True, RateThrottleStatus(
                allowed=True,
                remaining=remaining,
                limit=rule.limit,
                reset_time=window_start + rule.window,
                rule_name=rule.name,
            )
        else:
            retry_after = int(rule.window - elapsed_in_window) + 1

            return False, RateThrottleStatus(
                allowed=False,
                remaining=0,
                limit=rule.limit,
                reset_time=window_start + rule.window,
                retry_after=retry_after,
                rule_name=rule.name,
                blocked=True,
            )
