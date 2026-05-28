"""
RateThrottle - Async Core Engine

Asyncio-compatible rate limiting engine that handles rule evaluation,
distributed lists, failover, and metrics without blocking the event loop.
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Type

from .async_storage import AsyncInMemoryStorage, AsyncStorageBackend
from .async_strategies import (
    AsyncFixedWindowStrategy,
    AsyncLeakyBucketStrategy,
    AsyncRateLimitStrategy,
    AsyncSlidingWindowCounterStrategy,
    AsyncSlidingWindowStrategy,
    AsyncTokenBucketStrategy,
)
from .core import RateThrottleRule, RateThrottleStatus, RateThrottleViolation
from .exceptions import InvalidRuleError, StrategyNotFoundError
from .failover import FailoverHandler, FailureMode

logger = logging.getLogger(__name__)


class AsyncRateThrottleCore:
    """
    Core engine for async rate limiting.
    Handles rule management, strategy execution, and storage coordination.
    """

    STRATEGIES: Dict[str, Type["AsyncRateLimitStrategy"]] = {
        "fixed_window": AsyncFixedWindowStrategy,
        "sliding_window": AsyncSlidingWindowStrategy,
        "token_bucket": AsyncTokenBucketStrategy,
        "leaky_bucket": AsyncLeakyBucketStrategy,
        "sliding_counter": AsyncSlidingWindowCounterStrategy,
    }

    def __init__(
        self,
        storage: Optional[AsyncStorageBackend] = None,
        use_distributed_lists: bool = True,
        failure_mode: FailureMode = FailureMode.STRICT,
        failover_handler: Optional[FailoverHandler] = None,
    ):
        """
        Initialize async rate throttle engine
        """
        self.storage = storage or AsyncInMemoryStorage()
        self.use_distributed_lists = use_distributed_lists and not isinstance(
            self.storage, AsyncInMemoryStorage
        )

        self.failover_handler = failover_handler or FailoverHandler(failure_mode=failure_mode)

        self.rules: Dict[str, RateThrottleRule] = {}
        self.strategies: Dict[str, AsyncRateLimitStrategy] = {
            name: cls() for name, cls in self.STRATEGIES.items()
        }

        # Local caches for performance
        self.whitelist: Set[str] = set()
        self.blacklist: Set[str] = set()
        self._list_cache_time = 0
        self._list_cache_ttl = 60  # Refresh cache every 60s

        self.violation_callbacks: List[Callable[[RateThrottleViolation], None]] = []
        self.metrics: Dict[str, Any] = {
            "total_requests": 0,
            "allowed_requests": 0,
            "blocked_requests": 0,
            "violations": deque(maxlen=1000),
        }
        self._lock = asyncio.Lock()

        logger.info(
            f"AsyncRateThrottleCore initialized (distributed_lists={self.use_distributed_lists})"
        )

    def add_rule(self, rule: RateThrottleRule) -> None:
        """Add or update a rate limiting rule"""
        if not rule.name or rule.limit <= 0 or rule.window <= 0:
            raise InvalidRuleError("Invalid rule parameters")

        if rule.strategy not in self.strategies:
            raise StrategyNotFoundError(f"Unknown strategy: {rule.strategy}")

        self.rules[rule.name] = rule
        logger.info(f"Added async rule: {rule.name} ({rule.limit}/{rule.window}s, {rule.strategy})")

    def register_strategy(self, name: str, strategy: AsyncRateLimitStrategy) -> None:
        """Register a custom async strategy"""
        if not isinstance(strategy, AsyncRateLimitStrategy):
            raise TypeError("Strategy must inherit from AsyncRateLimitStrategy")
        self.strategies[name] = strategy
        logger.info(f"Registered custom async strategy: {name}")

    def get_rule(self, name: str) -> Optional[RateThrottleRule]:
        return self.rules.get(name)

    async def _sync_lists_from_storage(self) -> None:
        """Sync whitelist and blacklist from distributed storage"""
        if not self.use_distributed_lists:
            return

        now = time.time()
        if now - self._list_cache_time < self._list_cache_ttl:
            return

        try:
            # Need to scan keys with prefix in async storage
            # Assuming AsyncStorageBackend doesn't have a direct 'keys' method but we can
            # implement a basic refresh or leave this to rely on individual checks.
            # For performance, we skip full sync and rely on individual 'is_whitelisted' checks
            # that hit cache first, then storage.
            pass
        except Exception as e:
            logger.error(f"Failed to sync lists from storage: {e}")

    async def add_to_whitelist(self, identifier: str, persistent: bool = True) -> None:
        if not identifier:
            return

        async with self._lock:
            self.whitelist.add(identifier)

            if persistent and self.use_distributed_lists:
                try:
                    await self.storage.set(f"whitelist:{identifier}", "1", ttl=2592000)
                except Exception as e:
                    logger.error(f"Failed to persist whitelist entry: {e}")

    async def remove_from_whitelist(self, identifier: str) -> bool:
        async with self._lock:
            was_whitelisted = identifier in self.whitelist
            if was_whitelisted:
                self.whitelist.discard(identifier)

                if self.use_distributed_lists:
                    try:
                        await self.storage.delete(f"whitelist:{identifier}")
                    except Exception as e:
                        logger.error(f"Failed to remove persisted whitelist entry: {e}")
            return was_whitelisted

    async def is_whitelisted(self, identifier: str) -> bool:
        if identifier in self.whitelist:
            return True

        if self.use_distributed_lists:
            try:
                if await self.storage.exists(f"whitelist:{identifier}"):
                    async with self._lock:
                        self.whitelist.add(identifier)
                    return True
            except Exception:
                pass

        return False

    async def add_to_blacklist(
        self, identifier: str, duration: Optional[int] = None, persistent: bool = True
    ) -> None:
        if not identifier:
            return

        async with self._lock:
            self.blacklist.add(identifier)

            if persistent:
                try:
                    if self.use_distributed_lists:
                        if duration:
                            await self.storage.set(
                                f"blacklist:{identifier}",
                                str(int(time.time() + duration)),
                                ttl=duration,
                            )
                        else:
                            await self.storage.set(
                                f"blacklist:{identifier}", "permanent", ttl=2592000
                            )
                except Exception as e:
                    logger.error(f"Failed to persist blacklist entry: {e}")

    async def remove_from_blacklist(self, identifier: str) -> bool:
        async with self._lock:
            was_blacklisted = identifier in self.blacklist
            if was_blacklisted:
                self.blacklist.discard(identifier)

                if self.use_distributed_lists:
                    try:
                        await self.storage.delete(f"blacklist:{identifier}")
                    except Exception as e:
                        logger.error(f"Failed to remove persisted blacklist entry: {e}")
            return was_blacklisted

    async def is_blacklisted(self, identifier: str) -> bool:
        if identifier in self.blacklist:
            return True

        if self.use_distributed_lists:
            try:
                if await self.storage.exists(f"blacklist:{identifier}"):
                    async with self._lock:
                        self.blacklist.add(identifier)
                    return True
            except Exception:
                pass

        return False

    def register_violation_callback(
        self, callback: Callable[[RateThrottleViolation], None]
    ) -> None:
        if not callable(callback):
            raise ValueError("Callback must be callable")
        self.violation_callbacks.append(callback)

    def _trigger_violation_callbacks(self, violation: RateThrottleViolation) -> None:
        for callback in self.violation_callbacks:
            try:
                callback(violation)
            except Exception as e:
                logger.error(f"Violation callback error: {e}")

    async def _record_violation(
        self,
        identifier: str,
        rule: RateThrottleRule,
        rule_name: str,
        retry_after: int,
        blocked_until: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        violation = RateThrottleViolation(
            identifier=identifier,
            rule_name=rule_name,
            timestamp=datetime.now().isoformat(),
            requests_made=rule.limit,
            limit=rule.limit,
            blocked_until=blocked_until,
            retry_after=retry_after,
            scope=rule.scope,
            metadata=metadata or {},
        )
        async with self._lock:
            self.metrics["violations"].append(violation)
        self._trigger_violation_callbacks(violation)

    async def check_rate_limit(
        self, identifier: str, rule_name: str, metadata: Optional[Dict] = None
    ) -> RateThrottleStatus:
        if not identifier:
            return RateThrottleStatus(
                allowed=False,
                remaining=0,
                limit=0,
                reset_time=int(time.time()),
                rule_name="error",
                blocked=True,
            )

        async with self._lock:
            self.metrics["total_requests"] += 1

        if await self.is_whitelisted(identifier):
            async with self._lock:
                self.metrics["allowed_requests"] += 1
            return RateThrottleStatus(
                allowed=True,
                remaining=float("inf"),
                limit=float("inf"),
                reset_time=int(time.time() + 3600),
                rule_name="whitelist",
            )

        if await self.is_blacklisted(identifier):
            async with self._lock:
                self.metrics["blocked_requests"] += 1
            return RateThrottleStatus(
                allowed=False,
                remaining=0,
                limit=0,
                reset_time=int(time.time() + 3600),
                rule_name="blacklist",
                blocked=True,
            )

        async with self._lock:
            if rule_name not in self.rules:
                logger.warning(f"Rule not found: {rule_name}")
                self.metrics["blocked_requests"] += 1
                return RateThrottleStatus(
                    allowed=False,
                    remaining=0,
                    limit=0,
                    reset_time=int(time.time()),
                    rule_name="unknown_rule",
                    blocked=True,
                )
            rule = self.rules[rule_name]

        block_key = f"blocked:{rule_name}:{identifier}"

        try:
            if hasattr(self.storage, "check_and_delete_if_expired"):
                exists, block_until = await self.storage.check_and_delete_if_expired(block_key)
                if exists and block_until is not None:
                    retry_after = max(1, int(float(block_until) - time.time()))
                    async with self._lock:
                        self.metrics["blocked_requests"] += 1
                    await self._record_violation(
                        identifier,
                        rule,
                        rule_name,
                        retry_after,
                        blocked_until=datetime.fromtimestamp(float(block_until)).isoformat(),
                        metadata=metadata,
                    )
                    return RateThrottleStatus(
                        allowed=False,
                        remaining=0,
                        limit=rule.limit,
                        reset_time=int(float(block_until)),
                        retry_after=retry_after,
                        rule_name=rule_name,
                        blocked=True,
                    )
            else:
                block_until = await self.storage.get(block_key)
                if block_until is not None:
                    retry_after = max(1, int(float(block_until) - time.time()))
                    async with self._lock:
                        self.metrics["blocked_requests"] += 1
                    await self._record_violation(
                        identifier,
                        rule,
                        rule_name,
                        retry_after,
                        blocked_until=datetime.fromtimestamp(float(block_until)).isoformat(),
                        metadata=metadata,
                    )
                    return RateThrottleStatus(
                        allowed=False,
                        remaining=0,
                        limit=rule.limit,
                        reset_time=int(float(block_until)),
                        retry_after=retry_after,
                        rule_name=rule_name,
                        blocked=True,
                    )
        except Exception as e:
            logger.error(f"Storage error checking block status: {e}")
            self.failover_handler.record_failure()
            if not self.failover_handler.should_allow():
                return RateThrottleStatus(
                    allowed=False,
                    remaining=0,
                    limit=0,
                    reset_time=int(time.time()),
                    rule_name="error",
                    blocked=True,
                )

        strategy = self.strategies.get(rule.strategy)
        if not strategy:
            logger.error(f"Strategy not found: {rule.strategy}")
            return RateThrottleStatus(
                allowed=False,
                remaining=0,
                limit=0,
                reset_time=int(time.time()),
                rule_name="strategy_error",
                blocked=True,
            )

        try:
            allowed, status = await strategy.is_allowed(identifier, rule, self.storage)
            self.failover_handler.record_success()
        except Exception as e:
            logger.error(f"Strategy error: {e}")
            self.failover_handler.record_failure()
            if not self.failover_handler.should_allow():
                return RateThrottleStatus(
                    allowed=False,
                    remaining=0,
                    limit=0,
                    reset_time=int(time.time()),
                    rule_name="storage_error",
                    blocked=True,
                )
            else:
                allowed, status = True, RateThrottleStatus(
                    allowed=True,
                    remaining=1,
                    limit=rule.limit,
                    reset_time=int(time.time()),
                    rule_name=rule.name,
                )

        if allowed:
            async with self._lock:
                self.metrics["allowed_requests"] += 1
        else:
            async with self._lock:
                self.metrics["blocked_requests"] += 1

            if rule.block_duration:
                try:
                    block_until = time.time() + rule.block_duration
                    await self.storage.set(block_key, str(block_until), ttl=rule.block_duration)
                    status.retry_after = rule.block_duration
                    status.reset_time = int(block_until)
                    logger.info(
                        f"Applied penalty block for {rule.block_duration}s to {identifier}"
                    )
                except Exception as e:
                    logger.error(f"Failed to set penalty block: {e}")

            await self._record_violation(
                identifier,
                rule,
                rule_name,
                status.retry_after or rule.block_duration,
                blocked_until=(
                    datetime.fromtimestamp(status.reset_time).isoformat()
                    if status.reset_time
                    else None
                ),
                metadata=metadata,
            )

        return status

    def remove_rule(self, rule_name: str) -> bool:
        """
        Remove a rate limiting rule

        Args:
            rule_name: Name of the rule to remove

        Returns:
            True if rule was removed, False if not found
        """
        if rule_name in self.rules:
            del self.rules[rule_name]
            logger.info(f"Removed async rule: {rule_name}")
            return True
        logger.warning(f"Attempted to remove non-existent async rule: {rule_name}")
        return False

    def list_rules(self) -> List[str]:
        """
        List all rule names

        Returns:
            List of rule names
        """
        return list(self.rules.keys())

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get current metrics

        Returns:
            Dictionary containing rate limiting metrics
        """
        async with self._lock:
            total = self.metrics["total_requests"]
            return {
                "total_requests": total,
                "allowed_requests": self.metrics["allowed_requests"],
                "blocked_requests": self.metrics["blocked_requests"],
                "block_rate": (
                    (self.metrics["blocked_requests"] / total * 100) if total > 0 else 0
                ),
                "total_violations": len(self.metrics["violations"]),
                "recent_violations": list(self.metrics["violations"])[-10:],
                "active_rules": len(self.rules),
                "whitelisted_count": len(self.whitelist),
                "blacklisted_count": len(self.blacklist),
            }

    async def reset_metrics(self) -> None:
        """Reset all metrics"""
        async with self._lock:
            self.metrics = {
                "total_requests": 0,
                "allowed_requests": 0,
                "blocked_requests": 0,
                "violations": deque(maxlen=1000),
            }
            logger.info("Async metrics reset")

    async def get_status(self) -> Dict[str, Any]:
        """
        Get system status

        Returns:
            Dictionary with system status information
        """
        return {
            "rules": [
                {
                    "name": rule.name,
                    "limit": rule.limit,
                    "window": rule.window,
                    "strategy": rule.strategy,
                }
                for rule in self.rules.values()
            ],
            "whitelist_size": len(self.whitelist),
            "blacklist_size": len(self.blacklist),
            "whitelisted_count": len(self.whitelist),
            "blacklisted_count": len(self.blacklist),
            "callbacks_registered": len(self.violation_callbacks),
            "storage_type": type(self.storage).__name__,
            "strategies_available": list(self.STRATEGIES.keys()),
        }

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"AsyncRateThrottleCore(rules={len(self.rules)}, "
            f"whitelist={len(self.whitelist)}, "
            f"blacklist={len(self.blacklist)})"
        )
