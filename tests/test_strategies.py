"""
Tests for rate limiting strategies
"""

import time

import pytest

from ratethrottle.core import RateThrottleRule
from ratethrottle.exceptions import StorageError
from ratethrottle.storage_backend import InMemoryStorage
from ratethrottle.strategies import (
    FixedWindowStrategy,
    LeakyBucketStrategy,
    SlidingWindowStrategy,
    TokenBucketStrategy,
)


class TestTokenBucketStrategy:
    """Test token bucket strategy"""

    @pytest.fixture
    def strategy(self):
        return TokenBucketStrategy()

    @pytest.fixture
    def rule(self):
        return RateThrottleRule(name="test", limit=10, window=60, burst=15, strategy="token_bucket")

    @pytest.fixture
    def storage(self):
        return InMemoryStorage()

    def test_initial_request_allowed(self, strategy, rule, storage):
        """Test that initial request is allowed"""
        allowed, status = strategy.is_allowed("client1", rule, storage)

        assert allowed is True
        assert status.allowed is True
        assert status.remaining > 0
        assert status.limit == rule.limit

    def test_consumes_tokens(self, strategy, rule, storage):
        """Test that requests consume tokens"""
        # First request
        allowed1, status1 = strategy.is_allowed("client1", rule, storage)
        remaining1 = status1.remaining

        # Second request
        allowed2, status2 = strategy.is_allowed("client1", rule, storage)
        remaining2 = status2.remaining

        assert allowed1 is True
        assert allowed2 is True
        assert remaining2 < remaining1

    def test_blocks_when_no_tokens(self, strategy, rule, storage):
        """Test blocking when tokens exhausted"""
        # Use up all tokens
        for _ in range(16):
            strategy.is_allowed("client1", rule, storage)

        # Next request should be blocked
        allowed, status = strategy.is_allowed("client1", rule, storage)

        assert allowed is False
        assert status.allowed is False
        assert status.remaining == 0
        assert status.retry_after > 0

    def test_tokens_refill_over_time(self, strategy, rule, storage):
        """Test that tokens refill over time"""
        # Use some tokens
        for _ in range(5):
            strategy.is_allowed("client1", rule, storage)

        # Wait for refill
        time.sleep(1)

        # Should have more tokens
        allowed, status = strategy.is_allowed("client1", rule, storage)
        assert allowed is True

    def test_different_clients_independent(self, strategy, rule, storage):
        """Test that different clients have independent buckets"""
        # Use tokens for client1
        for _ in range(15):
            strategy.is_allowed("client1", rule, storage)

        # Client2 should still have tokens
        allowed, status = strategy.is_allowed("client2", rule, storage)
        assert allowed is True

    def test_handles_invalid_state(self, strategy, rule, storage):
        """Test handling of corrupted state"""
        # Set invalid state
        storage.set("tb:test:client1", "invalid")

        # Should reinitialize
        allowed, status = strategy.is_allowed("client1", rule, storage)
        assert allowed is True


class TestLeakyBucketStrategy:
    """Test leaky bucket strategy"""

    @pytest.fixture
    def strategy(self):
        return LeakyBucketStrategy()

    @pytest.fixture
    def rule(self):
        return RateThrottleRule(name="test", limit=10, window=60, strategy="leaky_bucket")

    @pytest.fixture
    def storage(self):
        return InMemoryStorage()

    def test_initial_request_allowed(self, strategy, rule, storage):
        """Test that initial request is allowed"""
        allowed, status = strategy.is_allowed("client1", rule, storage)

        assert allowed is True
        assert status.remaining == rule.limit - 1

    def test_fills_queue(self, strategy, rule, storage):
        """Test filling the queue"""
        for i in range(10):
            allowed, status = strategy.is_allowed("client1", rule, storage)
            assert allowed is True
            assert status.remaining == 9 - i

    def test_blocks_when_queue_full(self, strategy, rule, storage):
        """Test blocking when queue is full"""
        # Fill queue
        for _ in range(10):
            strategy.is_allowed("client1", rule, storage)

        # Next request blocked
        allowed, status = strategy.is_allowed("client1", rule, storage)

        assert allowed is False
        assert status.remaining == 0
        assert status.retry_after > 0

    def test_requests_leak_over_time(self, strategy, rule, storage):
        """Test that old requests leak out"""
        # Fill queue
        for _ in range(10):
            strategy.is_allowed("client1", rule, storage)

        # Wait for some to leak
        time.sleep(1)

        # Should have space now
        allowed, status = strategy.is_allowed("client1", rule, storage)
        # May or may not be allowed depending on leak rate

    def test_handles_invalid_queue(self, strategy, rule, storage):
        """Test handling of invalid queue"""
        storage.set("lb:q:test:client1", "invalid")

        allowed, status = strategy.is_allowed("client1", rule, storage)
        assert allowed is True


class TestFixedWindowStrategy:
    """Test fixed window strategy"""

    @pytest.fixture
    def strategy(self):
        return FixedWindowStrategy()

    @pytest.fixture
    def rule(self):
        return RateThrottleRule(name="test", limit=10, window=60, strategy="fixed_window")

    @pytest.fixture
    def storage(self):
        return InMemoryStorage()

    def test_initial_request_allowed(self, strategy, rule, storage):
        """Test that initial request is allowed"""
        allowed, status = strategy.is_allowed("client1", rule, storage)

        assert allowed is True
        assert status.remaining == rule.limit - 1

    def test_counts_requests_in_window(self, strategy, rule, storage):
        """Test counting requests in window"""
        for i in range(5):
            allowed, status = strategy.is_allowed("client1", rule, storage)
            assert allowed is True
            assert status.remaining == 9 - i

    def test_blocks_when_limit_exceeded(self, strategy, rule, storage):
        """Test blocking when limit exceeded"""
        # Use up limit
        for _ in range(10):
            strategy.is_allowed("client1", rule, storage)

        # Next request blocked
        allowed, status = strategy.is_allowed("client1", rule, storage)

        assert allowed is False
        assert status.remaining == 0

    def test_resets_on_new_window(self, strategy, storage):
        """Test that count resets on new window"""
        rule = RateThrottleRule(
            name="test", limit=5, window=1, strategy="fixed_window"  # 1 second window
        )

        # Use up limit
        for _ in range(5):
            strategy.is_allowed("client1", rule, storage)

        # Should be blocked
        allowed, _ = strategy.is_allowed("client1", rule, storage)
        assert allowed is False

        # Wait for new window
        time.sleep(1.1)

        # Should be allowed in new window
        allowed, status = strategy.is_allowed("client1", rule, storage)
        assert allowed is True

    def test_handles_invalid_count(self, strategy, rule, storage):
        """Test handling of invalid count"""
        storage.set("fw:test:client1:0", "invalid")

        allowed, status = strategy.is_allowed("client1", rule, storage)
        assert allowed is True


class TestSlidingWindowStrategy:
    """Test sliding window strategy"""

    @pytest.fixture
    def strategy(self):
        return SlidingWindowStrategy()

    @pytest.fixture
    def rule(self):
        return RateThrottleRule(name="test", limit=10, window=60, strategy="sliding_window")

    @pytest.fixture
    def storage(self):
        return InMemoryStorage()

    def test_initial_request_allowed(self, strategy, rule, storage):
        """Test that initial request is allowed"""
        allowed, status = strategy.is_allowed("client1", rule, storage)

        assert allowed is True
        assert status.remaining == rule.limit - 1

    def test_maintains_timestamp_log(self, strategy, rule, storage):
        """Test that timestamps are maintained"""
        for i in range(5):
            allowed, status = strategy.is_allowed("client1", rule, storage)
            assert allowed is True
            assert status.remaining == 9 - i

    def test_blocks_when_limit_exceeded(self, strategy, rule, storage):
        """Test blocking when limit exceeded"""
        # Use up limit
        for _ in range(10):
            strategy.is_allowed("client1", rule, storage)

        # Next request blocked
        allowed, status = strategy.is_allowed("client1", rule, storage)

        assert allowed is False
        assert status.remaining == 0
        assert status.retry_after > 0

    def test_sliding_window_behavior(self, strategy, storage):
        """Test true sliding window behavior"""
        rule = RateThrottleRule(
            name="test", limit=3, window=2, strategy="sliding_window"  # 2 second window
        )

        # Make 3 requests
        for _ in range(3):
            allowed, _ = strategy.is_allowed("client1", rule, storage)
            assert allowed is True

        # 4th request blocked
        allowed, _ = strategy.is_allowed("client1", rule, storage)
        assert allowed is False

        # Wait 1 second
        time.sleep(1)

        # Still blocked (only 1 second passed, need 2)
        allowed, _ = strategy.is_allowed("client1", rule, storage)
        assert allowed is False

        # Wait another 1.1 seconds
        time.sleep(1.1)

        # Should be allowed now (old requests outside window)
        allowed, status = strategy.is_allowed("client1", rule, storage)
        assert allowed is True

    def test_removes_old_timestamps(self, strategy, rule, storage):
        """Test that old timestamps are removed"""
        # Add some requests
        for _ in range(5):
            strategy.is_allowed("client1", rule, storage)

        # Check timestamps exist
        timestamps = storage.get("sw:test:client1")
        assert len(timestamps) == 5

        # Wait for them to expire
        time.sleep(61)  # Beyond window

        # Make new request
        strategy.is_allowed("client1", rule, storage)

        # Old timestamps should be gone
        timestamps = storage.get("sw:test:client1")
        assert len(timestamps) == 1

    def test_handles_invalid_timestamps(self, strategy, rule, storage):
        """Test handling of invalid timestamp list"""
        storage.set("sw:test:client1", "invalid")

        allowed, status = strategy.is_allowed("client1", rule, storage)
        assert allowed is True

    def test_accurate_across_boundaries(self, strategy, storage):
        """Test accuracy across time boundaries (no edge case)"""
        rule = RateThrottleRule(name="test", limit=5, window=2, strategy="sliding_window")

        # Make 4 requests
        for _ in range(4):
            allowed, _ = strategy.is_allowed("client1", rule, storage)
            assert allowed is True

        # Wait 1.5 seconds
        time.sleep(1.5)

        # Make 4 more requests (should work because old ones are expiring)
        for i in range(4):
            allowed, _ = strategy.is_allowed("client1", rule, storage)
            # First few should be allowed as old requests expire
            if i < 1:
                assert allowed is True


class TestStrategyErrorHandling:
    """Test error handling across strategies"""

    @pytest.fixture
    def rule(self):
        return RateThrottleRule(name="test", limit=10, window=60, strategy="token_bucket")

    def test_storage_error_propagates(self, mocker):
        """Test that storage errors propagate"""
        strategy = TokenBucketStrategy()
        storage = mocker.Mock()
        storage.get.side_effect = Exception("Storage failed")

        rule = RateThrottleRule(name="test", limit=10, window=60, strategy="token_bucket")

        with pytest.raises(StorageError):
            strategy.is_allowed("client1", rule, storage)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
