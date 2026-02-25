"""
Tests for core rate limiting functionality
"""

import time

import pytest

from ratethrottle.core import (
    RateThrottleCore,
    RateThrottleRule,
    RateThrottleStatus,
    RateThrottleViolation,
)
from ratethrottle.storage_backend import InMemoryStorage


class TestRateThrottleRule:
    """Test RateThrottleRule creation and validation"""

    def test_create_basic_rule(self):
        """Test creating a basic rate limit rule"""
        rule = RateThrottleRule(
            name="test_rule",
            limit=100,
            window=60,
        )

        assert rule.name == "test_rule"
        assert rule.limit == 100
        assert rule.window == 60
        assert rule.scope == "ip"
        assert rule.strategy == "sliding_window"
        assert rule.burst == 100  # Default burst equals limit

    def test_create_rule_with_burst(self):
        """Test creating rule with custom burst"""
        rule = RateThrottleRule(
            name="burst_rule",
            limit=100,
            window=60,
            burst=150,
        )

        assert rule.burst == 150

    def test_create_rule_with_strategy(self):
        """Test creating rule with specific strategy"""
        rule = RateThrottleRule(
            name="token_rule",
            limit=100,
            window=60,
            strategy="token_bucket",
        )

        assert rule.strategy == "token_bucket"


class TestRateThrottleCore:
    """Test core rate limiting engine"""

    @pytest.fixture
    def limiter(self):
        """Create a rate limiter instance"""
        return RateThrottleCore(storage=InMemoryStorage())

    @pytest.fixture
    def basic_rule(self):
        """Create a basic rule"""
        return RateThrottleRule(
            name="test_rule",
            limit=10,
            window=60,
            strategy="fixed_window",
        )

    def test_add_rule(self, limiter, basic_rule):
        """Test adding a rate limit rule"""
        limiter.add_rule(basic_rule)
        assert "test_rule" in limiter.rules
        assert limiter.rules["test_rule"] == basic_rule

    def test_remove_rule(self, limiter, basic_rule):
        """Test removing a rate limit rule"""
        limiter.add_rule(basic_rule)
        limiter.remove_rule("test_rule")
        assert "test_rule" not in limiter.rules

    def test_whitelist_management(self, limiter):
        """Test whitelist add/check"""
        identifier = "192.168.1.100"
        limiter.add_to_whitelist(identifier)
        assert identifier in limiter.whitelist

    def test_blacklist_management(self, limiter):
        """Test blacklist add/remove"""
        identifier = "192.168.1.200"
        limiter.add_to_blacklist(identifier)
        assert identifier in limiter.blacklist

        limiter.remove_from_blacklist(identifier)
        assert identifier not in limiter.blacklist

    def test_whitelist_bypasses_limits(self, limiter, basic_rule):
        """Test that whitelisted IPs bypass rate limits"""
        identifier = "192.168.1.100"
        limiter.add_rule(basic_rule)
        limiter.add_to_whitelist(identifier)

        # Make many requests - should all be allowed
        for _ in range(100):
            status = limiter.check_rate_limit(identifier, "test_rule")
            assert status.allowed
            assert status.rule_name == "whitelist"

    def test_blacklist_blocks_all(self, limiter, basic_rule):
        """Test that blacklisted IPs are blocked"""
        identifier = "192.168.1.200"
        limiter.add_rule(basic_rule)
        limiter.add_to_blacklist(identifier)

        status = limiter.check_rate_limit(identifier, "test_rule")
        assert not status.allowed
        assert status.blocked
        assert status.rule_name == "blacklist"

    def test_rate_limiting_basic(self, limiter, basic_rule):
        """Test basic rate limiting"""
        identifier = "192.168.1.100"
        limiter.add_rule(basic_rule)

        # First 10 requests should be allowed
        for i in range(10):
            status = limiter.check_rate_limit(identifier, "test_rule")
            assert status.allowed, f"Request {i+1} should be allowed"
            assert status.remaining == 10 - i - 1

        # 11th request should be blocked
        status = limiter.check_rate_limit(identifier, "test_rule")
        assert not status.allowed
        assert status.remaining == 0

    def test_different_identifiers_independent(self, limiter, basic_rule):
        """Test that different identifiers have independent limits"""
        limiter.add_rule(basic_rule)

        # Use up limit for first identifier
        for _ in range(10):
            status = limiter.check_rate_limit("192.168.1.1", "test_rule")
            assert status.allowed

        # Second identifier should still be allowed
        status = limiter.check_rate_limit("192.168.1.2", "test_rule")
        assert status.allowed
        assert status.remaining == 9

    def test_violation_callback(self, limiter, basic_rule):
        """Test violation callback is triggered"""
        limiter.add_rule(basic_rule)
        violations = []

        def callback(violation):
            violations.append(violation)

        limiter.register_violation_callback(callback)

        # Use up limit and trigger violation
        for _ in range(11):
            limiter.check_rate_limit("192.168.1.100", "test_rule")

        assert len(violations) > 0
        assert violations[0].identifier == "192.168.1.100"
        assert violations[0].rule_name == "test_rule"

    def test_metrics_tracking(self, limiter, basic_rule):
        """Test that metrics are tracked correctly"""
        limiter.add_rule(basic_rule)

        # Make some requests
        for _ in range(5):
            limiter.check_rate_limit("192.168.1.100", "test_rule")

        metrics = limiter.get_metrics()
        assert metrics["total_requests"] == 5
        assert metrics["allowed_requests"] == 5
        assert metrics["blocked_requests"] == 0

    def test_reset_metrics(self, limiter, basic_rule):
        """Test resetting metrics"""
        limiter.add_rule(basic_rule)

        limiter.check_rate_limit("192.168.1.100", "test_rule")
        limiter.reset_metrics()

        metrics = limiter.get_metrics()
        assert metrics["total_requests"] == 0
        assert metrics["allowed_requests"] == 0
        assert metrics["blocked_requests"] == 0

    @pytest.mark.parametrize(
        "strategy", ["fixed_window", "token_bucket", "leaky_bucket", "sliding_window"]
    )
    def test_block_duration_all_strategies(self, limiter, strategy):
        rule = RateThrottleRule(
            name="block_test",
            limit=1,
            window=2,
            block_duration=2,
            strategy=strategy,
        )
        limiter.add_rule(rule)

        # Use up limit
        limiter.check_rate_limit("192.168.1.100", "block_test")

        # Should be blocked
        status = limiter.check_rate_limit("192.168.1.100", "block_test")
        assert not status.allowed

        # Wait for block to expire
        time.sleep(2.1)  # Add buffer

        # Should be allowed again
        status = limiter.check_rate_limit("192.168.1.100", "block_test")
        assert status.allowed, f"{strategy} should allow after block expires"


class TestRateThrottleStatus:
    """Test RateThrottleStatus"""

    def test_create_status(self):
        """Test creating a status object"""
        status = RateThrottleStatus(
            allowed=True,
            remaining=50,
            limit=100,
            reset_time=int(time.time() + 3600),
        )

        assert status.allowed
        assert status.remaining == 50
        assert status.limit == 100
        assert not status.blocked


class TestRateThrottleViolation:
    """Test RateThrottleViolation"""

    def test_create_violation(self):
        """Test creating a violation object"""
        violation = RateThrottleViolation(
            identifier="192.168.1.100",
            rule_name="test_rule",
            timestamp="2025-01-01T00:00:00",
            requests_made=101,
            limit=100,
            blocked_until="2025-01-01T00:05:00",
            retry_after=300,
            scope="ip",
        )

        assert violation.identifier == "192.168.1.100"
        assert violation.rule_name == "test_rule"
        assert violation.requests_made == 101
        assert violation.limit == 100
        assert violation.retry_after == 300


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
