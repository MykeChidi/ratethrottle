"""
Tests for DDoS protection, analytics, and exceptions
"""

import tempfile
import time
from pathlib import Path

import pytest

from ratethrottle.analytics import RateThrottleAnalytics
from ratethrottle.ddos import DDoSProtection, TrafficPattern
from ratethrottle.exceptions import (
    ConfigurationError,
    InvalidRuleError,
    RateLimitExceeded,
    RateThrottleException,
    RuleNotFoundError,
    StorageError,
    StrategyNotFoundError,
)

# ==============================================
# DDoS Protection Tests
# ==============================================


class TestTrafficPattern:
    """Test TrafficPattern dataclass"""

    def test_create_pattern(self):
        """Test creating a traffic pattern"""
        pattern = TrafficPattern(
            identifier="192.168.1.1",
            request_rate=10.5,
            unique_endpoints=5,
            suspicious_score=0.3,
            is_suspicious=False,
            analysis_window=60,
            timestamp=time.time(),
        )

        assert pattern.identifier == "192.168.1.1"
        assert pattern.request_rate == 10.5
        assert pattern.is_suspicious is False

    def test_to_dict(self):
        """Test converting pattern to dict"""
        pattern = TrafficPattern(
            identifier="test",
            request_rate=1.0,
            unique_endpoints=1,
            suspicious_score=0.0,
            is_suspicious=False,
            analysis_window=60,
            timestamp=time.time(),
        )

        d = pattern.to_dict()
        assert isinstance(d, dict)
        assert d["identifier"] == "test"


class TestDDoSProtection:
    """Test DDoS protection"""

    def test_initialization(self):
        """Test DDoS protection initialization"""
        ddos = DDoSProtection({"enabled": True, "threshold": 1000})

        assert ddos.enabled is True
        assert ddos.threshold == 1000

    def test_initialization_validation_error(self):
        """Test initialization with invalid config"""
        with pytest.raises(ConfigurationError):
            DDoSProtection({"threshold": -1})

    def test_analyze_traffic_when_disabled(self):
        """Test analysis when disabled"""
        ddos = DDoSProtection({"enabled": False})
        pattern = ddos.analyze_traffic("192.168.1.1", "/api/test")

        assert pattern.is_suspicious is False

    def test_analyze_traffic_normal(self):
        """Test analyzing normal traffic"""
        ddos = DDoSProtection({"enabled": True, "threshold": 1000})

        pattern = ddos.analyze_traffic("192.168.1.1", "/api/test")

        assert isinstance(pattern, TrafficPattern)
        assert pattern.identifier == "192.168.1.1"
        assert pattern.is_suspicious is False

    def test_analyze_traffic_high_rate(self):
        """Test detecting high request rate"""
        ddos = DDoSProtection({"enabled": True, "threshold": 10, "window": 1, "auto_block": False})

        # Generate high traffic
        for _ in range(20):
            pattern = ddos.analyze_traffic("192.168.1.1", "/api/test")

        assert pattern.is_suspicious is True
        assert pattern.suspicious_score > 0

    def test_analyze_traffic_many_endpoints(self):
        """Test detecting scanning behavior"""
        ddos = DDoSProtection({"enabled": True, "max_unique_endpoints": 5, "auto_block": False})

        # Access many different endpoints
        for i in range(10):
            ddos.analyze_traffic("192.168.1.1", f"/api/endpoint{i}")

        pattern = ddos.analyze_traffic("192.168.1.1", "/api/another")
        assert pattern.unique_endpoints > 5

    def test_whitelisted_ip_not_suspicious(self):
        """Test whitelisted IP is not marked suspicious"""
        ddos = DDoSProtection({"enabled": True, "threshold": 1})

        ddos.whitelist_ip("192.168.1.1")

        # Generate high traffic
        for _ in range(100):
            pattern = ddos.analyze_traffic("192.168.1.1", "/api/test")

        assert pattern.is_suspicious is False

    def test_auto_block(self):
        """Test automatic blocking"""
        ddos = DDoSProtection({"enabled": True, "threshold": 10, "window": 1, "auto_block": True})

        # Generate suspicious traffic
        for _ in range(50):
            ddos.analyze_traffic("192.168.1.1", "/api/test")

        # Should be blocked
        assert ddos.is_blocked("192.168.1.1")

    def test_block_ip(self):
        """Test blocking an IP"""
        ddos = DDoSProtection()

        ddos.block_ip("192.168.1.1", duration=60)
        assert ddos.is_blocked("192.168.1.1")

    def test_unblock_ip(self):
        """Test unblocking an IP"""
        ddos = DDoSProtection()

        ddos.block_ip("192.168.1.1")
        assert ddos.is_blocked("192.168.1.1")

        result = ddos.unblock_ip("192.168.1.1")
        assert result is True
        assert not ddos.is_blocked("192.168.1.1")

    def test_block_expiry(self):
        """Test that blocks expire"""
        ddos = DDoSProtection()

        ddos.block_ip("192.168.1.1", duration=1)
        assert ddos.is_blocked("192.168.1.1")

        time.sleep(1.1)
        assert not ddos.is_blocked("192.168.1.1")

    def test_whitelist_ip(self):
        """Test whitelisting an IP"""
        ddos = DDoSProtection()

        ddos.block_ip("192.168.1.1")
        ddos.whitelist_ip("192.168.1.1")

        assert not ddos.is_blocked("192.168.1.1")
        assert "192.168.1.1" in ddos.whitelisted_ips

    def test_remove_from_whitelist(self):
        """Test removing from whitelist"""
        ddos = DDoSProtection()

        ddos.whitelist_ip("192.168.1.1")
        result = ddos.remove_from_whitelist("192.168.1.1")

        assert result is True
        assert "192.168.1.1" not in ddos.whitelisted_ips

    def test_get_statistics(self):
        """Test getting statistics"""
        ddos = DDoSProtection({"enabled": True})

        # Generate some traffic
        ddos.analyze_traffic("192.168.1.1", "/api/test")
        ddos.block_ip("192.168.1.2")

        stats = ddos.get_statistics()

        assert "enabled" in stats
        assert "blocked_ips" in stats
        assert stats["total_analyzed"] > 0

    def test_reset_statistics(self):
        """Test resetting statistics"""
        ddos = DDoSProtection()

        ddos.analyze_traffic("192.168.1.1", "/api/test")
        ddos.reset_statistics()

        stats = ddos.get_statistics()
        assert stats["total_analyzed"] == 0

    def test_export_report(self):
        """Test exporting report"""
        ddos = DDoSProtection()

        ddos.analyze_traffic("192.168.1.1", "/api/test")

        report = ddos.export_report()
        assert "generated_at" in report
        assert "statistics" in report


# ==============================================
# Analytics Tests
# ==============================================


class TestRateThrottleAnalytics:
    """Test analytics"""

    def test_initialization(self):
        """Test analytics initialization"""
        analytics = RateThrottleAnalytics(max_history=1000)
        assert analytics.max_history == 1000

    def test_initialization_invalid_max_history(self):
        """Test initialization with invalid max_history"""
        with pytest.raises(ConfigurationError):
            RateThrottleAnalytics(max_history=0)

    def test_record_request(self):
        """Test recording a request"""
        analytics = RateThrottleAnalytics()

        analytics.record_request("192.168.1.1", "api", True)

        assert len(analytics.requests) == 1
        assert analytics.stats["total_requests"] == 1

    def test_record_violation(self):
        """Test recording a violation"""
        analytics = RateThrottleAnalytics()

        violation = {
            "identifier": "192.168.1.1",
            "rule_name": "api",
            "timestamp": "2025-01-01T00:00:00",
        }

        analytics.record_violation(violation)

        assert len(analytics.violations) == 1
        assert analytics.stats["total_violations"] == 1

    def test_data_sanitization(self):
        """Test data sanitization"""
        analytics = RateThrottleAnalytics(sanitize_data=True)

        analytics.record_request("192.168.1.100", "api", True, metadata={"password": "secret123"})

        request = analytics.requests[0]
        assert "192.168.1.xxx" in request["identifier"]
        assert request["metadata"]["password"] == "***REDACTED***"

    def test_get_top_violators(self):
        """Test getting top violators"""
        analytics = RateThrottleAnalytics()

        # Record some violations
        for i in range(5):
            analytics.record_violation(
                {
                    "identifier": "192.168.1.1",
                    "rule_name": "api",
                    "timestamp": "2025-01-01T00:00:00",
                }
            )

        for i in range(3):
            analytics.record_violation(
                {
                    "identifier": "192.168.1.2",
                    "rule_name": "api",
                    "timestamp": "2025-01-01T00:00:00",
                }
            )

        top = analytics.get_top_violators(10)

        assert len(top) == 2
        assert top[0]["violations"] == 5

    def test_get_violation_timeline(self):
        """Test getting violation timeline"""
        analytics = RateThrottleAnalytics()

        analytics.record_violation(
            {"identifier": "192.168.1.1", "rule_name": "api", "timestamp": "2025-01-01T10:00:00"}
        )

        timeline = analytics.get_violation_timeline(24)
        assert isinstance(timeline, dict)

    def test_get_rule_statistics(self):
        """Test getting rule statistics"""
        analytics = RateThrottleAnalytics()

        analytics.record_request("192.168.1.1", "api", True)
        analytics.record_request("192.168.1.1", "api", False)

        stats = analytics.get_rule_statistics()

        assert "api" in stats
        assert stats["api"]["total_requests"] == 2
        assert stats["api"]["allowed"] == 1
        assert stats["api"]["blocked"] == 1

    def test_get_summary(self):
        """Test getting summary"""
        analytics = RateThrottleAnalytics()

        analytics.record_request("192.168.1.1", "api", True)

        summary = analytics.get_summary()

        assert "total_requests" in summary
        assert "unique_identifiers" in summary

    def test_export_report(self):
        """Test exporting report"""
        analytics = RateThrottleAnalytics()

        analytics.record_request("192.168.1.1", "api", True)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = f.name

        try:
            analytics.export_report(temp_path)
            assert Path(temp_path).exists()
        finally:
            Path(temp_path).unlink()

    def test_clear_old_data(self):
        """Test clearing old data"""
        analytics = RateThrottleAnalytics()

        # Add some recent data
        analytics.record_request("192.168.1.1", "api", True)

        # Clear data older than 30 days
        cleared = analytics.clear_old_data(days=30)

        # Recent data should remain
        assert len(analytics.requests) > 0

    def test_reset(self):
        """Test resetting analytics"""
        analytics = RateThrottleAnalytics()

        analytics.record_request("192.168.1.1", "api", True)
        analytics.reset()

        assert len(analytics.requests) == 0
        assert analytics.stats["total_requests"] == 0


# ==============================================
# Exception Tests
# ==============================================


class TestExceptions:
    """Test custom exceptions"""

    def test_rate_throttle_exception(self):
        """Test base exception"""
        exc = RateThrottleException("Test error")
        assert str(exc) == "Test error"
        assert isinstance(exc, Exception)

    def test_configuration_error(self):
        """Test configuration error"""
        exc = ConfigurationError("Config error")
        assert isinstance(exc, RateThrottleException)

    def test_storage_error(self):
        """Test storage error"""
        exc = StorageError("Storage error")
        assert isinstance(exc, RateThrottleException)

    def test_rate_limit_exceeded(self):
        """Test rate limit exceeded exception"""
        exc = RateLimitExceeded(
            "Rate limit exceeded", retry_after=60, limit=100, remaining=0, reset_time=1234567890
        )

        assert exc.retry_after == 60
        assert exc.limit == 100
        assert exc.remaining == 0
        assert exc.reset_time == 1234567890

    def test_strategy_not_found_error(self):
        """Test strategy not found error"""
        exc = StrategyNotFoundError("Strategy not found")
        assert isinstance(exc, RateThrottleException)

    def test_rule_not_found_error(self):
        """Test rule not found error"""
        exc = RuleNotFoundError("Rule not found")
        assert isinstance(exc, RateThrottleException)

    def test_invalid_rule_error(self):
        """Test invalid rule error"""
        exc = InvalidRuleError("Invalid rule")
        assert isinstance(exc, RateThrottleException)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
