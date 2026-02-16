"""
Tests for helper functions
"""

import pytest

from ratethrottle.core import RateThrottleCore
from ratethrottle.exceptions import ConfigurationError
from ratethrottle.helpers import create_limiter, get_client_ip, parse_rate_limit


class TestParseRateLimit:
    """Test rate limit string parsing"""

    def test_parse_per_second(self):
        """Test parsing per second rates"""
        assert parse_rate_limit("5/second") == (5, 1)
        assert parse_rate_limit("10/seconds") == (10, 1)
        assert parse_rate_limit("100/sec") == (100, 1)
        assert parse_rate_limit("50/s") == (50, 1)

    def test_parse_per_minute(self):
        """Test parsing per minute rates"""
        assert parse_rate_limit("100/minute") == (100, 60)
        assert parse_rate_limit("50/minutes") == (50, 60)
        assert parse_rate_limit("200/min") == (200, 60)
        assert parse_rate_limit("75/m") == (75, 60)

    def test_parse_per_hour(self):
        """Test parsing per hour rates"""
        assert parse_rate_limit("1000/hour") == (1000, 3600)
        assert parse_rate_limit("500/hours") == (500, 3600)
        assert parse_rate_limit("2000/hr") == (2000, 3600)
        assert parse_rate_limit("1500/h") == (1500, 3600)

    def test_parse_per_day(self):
        """Test parsing per day rates"""
        assert parse_rate_limit("10000/day") == (10000, 86400)
        assert parse_rate_limit("5000/days") == (5000, 86400)
        assert parse_rate_limit("20000/d") == (20000, 86400)

    def test_parse_with_spaces(self):
        """Test parsing with extra spaces"""
        assert parse_rate_limit("  100  /  minute  ") == (100, 60)
        assert parse_rate_limit("50 / second") == (50, 1)

    def test_invalid_format(self):
        """Test invalid format raises error"""
        with pytest.raises(ValueError, match="Rate string must contain '/' separator"):
            parse_rate_limit("100")

        with pytest.raises(ValueError, match="Invalid rate limit format"):
            parse_rate_limit("abc/minute")

    def test_invalid_period(self):
        """Test invalid time period raises error"""
        with pytest.raises(ValueError, match="Unknown time period:"):
            parse_rate_limit("100/fortnight")

    def test_negative_limit(self):
        """Test negative limit raises error"""
        with pytest.raises(ValueError, match="Limit must be positive"):
            parse_rate_limit("-10/minute")

    def test_zero_limit(self):
        """Test zero limit raises error"""
        with pytest.raises(ValueError, match="Limit must be positive"):
            parse_rate_limit("0/minute")


class TestCreateLimiter:
    """Test limiter creation helper"""

    def test_create_memory_limiter(self):
        """Test creating in-memory limiter"""
        limiter = create_limiter("memory")
        assert isinstance(limiter, RateThrottleCore)

    def test_create_memory_limiter_default(self):
        """Test creating limiter with default storage"""
        limiter = create_limiter()
        assert isinstance(limiter, RateThrottleCore)

    def test_invalid_storage_type(self):
        """Test invalid storage type raises error"""
        with pytest.raises(ConfigurationError, match="Unknown storage type"):
            create_limiter("invalid_storage")

    def test_redis_without_url(self):
        """Test Redis storage without URL raises error"""
        with pytest.raises(ConfigurationError, match="redis_url is required"):
            create_limiter("redis")


class MockRequest:
    """Mock request object for testing"""

    def __init__(self, headers=None, remote_addr=None, meta=None):
        self.headers = headers or {}
        self.remote_addr = remote_addr
        self.META = meta or {}


class TestGetClientIP:
    """Test client IP extraction"""

    def test_direct_remote_addr(self):
        """Test getting IP from remote_addr"""
        request = MockRequest(remote_addr="192.168.1.100")
        ip = get_client_ip(request)
        assert ip == "192.168.1.100"

    def test_x_forwarded_for_single(self):
        """Test X-Forwarded-For with single IP"""
        request = MockRequest(headers={"X-Forwarded-For": "203.0.113.1"}, remote_addr="192.168.1.1")
        ip = get_client_ip(request)
        assert ip == "203.0.113.1"

    def test_x_forwarded_for_multiple(self):
        """Test X-Forwarded-For with multiple IPs"""
        request = MockRequest(
            headers={"X-Forwarded-For": "203.0.113.1, 70.41.3.18, 150.172.238.178"},
            remote_addr="192.168.1.1",
        )
        ip = get_client_ip(request)
        assert ip == "203.0.113.1"

    def test_x_forwarded_for_with_trusted_proxies(self):
        """Test X-Forwarded-For with trusted proxies"""
        request = MockRequest(
            headers={"X-Forwarded-For": "10.0.0.1, 203.0.113.1, 10.0.0.2"},
            remote_addr="192.168.1.1",
        )
        ip = get_client_ip(request, trusted_proxies=["10.0.0.1", "10.0.0.2"])
        assert ip == "203.0.113.1"

    def test_x_real_ip(self):
        """Test X-Real-IP header"""
        request = MockRequest(headers={"X-Real-IP": "203.0.113.1"}, remote_addr="192.168.1.1")
        ip = get_client_ip(request)
        assert ip == "203.0.113.1"

    def test_x_forwarded_for_priority(self):
        """Test X-Forwarded-For has priority over X-Real-IP"""
        request = MockRequest(
            headers={"X-Forwarded-For": "203.0.113.1", "X-Real-IP": "203.0.113.2"},
            remote_addr="192.168.1.1",
        )
        ip = get_client_ip(request)
        assert ip == "203.0.113.1"

    def test_fallback_to_default(self):
        """Test fallback to default IP"""
        request = MockRequest()
        ip = get_client_ip(request)
        assert ip == "0.0.0.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
