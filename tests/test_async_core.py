"""
Tests for AsyncRateThrottleCore async functionality
"""

import asyncio
import pytest
import time
from datetime import datetime

from ratethrottle.async_core import AsyncRateThrottleCore
from ratethrottle.core import RateThrottleRule, RateThrottleStatus
from ratethrottle.async_storage import AsyncInMemoryStorage, AsyncRedisStorage
from ratethrottle.exceptions import InvalidRuleError, StrategyNotFoundError


@pytest.fixture
async def async_limiter():
    """Create an async rate limiter instance"""
    storage = AsyncInMemoryStorage()
    limiter = AsyncRateThrottleCore(storage=storage)
    yield limiter
    await storage.shutdown()


@pytest.fixture
async def basic_rule():
    """Create a basic rule"""
    return RateThrottleRule(
        name="test_rule",
        limit=10,
        window=60,
        strategy="fixed_window",
    )


class TestAsyncRateThrottleCoreInitialization:
    """Test AsyncRateThrottleCore initialization"""

    @pytest.mark.asyncio
    async def test_init_with_default_storage(self):
        """Test initialization with default storage"""
        limiter = AsyncRateThrottleCore()
        assert limiter.storage is not None
        assert limiter.rules == {}
        assert len(limiter.strategies) == 5  # 5 built-in strategies
        await limiter.storage.shutdown()

    @pytest.mark.asyncio
    async def test_init_with_custom_storage(self):
        """Test initialization with custom storage"""
        storage = AsyncInMemoryStorage()
        limiter = AsyncRateThrottleCore(storage=storage)
        assert limiter.storage is storage
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_strategies_registered(self):
        """Test that all strategies are registered"""
        limiter = AsyncRateThrottleCore()
        expected_strategies = {
            "fixed_window",
            "sliding_window",
            "token_bucket",
            "leaky_bucket",
            "sliding_counter",
        }
        assert set(limiter.strategies.keys()) == expected_strategies
        await limiter.storage.shutdown()


class TestAsyncRuleManagement:
    """Test async rule management"""

    @pytest.mark.asyncio
    async def test_add_rule(self, async_limiter, basic_rule):
        """Test adding a rule"""
        async_limiter.add_rule(basic_rule)
        assert "test_rule" in async_limiter.rules
        assert async_limiter.rules["test_rule"] == basic_rule

    @pytest.mark.asyncio
    async def test_add_invalid_rule(self, async_limiter):
        """Test adding invalid rule raises exception"""
        with pytest.raises(InvalidRuleError):
            invalid_rule = RateThrottleRule(
                name="",  # Invalid: empty name
                limit=10,
                window=60,
            )
            async_limiter.add_rule(invalid_rule)

    @pytest.mark.asyncio
    async def test_get_rule(self, async_limiter, basic_rule):
        """Test getting a rule"""
        async_limiter.add_rule(basic_rule)
        retrieved_rule = async_limiter.get_rule("test_rule")
        assert retrieved_rule == basic_rule

    @pytest.mark.asyncio
    async def test_get_nonexistent_rule(self, async_limiter):
        """Test getting a nonexistent rule returns None"""
        retrieved_rule = async_limiter.get_rule("nonexistent")
        assert retrieved_rule is None

    @pytest.mark.asyncio
    async def test_remove_rule(self, async_limiter, basic_rule):
        """Test removing a rule"""
        async_limiter.add_rule(basic_rule)
        assert async_limiter.remove_rule("test_rule")
        assert "test_rule" not in async_limiter.rules

    @pytest.mark.asyncio
    async def test_remove_nonexistent_rule(self, async_limiter):
        """Test removing nonexistent rule returns False"""
        assert not async_limiter.remove_rule("nonexistent")

    @pytest.mark.asyncio
    async def test_list_rules(self, async_limiter):
        """Test listing rules"""
        rule1 = RateThrottleRule(name="rule1", limit=10, window=60)
        rule2 = RateThrottleRule(name="rule2", limit=20, window=60)
        async_limiter.add_rule(rule1)
        async_limiter.add_rule(rule2)
        rules = async_limiter.list_rules()
        assert set(rules) == {"rule1", "rule2"}


class TestAsyncWhitelistBlacklist:
    """Test async whitelist and blacklist management"""

    @pytest.mark.asyncio
    async def test_add_to_whitelist(self, async_limiter):
        """Test adding to whitelist"""
        identifier = "192.168.1.100"
        await async_limiter.add_to_whitelist(identifier, persistent=False)
        assert await async_limiter.is_whitelisted(identifier)

    @pytest.mark.asyncio
    async def test_remove_from_whitelist(self, async_limiter):
        """Test removing from whitelist"""
        identifier = "192.168.1.100"
        await async_limiter.add_to_whitelist(identifier, persistent=False)
        assert await async_limiter.remove_from_whitelist(identifier)
        assert not await async_limiter.is_whitelisted(identifier)

    @pytest.mark.asyncio
    async def test_add_to_blacklist(self, async_limiter):
        """Test adding to blacklist"""
        identifier = "192.168.1.200"
        await async_limiter.add_to_blacklist(identifier, persistent=False)
        assert await async_limiter.is_blacklisted(identifier)

    @pytest.mark.asyncio
    async def test_remove_from_blacklist(self, async_limiter):
        """Test removing from blacklist"""
        identifier = "192.168.1.200"
        await async_limiter.add_to_blacklist(identifier, persistent=False)
        assert await async_limiter.remove_from_blacklist(identifier)
        assert not await async_limiter.is_blacklisted(identifier)

    @pytest.mark.asyncio
    async def test_add_empty_identifier_to_whitelist(self, async_limiter):
        """Test adding empty identifier is ignored"""
        await async_limiter.add_to_whitelist("", persistent=False)
        assert "" not in async_limiter.whitelist

    @pytest.mark.asyncio
    async def test_add_empty_identifier_to_blacklist(self, async_limiter):
        """Test adding empty identifier is ignored"""
        await async_limiter.add_to_blacklist("", persistent=False)
        assert "" not in async_limiter.blacklist


class TestAsyncRateLimitCheck:
    """Test async rate limit checking"""

    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed(self, async_limiter):
        """Test allowed request"""
        rule = RateThrottleRule(
            name="test_rule",
            limit=10,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        status = await async_limiter.check_rate_limit("192.168.1.100", "test_rule")
        assert status.allowed
        assert status.remaining >= 0

    @pytest.mark.asyncio
    async def test_check_rate_limit_blocked(self, async_limiter):
        """Test blocked request after limit exceeded"""
        rule = RateThrottleRule(
            name="test_rule",
            limit=2,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        identifier = "192.168.1.100"
        
        # First two requests should be allowed
        status1 = await async_limiter.check_rate_limit(identifier, "test_rule")
        assert status1.allowed
        
        status2 = await async_limiter.check_rate_limit(identifier, "test_rule")
        assert status2.allowed
        
        # Third request should be blocked
        status3 = await async_limiter.check_rate_limit(identifier, "test_rule")
        assert not status3.allowed
        assert status3.blocked

    @pytest.mark.asyncio
    async def test_check_rate_limit_whitelisted(self, async_limiter):
        """Test whitelisted identifier bypasses limit"""
        rule = RateThrottleRule(
            name="test_rule",
            limit=1,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        identifier = "192.168.1.100"
        
        await async_limiter.add_to_whitelist(identifier, persistent=False)
        
        # Both requests should be allowed (whitelisted)
        status1 = await async_limiter.check_rate_limit(identifier, "test_rule")
        assert status1.allowed
        
        status2 = await async_limiter.check_rate_limit(identifier, "test_rule")
        assert status2.allowed  # Whitelisted

    @pytest.mark.asyncio
    async def test_check_rate_limit_blacklisted(self, async_limiter):
        """Test blacklisted identifier is always blocked"""
        rule = RateThrottleRule(
            name="test_rule",
            limit=100,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        identifier = "192.168.1.100"
        
        await async_limiter.add_to_blacklist(identifier, persistent=False)
        
        status = await async_limiter.check_rate_limit(identifier, "test_rule")
        assert not status.allowed
        assert status.blocked

    @pytest.mark.asyncio
    async def test_check_rate_limit_empty_identifier(self, async_limiter):
        """Test empty identifier is rejected"""
        rule = RateThrottleRule(name="test_rule", limit=10, window=60)
        async_limiter.add_rule(rule)
        
        status = await async_limiter.check_rate_limit("", "test_rule")
        assert not status.allowed
        assert status.blocked

    @pytest.mark.asyncio
    async def test_check_rate_limit_unknown_rule(self, async_limiter):
        """Test unknown rule returns blocked status"""
        status = await async_limiter.check_rate_limit("192.168.1.100", "unknown_rule")
        assert not status.allowed
        assert status.blocked
        assert status.rule_name == "unknown_rule"

    @pytest.mark.asyncio
    async def test_check_rate_limit_with_metadata(self, async_limiter, basic_rule):
        """Test rate limit check with metadata"""
        async_limiter.add_rule(basic_rule)
        metadata = {"path": "/api/endpoint", "method": "GET"}
        status = await async_limiter.check_rate_limit(
            "192.168.1.100", "test_rule", metadata=metadata
        )
        assert status.allowed


class TestAsyncMetrics:
    """Test async metrics collection"""

    @pytest.mark.asyncio
    async def test_get_metrics(self, async_limiter, basic_rule):
        """Test getting metrics"""
        async_limiter.add_rule(basic_rule)
        
        # Make some requests
        await async_limiter.check_rate_limit("192.168.1.100", "test_rule")
        await async_limiter.check_rate_limit("192.168.1.100", "test_rule")
        
        metrics = await async_limiter.get_metrics()
        assert metrics["total_requests"] == 2
        assert metrics["allowed_requests"] == 2
        assert metrics["blocked_requests"] == 0
        assert "block_rate" in metrics

    @pytest.mark.asyncio
    async def test_reset_metrics(self, async_limiter, basic_rule):
        """Test resetting metrics"""
        async_limiter.add_rule(basic_rule)
        
        await async_limiter.check_rate_limit("192.168.1.100", "test_rule")
        metrics_before = await async_limiter.get_metrics()
        assert metrics_before["total_requests"] == 1
        
        await async_limiter.reset_metrics()
        metrics_after = await async_limiter.get_metrics()
        assert metrics_after["total_requests"] == 0

    @pytest.mark.asyncio
    async def test_get_status(self, async_limiter, basic_rule):
        """Test getting system status"""
        async_limiter.add_rule(basic_rule)
        
        status = await async_limiter.get_status()
        assert "rules" in status
        assert len(status["rules"]) == 1
        assert status["rules"][0]["name"] == "test_rule"
        assert "strategies_available" in status


class TestAsyncViolationCallbacks:
    """Test async violation callbacks"""

    @pytest.mark.asyncio
    async def test_register_violation_callback(self, async_limiter):
        """Test registering violation callback"""
        callback_called = []
        
        def violation_callback(violation):
            callback_called.append(violation)
        
        async_limiter.register_violation_callback(violation_callback)
        
        rule = RateThrottleRule(name="test_rule", limit=1, window=60)
        async_limiter.add_rule(rule)
        
        # Trigger violation
        await async_limiter.check_rate_limit("192.168.1.100", "test_rule")
        await async_limiter.check_rate_limit("192.168.1.100", "test_rule")
        
        assert len(callback_called) == 1
        assert callback_called[0].identifier == "192.168.1.100"


class TestAsyncStrategies:
    """Test different async rate limiting strategies"""

    @pytest.mark.asyncio
    async def test_token_bucket_strategy(self, async_limiter):
        """Test token bucket strategy"""
        rule = RateThrottleRule(
            name="token_rule",
            limit=5,
            window=60,
            strategy="token_bucket",
            burst=10,
        )
        async_limiter.add_rule(rule)
        
        status = await async_limiter.check_rate_limit("192.168.1.100", "token_rule")
        assert status.allowed
        assert status.strategy == "token_bucket" or status.rule_name == "token_rule"

    @pytest.mark.asyncio
    async def test_sliding_window_strategy(self, async_limiter):
        """Test sliding window strategy"""
        rule = RateThrottleRule(
            name="sw_rule",
            limit=5,
            window=60,
            strategy="sliding_window",
        )
        async_limiter.add_rule(rule)
        
        status = await async_limiter.check_rate_limit("192.168.1.100", "sw_rule")
        assert status.allowed

    @pytest.mark.asyncio
    async def test_leaky_bucket_strategy(self, async_limiter):
        """Test leaky bucket strategy"""
        rule = RateThrottleRule(
            name="lb_rule",
            limit=5,
            window=60,
            strategy="leaky_bucket",
        )
        async_limiter.add_rule(rule)
        
        status = await async_limiter.check_rate_limit("192.168.1.100", "lb_rule")
        assert status.allowed

    @pytest.mark.asyncio
    async def test_sliding_counter_strategy(self, async_limiter):
        """Test sliding counter strategy"""
        rule = RateThrottleRule(
            name="sc_rule",
            limit=5,
            window=60,
            strategy="sliding_counter",
        )
        async_limiter.add_rule(rule)
        
        status = await async_limiter.check_rate_limit("192.168.1.100", "sc_rule")
        assert status.allowed


class TestAsyncConcurrency:
    """Test async concurrent operations"""

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, async_limiter):
        """Test handling concurrent requests"""
        rule = RateThrottleRule(
            name="concurrent_rule",
            limit=10,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        
        # Create 20 concurrent requests
        tasks = [
            async_limiter.check_rate_limit(
                f"192.168.1.{i % 256}",
                "concurrent_rule"
            )
            for i in range(20)
        ]
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 20
        assert all(isinstance(r, RateThrottleStatus) for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_whitelist_operations(self, async_limiter):
        """Test concurrent whitelist operations"""
        tasks = [
            async_limiter.add_to_whitelist(f"192.168.1.{i}", persistent=False)
            for i in range(10)
        ]
        
        await asyncio.gather(*tasks)
        
        # Verify all were added
        for i in range(10):
            assert await async_limiter.is_whitelisted(f"192.168.1.{i}")

    @pytest.mark.asyncio
    async def test_concurrent_rule_management(self, async_limiter):
        """Test concurrent rule management"""
        rules = [
            RateThrottleRule(
                name=f"rule_{i}",
                limit=10,
                window=60,
                strategy="fixed_window",
            )
            for i in range(10)
        ]
        
        # Add rules (synchronous but test concurrent access)
        for rule in rules:
            async_limiter.add_rule(rule)
        
        # Check concurrent access
        tasks = [
            async_limiter.check_rate_limit(f"192.168.1.{i}", f"rule_{i % 10}")
            for i in range(20)
        ]
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 20


class TestAsyncRepr:
    """Test async limiter representation"""

    @pytest.mark.asyncio
    async def test_repr(self, async_limiter, basic_rule):
        """Test string representation"""
        async_limiter.add_rule(basic_rule)
        repr_str = repr(async_limiter)
        assert "AsyncRateThrottleCore" in repr_str
        assert "rules=1" in repr_str
