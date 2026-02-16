"""
RateThrottle - Core Rate Limiting Engine

Production-grade rate limiting with comprehensive error handling,
validation, and monitoring capabilities.
"""

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Type

from .exceptions import (
    InvalidRuleError,
    RuleNotFoundError,
    StorageError,
    StrategyNotFoundError,
)
from .storage_backend import InMemoryStorage, StorageBackend
from .strategies import (
    FixedWindowStrategy,
    LeakyBucketStrategy,
    RateLimitStrategy,
    SlidingWindowStrategy,
    TokenBucketStrategy,
)

logger = logging.getLogger(__name__)


@dataclass
class RateThrottleRule:
    """
    Defines a rate limiting rule with validation

    Args:
        name: Unique identifier for the rule
        limit: Maximum number of requests allowed
        window: Time window in seconds
        scope: Scope of rate limiting ('ip', 'user', 'endpoint', 'global')
        block_duration: Duration to block after limit exceeded (seconds)
        strategy: Rate limiting strategy name
        burst: Maximum burst allowance (for token bucket)

    Raises:
        InvalidRuleError: If rule parameters are invalid

    Examples:
        >>> rule = RateThrottleRule(
        ...     name='api_limit',
        ...     limit=100,
        ...     window=60,
        ...     strategy='sliding_window'
        ... )
    """

    name: str
    limit: int
    window: int
    scope: str = "ip"
    block_duration: int = 300
    strategy: str = "sliding_window"
    burst: Optional[int] = None

    def __post_init__(self):
        """Validate rule parameters"""
        if self.burst is None:
            self.burst = self.limit

        # Validation
        if not self.name or not isinstance(self.name, str):
            raise InvalidRuleError("Rule name must be a non-empty string")

        if self.limit <= 0:
            raise InvalidRuleError(f"Limit must be positive, got {self.limit}")

        if self.window <= 0:
            raise InvalidRuleError(f"Window must be positive, got {self.window}")

        if self.block_duration < 0:
            raise InvalidRuleError(f"Block duration cannot be negative, got {self.block_duration}")

        if self.burst < self.limit:
            raise InvalidRuleError(f"Burst ({self.burst}) cannot be less than limit ({self.limit})")

        valid_scopes = {"ip", "user", "endpoint", "global"}
        if self.scope not in valid_scopes:
            raise InvalidRuleError(
                f"Invalid scope '{self.scope}'. Valid options: {', '.join(valid_scopes)}"
            )

        logger.debug(f"Created rule: {self.name} ({self.limit}/{self.window}s)")


@dataclass
class RateThrottleViolation:
    """
    Records a rate limit violation with detailed context

    Attributes:
        identifier: Client identifier that violated the limit
        rule_name: Name of the violated rule
        timestamp: ISO 8601 timestamp of violation
        requests_made: Number of requests that triggered violation
        limit: The rate limit that was exceeded
        blocked_until: ISO 8601 timestamp when block expires
        retry_after: Seconds until client can retry
        scope: Scope of the rate limit
        metadata: Additional context information
    """

    identifier: str
    rule_name: str
    timestamp: str
    requests_made: int
    limit: int
    blocked_until: Optional[str]
    retry_after: int
    scope: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert violation to dictionary"""
        return asdict(self)


@dataclass
class RateThrottleStatus:
    """
    Current status of rate limiting for a request

    Attributes:
        allowed: Whether the request is allowed
        remaining: Number of requests remaining in window
        limit: Total request limit
        reset_time: Unix timestamp when limit resets
        retry_after: Seconds to wait before retrying (if blocked)
        rule_name: Name of the rule that was applied
        blocked: Whether the client is currently blocked
    """

    allowed: bool
    remaining: int
    limit: int
    reset_time: int
    retry_after: Optional[int] = None
    rule_name: Optional[str] = None
    blocked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert status to dictionary for JSON responses"""
        return {
            "allowed": self.allowed,
            "remaining": self.remaining,
            "limit": self.limit,
            "reset_time": self.reset_time,
            "retry_after": self.retry_after,
            "rule_name": self.rule_name,
            "blocked": self.blocked,
        }

    def to_headers(self) -> Dict[str, str]:
        """Convert status to HTTP headers"""
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_time),
        }

        if self.retry_after is not None:
            headers["Retry-After"] = str(self.retry_after)

        return headers


class RateThrottleCore:
    """
    Core rate limiting engine with production-grade features

    Features:
        - Multiple rate limiting strategies
        - Whitelist/blacklist management
        - Violation callbacks and monitoring
        - Thread-safe operations
        - Comprehensive metrics tracking
        - Graceful error handling

    Examples:
        >>> from ratethrottle import RateThrottleCore, RateThrottleRule
        >>> limiter = RateThrottleCore()
        >>> rule = RateThrottleRule(name='api', limit=100, window=60)
        >>> limiter.add_rule(rule)
        >>> status = limiter.check_rate_limit('192.168.1.1', 'api')
        >>> if status.allowed:
        ...     # Process request
        ...     pass
    """

    STRATEGIES: Dict[str, Type[RateLimitStrategy]] = {
        "token_bucket": TokenBucketStrategy,
        "leaky_bucket": LeakyBucketStrategy,
        "fixed_window": FixedWindowStrategy,
        "sliding_window": SlidingWindowStrategy,
    }

    def __init__(self, storage: Optional[StorageBackend] = None):
        """
        Initialize rate throttle engine

        Args:
            storage: Storage backend for rate limit data (default: in-memory)
        """
        self.storage = storage or InMemoryStorage()
        self.rules: Dict[str, RateThrottleRule] = {}
        self.strategies: Dict[str, RateLimitStrategy] = {
            name: cls() for name, cls in self.STRATEGIES.items()
        }
        self.whitelist: Set[str] = set()
        self.blacklist: Set[str] = set()
        self.violation_callbacks: List[Callable[[RateThrottleViolation], None]] = []
        self.metrics: Dict[str, Any] = {
            "total_requests": 0,
            "allowed_requests": 0,
            "blocked_requests": 0,
            "violations": [],
        }
        self._lock = threading.RLock()

        logger.info("RateThrottleCore initialized")

    def add_rule(self, rule: RateThrottleRule) -> None:
        """
        Add a rate limiting rule

        Args:
            rule: Rate throttle rule to add

        Raises:
            InvalidRuleError: If rule is invalid
            StrategyNotFoundError: If strategy doesn't exist

        Examples:
            >>> rule = RateThrottleRule(name='api', limit=100, window=60)
            >>> limiter.add_rule(rule)
        """
        if not isinstance(rule, RateThrottleRule):
            raise InvalidRuleError(f"Expected RateThrottleRule, got {type(rule).__name__}")

        if rule.strategy not in self.STRATEGIES:
            raise StrategyNotFoundError(
                f"Strategy '{rule.strategy}' not found. "
                f"Available: {', '.join(self.STRATEGIES.keys())}"
            )

        with self._lock:
            self.rules[rule.name] = rule
            logger.info(
                f"Added rule '{rule.name}': {rule.limit} requests per {rule.window}s "
                f"using {rule.strategy} strategy"
            )

    def remove_rule(self, rule_name: str) -> bool:
        """
        Remove a rate limiting rule

        Args:
            rule_name: Name of the rule to remove

        Returns:
            True if rule was removed, False if not found

        Examples:
            >>> limiter.remove_rule('api')
            True
        """
        with self._lock:
            if rule_name in self.rules:
                del self.rules[rule_name]
                logger.info(f"Removed rule: {rule_name}")
                return True
            logger.warning(f"Attempted to remove non-existent rule: {rule_name}")
            return False

    def get_rule(self, rule_name: str) -> Optional[RateThrottleRule]:
        """
        Get a rule by name

        Args:
            rule_name: Name of the rule

        Returns:
            The rule if found, None otherwise
        """
        return self.rules.get(rule_name)

    def list_rules(self) -> List[str]:
        """
        List all rule names

        Returns:
            List of rule names
        """
        return list(self.rules.keys())

    def add_to_whitelist(self, identifier: str) -> None:
        """
        Add identifier to whitelist (bypasses all limits)

        Args:
            identifier: Client identifier to whitelist

        Examples:
            >>> limiter.add_to_whitelist('192.168.1.100')
        """
        if not identifier:
            logger.warning("Attempted to whitelist empty identifier")
            return

        with self._lock:
            self.whitelist.add(identifier)
            logger.info(f"Added to whitelist: {identifier}")

    def remove_from_whitelist(self, identifier: str) -> bool:
        """
        Remove identifier from whitelist

        Args:
            identifier: Client identifier to remove

        Returns:
            True if removed, False if not in whitelist
        """
        with self._lock:
            if identifier in self.whitelist:
                self.whitelist.discard(identifier)
                logger.info(f"Removed from whitelist: {identifier}")
                return True
            return False

    def is_whitelisted(self, identifier: str) -> bool:
        """Check if identifier is whitelisted"""
        return identifier in self.whitelist

    def add_to_blacklist(self, identifier: str, duration: Optional[int] = None) -> None:
        """
        Add identifier to blacklist (blocks all requests)

        Args:
            identifier: Client identifier to blacklist
            duration: Optional duration in seconds (permanent if None)

        Examples:
            >>> # Permanent blacklist
            >>> limiter.add_to_blacklist('192.168.1.200')
            >>>
            >>> # Temporary blacklist (1 hour)
            >>> limiter.add_to_blacklist('192.168.1.201', duration=3600)
        """
        if not identifier:
            logger.warning("Attempted to blacklist empty identifier")
            return

        with self._lock:
            self.blacklist.add(identifier)
            if duration:
                try:
                    self.storage.set(f"blacklist:{identifier}", True, duration)
                    logger.warning(f"Added to blacklist for {duration}s: {identifier}")
                except Exception as e:
                    logger.error(f"Failed to set blacklist TTL: {e}")
            else:
                logger.warning(f"Added to permanent blacklist: {identifier}")

    def remove_from_blacklist(self, identifier: str) -> bool:
        """
        Remove identifier from blacklist

        Args:
            identifier: Client identifier to remove

        Returns:
            True if removed, False if not in blacklist
        """
        with self._lock:
            was_blacklisted = identifier in self.blacklist
            if was_blacklisted:
                self.blacklist.discard(identifier)
                try:
                    self.storage.delete(f"blacklist:{identifier}")
                except Exception as e:
                    logger.error(f"Failed to delete blacklist entry: {e}")
                logger.info(f"Removed from blacklist: {identifier}")
            return was_blacklisted

    def is_blacklisted(self, identifier: str) -> bool:
        """Check if identifier is blacklisted"""
        if identifier in self.blacklist:
            return True
        try:
            return self.storage.exists(f"blacklist:{identifier}")
        except Exception as e:
            logger.error(f"Failed to check blacklist: {e}")
            return False

    def register_violation_callback(
        self, callback: Callable[[RateThrottleViolation], None]
    ) -> None:
        """
        Register callback for rate limit violations

        Args:
            callback: Function to call when violation occurs

        Examples:
            >>> def log_violation(violation):
            ...     print(f"Violation: {violation.identifier}")
            >>> limiter.register_violation_callback(log_violation)
        """
        if not callable(callback):
            raise ValueError("Callback must be callable")
        self.violation_callbacks.append(callback)
        logger.debug(f"Registered violation callback: {callback.__name__}")

    def check_rate_limit(
        self, identifier: str, rule_name: str, metadata: Optional[Dict[str, Any]] = None
    ) -> RateThrottleStatus:
        """
        Check if request is allowed under specified rule

        Args:
            identifier: Client identifier (IP, user ID, etc.)
            rule_name: Name of the rule to apply
            metadata: Optional metadata for logging/callbacks

        Returns:
            RateThrottleStatus indicating if request is allowed

        Raises:
            RuleNotFoundError: If rule doesn't exist
            StorageError: If storage backend fails

        Examples:
            >>> status = limiter.check_rate_limit('192.168.1.1', 'api')
            >>> if status.allowed:
            ...     # Process request
            ...     print(f"{status.remaining} requests remaining")
            ... else:
            ...     print(f"Rate limit exceeded. Retry after {status.retry_after}s")
        """
        if not identifier:
            logger.warning("Empty identifier provided to check_rate_limit")
            identifier = "unknown"

        with self._lock:
            self.metrics["total_requests"] += 1

            # Check whitelist
            if identifier in self.whitelist:
                self.metrics["allowed_requests"] += 1
                logger.debug(f"Allowed (whitelisted): {identifier}")
                return RateThrottleStatus(
                    allowed=True,
                    remaining=999999,
                    limit=999999,
                    reset_time=int(time.time() + 3600),
                    rule_name="whitelist",
                )

            # Check blacklist
            if self.is_blacklisted(identifier):
                self.metrics["blocked_requests"] += 1
                logger.debug(f"Blocked (blacklisted): {identifier}")
                return RateThrottleStatus(
                    allowed=False,
                    remaining=0,
                    limit=0,
                    reset_time=int(time.time() + 86400),
                    retry_after=86400,
                    rule_name="blacklist",
                    blocked=True,
                )

            # Get rule
            if rule_name not in self.rules:
                logger.error(f"Rule not found: {rule_name}")
                raise RuleNotFoundError(
                    f"Rule '{rule_name}' not found. "
                    f"Available rules: {', '.join(self.rules.keys())}"
                )

            rule = self.rules[rule_name]

            # Check if currently blocked
            block_key = f"blocked:{rule_name}:{identifier}"

            try:
                if self.storage.exists(block_key):
                    block_until = self.storage.get(block_key)
                    # Check if block has expired
                    if block_until is not None and isinstance(block_until, (int, float)):
                        if block_until <= time.time():
                            # Block has expired, remove it
                            self.storage.delete(block_key)
                            logger.info(f"Block expired: {identifier}")
                        else:
                            # Still blocked
                            retry_after = max(1, int(block_until - time.time()))
                            self.metrics["blocked_requests"] += 1
                            logger.debug(
                                f"Blocked (rate limit): {identifier} for rule {rule_name}, "
                                f"retry after {retry_after}s"
                            )

                            return RateThrottleStatus(
                                allowed=False,
                                remaining=0,
                                limit=rule.limit,
                                reset_time=int(block_until),
                                retry_after=retry_after,
                                rule_name=rule_name,
                                blocked=True,
                            )
            except Exception as e:
                logger.error(f"Storage error checking block status: {e}")
                raise StorageError(f"Failed to check block status: {e}") from e

            # Apply rate limiting strategy
            strategy = self.strategies.get(rule.strategy)
            if not strategy:
                logger.error(f"Strategy not found: {rule.strategy}")
                raise StrategyNotFoundError(f"Strategy '{rule.strategy}' not found")

            try:
                allowed, status = strategy.is_allowed(identifier, rule, self.storage)
            except Exception as e:
                logger.error(f"Strategy error: {e}")
                raise StorageError(f"Rate limiting strategy failed: {e}") from e

            if allowed:
                self.metrics["allowed_requests"] += 1
                logger.debug(
                    f"Allowed: {identifier} for rule {rule_name}, " f"{status.remaining} remaining"
                )
            else:
                self.metrics["blocked_requests"] += 1
                logger.info(f"Rate limit exceeded: {identifier} for rule {rule_name}")

                # Block for configured duration
                if rule.block_duration > 0:
                    block_until = time.time() + rule.block_duration
                    try:
                        self.storage.set(block_key, int(block_until), rule.block_duration)
                    except Exception as e:
                        logger.error(f"Failed to set block: {e}")

                # Record violation
                violation = RateThrottleViolation(
                    identifier=identifier,
                    rule_name=rule_name,
                    timestamp=datetime.now().isoformat(),
                    requests_made=rule.limit,
                    limit=rule.limit,
                    blocked_until=(
                        datetime.fromtimestamp(time.time() + rule.block_duration).isoformat()
                        if rule.block_duration > 0
                        else None
                    ),
                    retry_after=status.retry_after or rule.block_duration,
                    scope=rule.scope,
                    metadata=metadata or {},
                )

                self.metrics["violations"].append(violation)

                # Trigger callbacks
                for callback in self.violation_callbacks:
                    try:
                        callback(violation)
                    except Exception as e:
                        logger.error(f"Violation callback error ({callback.__name__}): {e}")

            return status

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current metrics

        Returns:
            Dictionary containing rate limiting metrics

        Examples:
            >>> metrics = limiter.get_metrics()
            >>> print(f"Block rate: {metrics['block_rate']:.2f}%")
        """
        with self._lock:
            total = self.metrics["total_requests"]
            return {
                "total_requests": total,
                "allowed_requests": self.metrics["allowed_requests"],
                "blocked_requests": self.metrics["blocked_requests"],
                "block_rate": (
                    (self.metrics["blocked_requests"] / total * 100) if total > 0 else 0
                ),
                "total_violations": len(self.metrics["violations"]),
                "recent_violations": self.metrics["violations"][-10:],
                "active_rules": len(self.rules),
                "whitelisted_count": len(self.whitelist),
                "blacklisted_count": len(self.blacklist),
            }

    def reset_metrics(self) -> None:
        """
        Reset all metrics

        Examples:
            >>> limiter.reset_metrics()
        """
        with self._lock:
            self.metrics = {
                "total_requests": 0,
                "allowed_requests": 0,
                "blocked_requests": 0,
                "violations": [],
            }
            logger.info("Metrics reset")

    def get_status(self) -> Dict[str, Any]:
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
            "callbacks_registered": len(self.violation_callbacks),
            "storage_type": type(self.storage).__name__,
            "strategies_available": list(self.STRATEGIES.keys()),
        }

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"RateThrottleCore(rules={len(self.rules)}, "
            f"whitelist={len(self.whitelist)}, "
            f"blacklist={len(self.blacklist)})"
        )
