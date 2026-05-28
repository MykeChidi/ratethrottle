"""
Integration tests for async functionality
"""

import pytest
import asyncio
from ratethrottle import (
    AsyncRateThrottleCore,
    AsyncInMemoryStorage,
    RateThrottleRule,
)
from ratethrottle.helpers import create_async_limiter
from ratethrottle.async_middleware import AsyncFastAPIRateLimiter


class TestAsyncCreateLimiter:
    """Test create_async_limiter helper"""

    @pytest.mark.asyncio
    async def test_create_async_limiter_memory(self):
        """Test creating async limiter with memory storage"""
        limiter = await create_async_limiter("memory")
        assert limiter is not None
        assert isinstance(limiter, AsyncRateThrottleCore)
        await limiter.storage.shutdown()

    @pytest.mark.asyncio
    async def test_create_async_limiter_with_redis(self):
        """Test creating async limiter with Redis storage"""
        try:
            limiter = await create_async_limiter(
                "redis",
                "redis://localhost:6379/0"
            )
            # If successful, test basic functionality
            rule = RateThrottleRule(name="test", limit=10, window=60)
            limiter.add_rule(rule)
            status = await limiter.check_rate_limit("client1", "test")
            assert status is not None
            await limiter.storage.shutdown()
        except Exception as e:
            # Expected if Redis not running
            pytest.skip(f"Redis not available: {e}")

    @pytest.mark.asyncio
    async def test_create_async_limiter_invalid_storage(self):
        """Test creating async limiter with invalid storage type"""
        from ratethrottle.exceptions import ConfigurationError
        
        with pytest.raises(ConfigurationError):
            await create_async_limiter("invalid_storage")


class TestAsyncIntegration:
    """Integration tests for async components"""

    @pytest.mark.asyncio
    async def test_full_rate_limit_workflow(self):
        """Test complete rate limiting workflow"""
        # Create limiter
        storage = AsyncInMemoryStorage()
        limiter = AsyncRateThrottleCore(storage=storage)
        
        # Add rule
        rule = RateThrottleRule(
            name="api_limit",
            limit=5,
            window=60,
            strategy="fixed_window"
        )
        limiter.add_rule(rule)
        
        # Add to whitelist
        await limiter.add_to_whitelist("trusted_client", persistent=False)
        
        # Add to blacklist
        await limiter.add_to_blacklist("malicious_client", persistent=False)
        
        # Test whitelist (should bypass limit)
        status = await limiter.check_rate_limit("trusted_client", "api_limit")
        assert status.allowed
        assert status.remaining == 999999
        
        # Test blacklist (should be blocked)
        status = await limiter.check_rate_limit("malicious_client", "api_limit")
        assert not status.allowed
        assert status.blocked
        
        # Test normal requests
        for _ in range(5):
            status = await limiter.check_rate_limit("normal_client", "api_limit")
            assert status.allowed

        # 6th request should be blocked
        status = await limiter.check_rate_limit("normal_client", "api_limit")
        assert not status.allowed
        
        # Check metrics
        metrics = await limiter.get_metrics()
        assert metrics["total_requests"] > 0
        
        # Check status
        status = await limiter.get_status()
        assert len(status["rules"]) == 1
        
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_rules_per_client(self):
        """Test multiple rules for same client"""
        storage = AsyncInMemoryStorage()
        limiter = AsyncRateThrottleCore(storage=storage)
        
        # Add multiple rules
        rules = [
            RateThrottleRule(name="api", limit=100, window=60),
            RateThrottleRule(name="upload", limit=10, window=60),
            RateThrottleRule(name="download", limit=50, window=60),
        ]
        
        for rule in rules:
            limiter.add_rule(rule)
        
        # Test client against different rules
        client = "test_client"
        
        status_api = await limiter.check_rate_limit(client, "api")
        status_upload = await limiter.check_rate_limit(client, "upload")
        status_download = await limiter.check_rate_limit(client, "download")
        
        assert status_api.allowed
        assert status_upload.allowed
        assert status_download.allowed
        
        assert status_api.limit == 100
        assert status_upload.limit == 10
        assert status_download.limit == 50
        
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_concurrent_different_rules(self):
        """Test concurrent requests across different rules"""
        storage = AsyncInMemoryStorage()
        limiter = AsyncRateThrottleCore(storage=storage)
        
        # Add rules
        rules = [
            RateThrottleRule(name="rule_1", limit=10, window=60),
            RateThrottleRule(name="rule_2", limit=20, window=60),
        ]
        for rule in rules:
            limiter.add_rule(rule)
        
        # Create concurrent tasks
        async def make_requests():
            tasks = []
            for i in range(30):
                rule_name = f"rule_{i % 2 + 1}"
                client = f"client_{i % 5}"
                tasks.append(limiter.check_rate_limit(client, rule_name))
            return await asyncio.gather(*tasks)
        
        results = await make_requests()
        assert len(results) == 30
        
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_violation_callbacks_in_async(self):
        """Test violation callbacks work with async operations"""
        storage = AsyncInMemoryStorage()
        limiter = AsyncRateThrottleCore(storage=storage)
        
        violations = []
        
        def callback(violation):
            violations.append(violation)
        
        limiter.register_violation_callback(callback)
        
        rule = RateThrottleRule(name="test", limit=1, window=60)
        limiter.add_rule(rule)
        
        # Make requests to trigger violations
        await limiter.check_rate_limit("client_1", "test")
        await limiter.check_rate_limit("client_1", "test")
        await limiter.check_rate_limit("client_1", "test")
        
        assert len(violations) >= 2
        
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_async_middleware_integration(self):
        """Test async middleware with rate limiter"""
        storage = AsyncInMemoryStorage()
        middleware = AsyncFastAPIRateLimiter(storage=storage)
        
        # Add rules
        rule = RateThrottleRule(name="api", limit=5, window=60)
        middleware.add_rule(rule)
        
        # Add client to whitelist
        await middleware.add_to_whitelist("trusted_client")
        
        # Check metrics
        metrics = await middleware.get_metrics()
        assert "total_requests" in metrics
        
        # Get status
        status = await middleware.get_status()
        assert len(status["rules"]) == 1
        
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_rule_management_async(self):
        """Test rule management in async context"""
        limiter = AsyncRateThrottleCore()
        
        # Add rules
        rule1 = RateThrottleRule(name="rule1", limit=10, window=60)
        rule2 = RateThrottleRule(name="rule2", limit=20, window=60)
        
        limiter.add_rule(rule1)
        limiter.add_rule(rule2)
        
        # List rules
        rules = limiter.list_rules()
        assert set(rules) == {"rule1", "rule2"}
        
        # Get specific rule
        retrieved = limiter.get_rule("rule1")
        assert retrieved == rule1
        
        # Remove rule
        assert limiter.remove_rule("rule1")
        rules = limiter.list_rules()
        assert "rule1" not in rules
        
        await limiter.storage.shutdown()

    @pytest.mark.asyncio
    async def test_whitelist_blacklist_async(self):
        """Test whitelist/blacklist in async context"""
        limiter = AsyncRateThrottleCore()
        
        # Test whitelist
        await limiter.add_to_whitelist("white_1")
        await limiter.add_to_whitelist("white_2")
        assert await limiter.is_whitelisted("white_1")
        assert await limiter.is_whitelisted("white_2")
        
        # Test blacklist
        await limiter.add_to_blacklist("black_1")
        await limiter.add_to_blacklist("black_2")
        assert await limiter.is_blacklisted("black_1")
        assert await limiter.is_blacklisted("black_2")
        
        # Remove from whitelist
        assert await limiter.remove_from_whitelist("white_1")
        assert not await limiter.is_whitelisted("white_1")
        
        # Remove from blacklist
        assert await limiter.remove_from_blacklist("black_1")
        assert not await limiter.is_blacklisted("black_1")
        
        await limiter.storage.shutdown()

    @pytest.mark.asyncio
    async def test_metrics_and_status_async(self):
        """Test metrics and status retrieval in async context"""
        limiter = AsyncRateThrottleCore()
        
        rule = RateThrottleRule(name="test", limit=100, window=60)
        limiter.add_rule(rule)
        
        # Make some requests
        for i in range(5):
            await limiter.check_rate_limit(f"client_{i}", "test")
        
        # Get metrics
        metrics = await limiter.get_metrics()
        assert metrics["total_requests"] == 5
        assert metrics["allowed_requests"] == 5
        assert "block_rate" in metrics
        
        # Reset metrics
        await limiter.reset_metrics()
        metrics = await limiter.get_metrics()
        assert metrics["total_requests"] == 0
        
        # Get status
        status = await limiter.get_status()
        assert len(status["rules"]) == 1
        assert status["whitelisted_count"] == 0
        assert status["blacklisted_count"] == 0
        
        await limiter.storage.shutdown()


class TestAsyncErrorHandling:
    """Test error handling in async operations"""

    @pytest.mark.asyncio
    async def test_invalid_rule_async(self):
        """Test invalid rule handling in async context"""
        from ratethrottle.exceptions import InvalidRuleError
        
        limiter = AsyncRateThrottleCore()
        
        invalid_rule_params = [
            {"name": "", "limit": 10, "window": 60},  # Empty name
            {"name": "rule", "limit": 0, "window": 60},  # Invalid limit
            {"name": "rule", "limit": 10, "window": 0},  # Invalid window
        ]

        for params in invalid_rule_params:
            with pytest.raises(InvalidRuleError):
                invalid_rule = RateThrottleRule(**params)
                limiter.add_rule(invalid_rule)
        
        await limiter.storage.shutdown()

    @pytest.mark.asyncio
    async def test_unknown_strategy_async(self):
        """Test unknown strategy handling"""
        from ratethrottle.exceptions import StrategyNotFoundError
        
        limiter = AsyncRateThrottleCore()
        
        with pytest.raises(StrategyNotFoundError):
            rule = RateThrottleRule(
                name="test",
                limit=10,
                window=60,
                strategy="unknown_strategy"
            )
            limiter.add_rule(rule)
        
        await limiter.storage.shutdown()
