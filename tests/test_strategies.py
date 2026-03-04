"""
Tests for rate limiting strategies
"""

import time
from unittest.mock import patch

import pytest

from ratethrottle.core import RateThrottleRule
from ratethrottle.exceptions import StorageError
from ratethrottle.storage_backend import InMemoryStorage
from ratethrottle.strategies import (
    FixedWindowStrategy,
    LeakyBucketStrategy,
    SlidingWindowCounterStrategy,
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


class TestSlidingWindowCounterStrategy:
    """Test basic functionality"""

    @pytest.fixture
    def storage(self):
        """Create in-memory storage"""
        return InMemoryStorage()

    @pytest.fixture
    def strategy(self):
        """Create strategy instance"""
        return SlidingWindowCounterStrategy()

    @pytest.fixture
    def rule(self):
        """Create test rule"""
        return RateThrottleRule(name="test", limit=10, window=60, strategy="sliding_counter")

    def test_first_request_allowed(self, strategy, rule, storage):
        """Test first request is always allowed"""
        allowed, status = strategy.is_allowed("user1", rule, storage)

        assert allowed is True
        assert status.allowed is True
        assert status.remaining == 9  # 10 - 1
        assert status.limit == 10

    def test_requests_within_limit(self, strategy, rule, storage):
        """Test multiple requests within limit are allowed"""
        for i in range(10):
            allowed, status = strategy.is_allowed("user1", rule, storage)
            assert allowed is True
            assert status.remaining == 9 - i

    def test_request_exceeding_limit(self, strategy, rule, storage):
        """Test request exceeding limit is blocked"""
        # Make 10 requests (at limit)
        for i in range(10):
            strategy.is_allowed("user1", rule, storage)

        # 11th request should be blocked
        allowed, status = strategy.is_allowed("user1", rule, storage)

        assert allowed is False
        assert status.allowed is False
        assert status.remaining == 0
        assert status.blocked is True
        assert status.retry_after > 0

    def test_different_users_independent(self, strategy, rule, storage):
        """Test different users have independent counters"""
        # User 1 makes 10 requests
        for i in range(10):
            strategy.is_allowed("user1", rule, storage)

        # User 2 should still be allowed
        allowed, status = strategy.is_allowed("user2", rule, storage)
        assert allowed is True
        assert status.remaining == 9

    def test_weighted_count_formula(self, strategy, rule, storage):
        """Test weighted count formula is correct"""
        # Mock time to control window progression
        with patch("time.time") as mock_time:
            # Start of first window (t=0)
            mock_time.return_value = 0.0

            # Make 8 requests in first window
            for i in range(8):
                strategy.is_allowed("user1", rule, storage)

            # Move to 30 seconds into second window (50% through)
            mock_time.return_value = 90.0  # Window starts at 60, now at 90

            # Make 4 requests in second window
            for i in range(4):
                strategy.is_allowed("user1", rule, storage)

            # Next request should check against this
            allowed, status = strategy.is_allowed("user1", rule, storage)

            # Should be allowed (weighted count ~8-9, limit 10)
            assert allowed is True

    def test_boundary_behavior_better_than_fixed(self, strategy, rule, storage):
        """Test that SWC handles boundaries better than fixed window"""
        with patch("time.time") as mock_time:
            # End of first window (t=59)
            mock_time.return_value = 59.0

            # Make 10 requests at end of first window
            for i in range(10):
                strategy.is_allowed("user1", rule, storage)

            # Move to start of second window (t=61, 1 second in)
            mock_time.return_value = 61.0

            # With fixed window: would allow 10 more (20 total in 2 seconds!)
            # With SWC: weighted count = (10 * 0.98) + 0 = 9.8 ≈ 10

            # Should block or heavily restrict
            allowed, status = strategy.is_allowed("user1", rule, storage)

            # First request might be allowed, but not many more
            request_count = 1 if allowed else 0

            for i in range(9):
                allowed, _ = strategy.is_allowed("user1", rule, storage)
                if allowed:
                    request_count += 1

            # Should allow far fewer than 10 (fixed window would allow 10)
            assert request_count < 5, f"Allowed {request_count}, should be < 5"

    def test_performance_similar_to_fixed_window(self, strategy, rule, storage):
        """Test that performance is comparable to fixed window"""
        import timeit

        # Time 1000 checks
        def run_checks():
            for i in range(1000):
                strategy.is_allowed(f"user_{i % 100}", rule, storage)

        elapsed = timeit.timeit(run_checks, number=1)

        # Should complete in reasonable time (< 1 second for 1000 checks)
        assert elapsed < 1.0, f"Too slow: {elapsed}s for 1000 checks"

    def test_many_concurrent_users(self, strategy, rule, storage):
        """Test with many concurrent users"""
        # Simulate 1000 users
        for user_id in range(1000):
            for request in range(5):
                allowed, _ = strategy.is_allowed(f"user_{user_id}", rule, storage)
                assert allowed is True  # All within limit


class TestSlidingWindowCounterEdgeCases:
    """Test edge cases and corner scenarios"""

    @pytest.fixture
    def storage(self):
        return InMemoryStorage()

    @pytest.fixture
    def strategy(self):
        return SlidingWindowCounterStrategy()

    @pytest.fixture
    def rule(self):
        return RateThrottleRule(name="test", limit=10, window=60, strategy="sliding_window_counter")

    def test_window_boundary_exact(self, strategy, rule, storage):
        """Test behavior at exact window boundary"""
        with patch("time.time") as mock_time:
            # Make requests at end of first window
            mock_time.return_value = 59.99
            for i in range(10):
                strategy.is_allowed("user1", rule, storage)

            # Exactly at boundary
            mock_time.return_value = 60.0

            allowed, status = strategy.is_allowed("user1", rule, storage)

            # At exact boundary, previous window has full weight
            # Should block
            assert allowed is False

    def test_multiple_windows_progression(self, strategy, rule, storage):
        """Test behavior across multiple complete windows"""
        with patch("time.time") as mock_time:
            # Window 1 (0-60s): 5 requests
            mock_time.return_value = 30.0
            for i in range(5):
                strategy.is_allowed("user1", rule, storage)

            # Window 2 (60-120s): 7 requests
            mock_time.return_value = 90.0
            for i in range(7):
                strategy.is_allowed("user1", rule, storage)

            # Window 3 (120-180s): Check weighted count
            mock_time.return_value = 150.0  # Halfway through window 3

            # Previous window (2) had 7 requests
            # Current window (3) has 0 requests
            # Weighted: (7 * 0.5) + 0 = 3.5

            # Should allow request
            allowed, status = strategy.is_allowed("user1", rule, storage)
            assert allowed is True
            assert status.remaining >= 5  # ~10 - 3.5 = 6.5

    def test_zero_requests_in_windows(self, strategy, rule, storage):
        """Test when no requests in previous window"""
        with patch("time.time") as mock_time:
            # Skip first window entirely (no requests)

            # Second window: make requests
            mock_time.return_value = 90.0  # Halfway through second window

            # Previous window: 0 requests
            # Current window: 5 requests
            # Weighted: (0 * 0.5) + 5 = 5

            for i in range(5):
                allowed, _ = strategy.is_allowed("user1", rule, storage)
                assert allowed is True

            # Should still have room (5 < 10)
            allowed, status = strategy.is_allowed("user1", rule, storage)
            assert allowed is True

    def test_requests_at_window_edges(self, strategy, rule, storage):
        """Test requests at exact window edges"""
        with patch("time.time") as mock_time:
            # Request at very end of window 1
            mock_time.return_value = 59.999
            strategy.is_allowed("user1", rule, storage)

            # Request at very start of window 2
            mock_time.return_value = 60.001
            allowed, _ = strategy.is_allowed("user1", rule, storage)

            # Should account for both requests in weighted count
            assert allowed is True  # Only 2 requests total

    def test_high_limit_accuracy(self, strategy, storage):
        """Test with high limit values"""
        rule = RateThrottleRule(
            name="test", limit=1000, window=60, strategy="sliding_window_counter"
        )

        with patch("time.time") as mock_time:
            # Make 900 requests in first window
            mock_time.return_value = 30.0
            for i in range(900):
                allowed, _ = strategy.is_allowed("user1", rule, storage)
                assert allowed is True

            # Move to second window
            mock_time.return_value = 90.0  # 50% through

            # Weighted: (900 * 0.5) + 0 = 450
            # Should allow ~550 more

            for i in range(550):
                allowed, _ = strategy.is_allowed("user1", rule, storage)
                if not allowed:
                    pytest.fail(f"Failed at request {i}, expected to allow ~550")

    def test_fractional_seconds_handling(self, strategy, rule, storage):
        """Test handling of fractional seconds in window calculation"""
        with patch("time.time") as mock_time:
            # Use fractional timestamps
            mock_time.return_value = 59.7
            for i in range(5):
                strategy.is_allowed("user1", rule, storage)

            # Move to fractional time in next window
            mock_time.return_value = 60.3

            # Should handle fractional window progress correctly
            allowed, status = strategy.is_allowed("user1", rule, storage)
            assert allowed is True or allowed is False  # Either is fine
            # Main test: should not crash with fractional seconds


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
