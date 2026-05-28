"""
Tests for async rate limiting strategies
"""

import pytest
import asyncio
import time
from ratethrottle.async_core import AsyncRateThrottleCore
from ratethrottle.core import RateThrottleRule
from ratethrottle.async_storage import AsyncInMemoryStorage


@pytest.fixture
async def async_limiter():
    """Create an async rate limiter"""
    storage = AsyncInMemoryStorage()
    limiter = AsyncRateThrottleCore(storage=storage)
    yield limiter
    await storage.shutdown()


class TestAsyncFixedWindowStrategy:
    """Test async fixed window strategy"""

    @pytest.mark.asyncio
    async def test_fixed_window_basic(self, async_limiter):
        """Test basic fixed window behavior"""
        rule = RateThrottleRule(
            name="fw_rule",
            limit=5,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)

        identifier = "client_1"

        # Make 5 allowed requests
        for i in range(5):
            status = await async_limiter.check_rate_limit(identifier, "fw_rule")
            assert status.allowed
            assert status.remaining == 5 - i - 1

    @pytest.mark.asyncio
    async def test_fixed_window_limit_exceeded(self, async_limiter):
        """Test fixed window when limit is exceeded"""
        rule = RateThrottleRule(
            name="fw_rule",
            limit=2,
            window=10,  # Short window for testing
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        
        identifier = "client_1"
        
        # First two should pass
        status1 = await async_limiter.check_rate_limit(identifier, "fw_rule")
        assert status1.allowed
        
        status2 = await async_limiter.check_rate_limit(identifier, "fw_rule")
        assert status2.allowed
        
        # Third should fail
        status3 = await async_limiter.check_rate_limit(identifier, "fw_rule")
        assert not status3.allowed
        assert status3.remaining == 0

    @pytest.mark.asyncio
    async def test_fixed_window_reset(self, async_limiter):
        """Test fixed window reset after window expires"""
        rule = RateThrottleRule(
            name="fw_rule",
            limit=2,
            window=1,  # 1 second window
            block_duration=0,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        
        identifier = "client_1"
        
        # Exhaust limit
        for _ in range(2):
            await async_limiter.check_rate_limit(identifier, "fw_rule")
        
        # Should be blocked
        status = await async_limiter.check_rate_limit(identifier, "fw_rule")
        assert not status.allowed
        
        # Wait for window to reset
        await asyncio.sleep(1.1)
        
        # Should be allowed again
        status = await async_limiter.check_rate_limit(identifier, "fw_rule")
        assert status.allowed


class TestAsyncSlidingWindowStrategy:
    """Test async sliding window strategy"""

    @pytest.mark.asyncio
    async def test_sliding_window_basic(self, async_limiter):
        """Test basic sliding window behavior"""
        rule = RateThrottleRule(
            name="sw_rule",
            limit=5,
            window=60,
            strategy="sliding_window",
        )
        async_limiter.add_rule(rule)

        identifier = "client_1"

        # Make requests
        for i in range(5):
            status = await async_limiter.check_rate_limit(identifier, "sw_rule")
            assert status.allowed
            assert status.remaining == 5 - i - 1

    @pytest.mark.asyncio
    async def test_sliding_window_limit_exceeded(self, async_limiter):
        """Test sliding window when limit is exceeded"""
        rule = RateThrottleRule(
            name="sw_rule",
            limit=2,
            window=10,
            strategy="sliding_window",
        )
        async_limiter.add_rule(rule)
        
        identifier = "client_1"
        
        # Make two requests
        await async_limiter.check_rate_limit(identifier, "sw_rule")
        await async_limiter.check_rate_limit(identifier, "sw_rule")
        
        # Third should be blocked
        status = await async_limiter.check_rate_limit(identifier, "sw_rule")
        assert not status.allowed


class TestAsyncTokenBucketStrategy:
    """Test async token bucket strategy"""

    @pytest.mark.asyncio
    async def test_token_bucket_basic(self, async_limiter):
        """Test basic token bucket behavior"""
        rule = RateThrottleRule(
            name="tb_rule",
            limit=5,
            window=60,
            strategy="token_bucket",
            burst=10,
        )
        async_limiter.add_rule(rule)
        
        # Should allow burst
        for i in range(10):
            status = await async_limiter.check_rate_limit(f"client_{i}", "tb_rule")
            assert status.allowed

    @pytest.mark.asyncio
    async def test_token_bucket_refill(self, async_limiter):
        """Test token bucket refill rate"""
        rule = RateThrottleRule(
            name="tb_rule",
            limit=10,
            window=1,  # 10 tokens per 1 second = 10 tokens/sec
            block_duration=0,
            strategy="token_bucket",
            burst=10,
        )
        async_limiter.add_rule(rule)
        
        identifier = "client_1"
        
        # Use all tokens
        for _ in range(10):
            status = await async_limiter.check_rate_limit(identifier, "tb_rule")
            assert status.allowed
        
        # Should be blocked (no tokens)
        status = await async_limiter.check_rate_limit(identifier, "tb_rule")
        assert not status.allowed
        
        # Wait for refill
        await asyncio.sleep(1.1)
        
        # Should be allowed again
        status = await async_limiter.check_rate_limit(identifier, "tb_rule")
        assert status.allowed


class TestAsyncLeakyBucketStrategy:
    """Test async leaky bucket strategy"""

    @pytest.mark.asyncio
    async def test_leaky_bucket_basic(self, async_limiter):
        """Test basic leaky bucket behavior"""
        rule = RateThrottleRule(
            name="lb_rule",
            limit=5,
            window=60,
            strategy="leaky_bucket",
        )
        async_limiter.add_rule(rule)
        
        # Make requests
        for i in range(5):
            status = await async_limiter.check_rate_limit(f"client_{i}", "lb_rule")
            assert status.allowed

    @pytest.mark.asyncio
    async def test_leaky_bucket_limit_exceeded(self, async_limiter):
        """Test leaky bucket when limit is exceeded"""
        rule = RateThrottleRule(
            name="lb_rule",
            limit=2,
            window=60,
            strategy="leaky_bucket",
        )
        async_limiter.add_rule(rule)
        
        identifier = "client_1"
        
        # Make two requests
        await async_limiter.check_rate_limit(identifier, "lb_rule")
        await async_limiter.check_rate_limit(identifier, "lb_rule")
        
        # Third should be blocked
        status = await async_limiter.check_rate_limit(identifier, "lb_rule")
        assert not status.allowed


class TestAsyncSlidingWindowCounterStrategy:
    """Test async sliding window counter strategy"""

    @pytest.mark.asyncio
    async def test_sliding_window_counter_basic(self, async_limiter):
        """Test basic sliding window counter behavior"""
        rule = RateThrottleRule(
            name="swc_rule",
            limit=5,
            window=60,
            strategy="sliding_counter",
        )
        async_limiter.add_rule(rule)
        
        # Make requests
        for i in range(5):
            status = await async_limiter.check_rate_limit(f"client_{i}", "swc_rule")
            assert status.allowed

    @pytest.mark.asyncio
    async def test_sliding_window_counter_limit_exceeded(self, async_limiter):
        """Test sliding window counter when limit is exceeded"""
        rule = RateThrottleRule(
            name="swc_rule",
            limit=2,
            window=60,
            strategy="sliding_counter",
        )
        async_limiter.add_rule(rule)
        
        identifier = "client_1"
        
        # Make two requests
        await async_limiter.check_rate_limit(identifier, "swc_rule")
        await async_limiter.check_rate_limit(identifier, "swc_rule")
        
        # Third should be blocked
        status = await async_limiter.check_rate_limit(identifier, "swc_rule")
        assert not status.allowed


class TestAsyncStrategyComparison:
    """Compare different strategies"""

    @pytest.mark.asyncio
    async def test_different_strategies_same_limit(self, async_limiter):
        """Test different strategies with same limit"""
        strategies = ["fixed_window", "sliding_window", "token_bucket", "leaky_bucket", "sliding_counter"]
        
        for strategy in strategies:
            rule = RateThrottleRule(
                name=f"{strategy}_rule",
                limit=5,
                window=60,
                strategy=strategy,
                burst=5 if strategy == "token_bucket" else None,
            )
            async_limiter.add_rule(rule)
            
            identifier = f"client_{strategy}"
            
            # All should allow first 5 requests
            for i in range(5):
                status = await async_limiter.check_rate_limit(identifier, f"{strategy}_rule")
                assert status.allowed, f"Strategy {strategy} failed on request {i}"
            
            # All should block 6th request
            status = await async_limiter.check_rate_limit(identifier, f"{strategy}_rule")
            assert not status.allowed, f"Strategy {strategy} should block 6th request"


class TestAsyncStrategyPerformance:
    """Test strategy performance under load"""

    @pytest.mark.asyncio
    async def test_high_concurrency_fixed_window(self, async_limiter):
        """Test fixed window strategy under high concurrency"""
        rule = RateThrottleRule(
            name="fw_rule",
            limit=100,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        
        # Create 1000 concurrent requests from different clients
        tasks = [
            async_limiter.check_rate_limit(f"client_{i % 50}", "fw_rule")
            for i in range(1000)
        ]
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 1000
        allowed_count = sum(1 for r in results if r.allowed)
        assert allowed_count > 0  # Some should be allowed

    @pytest.mark.asyncio
    async def test_high_concurrency_token_bucket(self, async_limiter):
        """Test token bucket strategy under high concurrency"""
        rule = RateThrottleRule(
            name="tb_rule",
            limit=100,
            window=60,
            strategy="token_bucket",
            burst=200,
        )
        async_limiter.add_rule(rule)
        
        # Create concurrent requests
        tasks = [
            async_limiter.check_rate_limit(f"client_{i % 50}", "tb_rule")
            for i in range(1000)
        ]
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 1000


class TestAsyncStatusResponse:
    """Test status response details from strategies"""

    @pytest.mark.asyncio
    async def test_status_response_allowed(self, async_limiter):
        """Test status response when allowed"""
        rule = RateThrottleRule(
            name="test_rule",
            limit=10,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        
        status = await async_limiter.check_rate_limit("client_1", "test_rule")
        
        assert status.allowed
        assert status.remaining < 10
        assert status.limit == 10
        assert status.reset_time > 0
        assert status.retry_after is None or status.retry_after == 0
        assert not status.blocked

    @pytest.mark.asyncio
    async def test_status_response_blocked(self, async_limiter):
        """Test status response when blocked"""
        rule = RateThrottleRule(
            name="test_rule",
            limit=1,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        
        await async_limiter.check_rate_limit("client_1", "test_rule")
        status = await async_limiter.check_rate_limit("client_1", "test_rule")
        
        assert not status.allowed
        assert status.remaining == 0
        assert status.limit == 1
        assert status.reset_time > 0
        assert status.retry_after is not None and status.retry_after > 0
        assert status.blocked

    @pytest.mark.asyncio
    async def test_status_to_dict(self, async_limiter):
        """Test converting status to dict"""
        rule = RateThrottleRule(
            name="test_rule",
            limit=10,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        
        status = await async_limiter.check_rate_limit("client_1", "test_rule")
        status_dict = status.to_dict()
        
        assert "allowed" in status_dict
        assert "remaining" in status_dict
        assert "limit" in status_dict
        assert "reset_time" in status_dict

    @pytest.mark.asyncio
    async def test_status_to_headers(self, async_limiter):
        """Test converting status to HTTP headers"""
        rule = RateThrottleRule(
            name="test_rule",
            limit=10,
            window=60,
            strategy="fixed_window",
        )
        async_limiter.add_rule(rule)
        
        status = await async_limiter.check_rate_limit("client_1", "test_rule")
        headers = status.to_headers()
        
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers
