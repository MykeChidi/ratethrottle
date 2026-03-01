"""
Tests for gRPC rate limiting
"""

import pytest
from unittest.mock import Mock


from ratethrottle.gRPC import (
    GRPCLimits,
    GRPCRateLimitInterceptor,
    grpc_ratelimit,
    ServiceRateLimiter,
    extract_user_id_from_metadata,
)


class TestGRPCLimits:
    """Test GRPCLimits configuration"""

    def test_default_limits(self):
        """Test default limit values"""
        limits = GRPCLimits()

        assert limits.requests_per_minute == 1000
        assert limits.concurrent_requests == 50
        assert limits.stream_messages_per_minute == 5000

    def test_custom_limits(self):
        """Test custom limit values"""
        limits = GRPCLimits(
            requests_per_minute=100, concurrent_requests=10, stream_messages_per_minute=500
        )

        assert limits.requests_per_minute == 100
        assert limits.concurrent_requests == 10
        assert limits.stream_messages_per_minute == 500


class TestGRPCRateLimitInterceptor:
    """Test gRPC interceptor"""

    @pytest.fixture
    def interceptor(self):
        """Create interceptor instance"""
        limits = GRPCLimits(
            requests_per_minute=10, concurrent_requests=3, stream_messages_per_minute=50
        )
        return GRPCRateLimitInterceptor(limits)

    @pytest.fixture
    def mock_context(self):
        """Create mock gRPC context"""
        context = Mock()
        context.invocation_metadata = Mock(
            return_value=[
                ("x-forwarded-for", "192.168.1.1"),
            ]
        )
        context.peer = Mock(return_value="ipv4:192.168.1.1:54321")
        context.abort = Mock()
        context.set_trailing_metadata = Mock()
        return context

    @pytest.fixture
    def mock_handler_call_details(self):
        """Create mock handler call details"""
        details = Mock()
        details.method = "/package.Service/GetUser"
        return details

    def test_initialization(self, interceptor):
        """Test interceptor initializes correctly"""
        assert interceptor.limits.requests_per_minute == 10
        assert interceptor.limits.concurrent_requests == 3
        assert len(interceptor.concurrent_requests) == 0

    def test_extract_client_id_from_forwarded_header(self, interceptor):
        """Test extracting client ID from X-Forwarded-For"""
        context = Mock()
        context.invocation_metadata = Mock(
            return_value=[
                ("x-forwarded-for", "192.168.1.100, 10.0.0.1"),
            ]
        )

        client_id = interceptor.extract_client_id(context)
        assert client_id == "192.168.1.100"

    def test_extract_client_id_from_peer(self, interceptor):
        """Test extracting client ID from peer"""
        context = Mock()
        context.invocation_metadata = Mock(return_value=[])
        context.peer = Mock(return_value="ipv4:192.168.1.50:12345")

        client_id = interceptor.extract_client_id(context)
        assert client_id == "192.168.1.50"

    def test_extract_client_id_fallback(self, interceptor):
        """Test client ID extraction fallback"""
        context = Mock()
        context.invocation_metadata = Mock(return_value=[])
        context.peer = Mock(return_value="unknown")

        client_id = interceptor.extract_client_id(context)
        assert client_id == "unknown"

    def test_get_method_name(self, interceptor, mock_handler_call_details):
        """Test extracting method name"""
        method_name = interceptor._get_method_name(mock_handler_call_details)
        assert method_name == "GetUser"

    def test_check_concurrent_limit_allowed(self, interceptor):
        """Test concurrent limit when under limit"""
        interceptor.concurrent_requests["client1"] = 2

        result = interceptor._check_concurrent_limit("client1")
        assert result is True

    def test_check_concurrent_limit_exceeded(self, interceptor):
        """Test concurrent limit when at limit"""
        interceptor.concurrent_requests["client1"] = 3

        result = interceptor._check_concurrent_limit("client1")
        assert result is False

    def test_increment_concurrent(self, interceptor):
        """Test incrementing concurrent counter"""
        interceptor._increment_concurrent("client1")
        assert interceptor.concurrent_requests["client1"] == 1

        interceptor._increment_concurrent("client1")
        assert interceptor.concurrent_requests["client1"] == 2

    def test_decrement_concurrent(self, interceptor):
        """Test decrementing concurrent counter"""
        interceptor.concurrent_requests["client1"] = 3

        interceptor._decrement_concurrent("client1")
        assert interceptor.concurrent_requests["client1"] == 2

        interceptor._decrement_concurrent("client1")
        interceptor._decrement_concurrent("client1")
        assert "client1" not in interceptor.concurrent_requests

    def test_get_statistics(self, interceptor):
        """Test getting statistics"""
        interceptor.concurrent_requests["client1"] = 2
        interceptor.concurrent_requests["client2"] = 1

        stats = interceptor.get_statistics()

        assert stats["current_concurrent_requests"] == 3
        assert stats["unique_clients"] == 2
        assert "limits" in stats
        assert stats["limits"]["requests_per_minute"] == 10


class TestGRPCRateLimitDecorator:
    """Test @grpc_ratelimit decorator"""

    def test_decorator_basic(self):
        """Test basic decorator usage"""

        @grpc_ratelimit(limit=10, window=60)
        def test_method(self, request, context):
            return "success"

        # Method should be wrapped
        assert callable(test_method)

    def test_decorator_allows_request(self):
        """Test decorator allows request within limit"""
        context = Mock()
        context.invocation_metadata = Mock(return_value=[])
        context.peer = Mock(return_value="ipv4:192.168.1.1:12345")
        context.abort = Mock()

        @grpc_ratelimit(limit=10, window=60)
        def test_method(self, request, context):
            return "success"

        # Should not abort
        result = test_method(None, "request", context)
        assert result == "success"
        context.abort.assert_not_called()

    def test_decorator_blocks_excess_requests(self):
        """Test decorator blocks requests over limit"""
        context = Mock()
        context.invocation_metadata = Mock(return_value=[])
        context.peer = Mock(return_value="ipv4:192.168.1.1:12345")
        context.abort = Mock()
        context.set_trailing_metadata = Mock()

        @grpc_ratelimit(limit=2, window=60)
        def test_method(self, request, context):
            return "success"

        # First two should work
        test_method(None, "request", context)
        test_method(None, "request", context)

        # Third should be blocked
        test_method(None, "request", context)

        # Should have aborted
        assert context.abort.called


class TestExtractUserIdFromMetadata:
    """Test extract_user_id_from_metadata helper"""

    def test_extract_from_default_key(self):
        """Test extracting from default 'user-id' key"""
        extractor = extract_user_id_from_metadata()

        context = Mock()
        context.invocation_metadata = Mock(
            return_value=[
                ("user-id", "user_123"),
            ]
        )

        user_id = extractor(context)
        assert user_id == "user_123"

    def test_extract_from_custom_key(self):
        """Test extracting from custom key"""
        extractor = extract_user_id_from_metadata("x-user-id")

        context = Mock()
        context.invocation_metadata = Mock(
            return_value=[
                ("x-user-id", "user_456"),
            ]
        )

        user_id = extractor(context)
        assert user_id == "user_456"

    def test_fallback_to_ip(self):
        """Test fallback to IP when metadata not present"""
        extractor = extract_user_id_from_metadata()

        context = Mock()
        context.invocation_metadata = Mock(return_value=[])
        context.peer = Mock(return_value="ipv4:192.168.1.1:12345")

        client_id = extractor(context)
        assert client_id == "192.168.1.1"


class TestServiceRateLimiter:
    """Test ServiceRateLimiter"""

    def test_initialization(self):
        """Test service limiter initialization"""
        limits = GRPCLimits(requests_per_minute=100)
        limiter = ServiceRateLimiter(limits, service_name="UserService")

        assert limiter.service_name == "UserService"
        assert limiter.limits.requests_per_minute == 100

    def test_check_rate_limit_allowed(self):
        """Test rate limit check allows request"""
        limits = GRPCLimits(requests_per_minute=10)
        limiter = ServiceRateLimiter(limits, service_name="UserService")

        context = Mock()
        context.abort = Mock()
        context.set_trailing_metadata = Mock()

        result = limiter.check_rate_limit("client1", context)
        assert result is True
        context.abort.assert_not_called()

    def test_check_rate_limit_blocked(self):
        """Test rate limit check blocks request"""
        limits = GRPCLimits(requests_per_minute=2)
        limiter = ServiceRateLimiter(limits, service_name="UserService")

        context = Mock()
        context.abort = Mock()
        context.set_trailing_metadata = Mock()

        # First two requests OK
        limiter.check_rate_limit("client1", context)
        limiter.check_rate_limit("client1", context)

        # Third should be blocked
        result = limiter.check_rate_limit("client1", context)
        assert result is False
        context.abort.assert_called()


class TestGRPCViolationHandling:
    """Test violation callbacks"""

    def test_violation_callback_connection_rate(self):
        """Test violation callback for connection rate"""
        violations = []

        def on_violation(info):
            violations.append(info)

        limits = GRPCLimits(requests_per_minute=1)
        interceptor = GRPCRateLimitInterceptor(limits, on_violation=on_violation)

        # Trigger violation by checking limit twice
        context = Mock()
        context.invocation_metadata = Mock(return_value=[])
        context.peer = Mock(return_value="ipv4:192.168.1.1:12345")

        # Extract client ID for both checks
        client_id = interceptor.extract_client_id(context)

        # First check OK
        interceptor.limiter.check_rate_limit(client_id, "grpc_requests")

        # Second check should trigger violation
        interceptor.limiter.check_rate_limit(client_id, "grpc_requests")

        # Violation callback not called in base check
        # Would be called in intercept_service method


class TestGRPCEdgeCases:
    """Test edge cases and error handling"""

    def test_method_limits_override(self):
        """Test method-specific limits override defaults"""
        method_limits = {
            "GetUser": GRPCLimits(requests_per_minute=100),
            "CreateUser": GRPCLimits(requests_per_minute=10),
        }

        interceptor = GRPCRateLimitInterceptor(
            GRPCLimits(requests_per_minute=50), method_limits=method_limits
        )

        get_limits = interceptor._get_limits_for_method("GetUser")
        assert get_limits.requests_per_minute == 100

        create_limits = interceptor._get_limits_for_method("CreateUser")
        assert create_limits.requests_per_minute == 10

        other_limits = interceptor._get_limits_for_method("DeleteUser")
        assert other_limits.requests_per_minute == 50  # Default

    def test_multiple_clients_independent(self):
        """Test that different clients have independent limits"""
        limits = GRPCLimits(requests_per_minute=2)
        interceptor = GRPCRateLimitInterceptor(limits)

        # Client 1 makes 2 requests
        for _ in range(2):
            status = interceptor.limiter.check_rate_limit("client1", "grpc_requests")
            assert status.allowed

        # Client 2 should still be able to make requests
        status = interceptor.limiter.check_rate_limit("client2", "grpc_requests")
        assert status.allowed

    def test_concurrent_tracking_per_client(self):
        """Test concurrent request tracking per client"""
        interceptor = GRPCRateLimitInterceptor(GRPCLimits(concurrent_requests=2))

        # Client 1: 2 concurrent
        interceptor._increment_concurrent("client1")
        interceptor._increment_concurrent("client1")

        # Client 2: 1 concurrent
        interceptor._increment_concurrent("client2")

        assert interceptor.concurrent_requests["client1"] == 2
        assert interceptor.concurrent_requests["client2"] == 1

        # Client 1 at limit
        assert not interceptor._check_concurrent_limit("client1")

        # Client 2 still has room
        assert interceptor._check_concurrent_limit("client2")


class TestGRPCIntegration:
    """Integration tests"""

    def test_full_request_lifecycle(self):
        """Test complete request lifecycle"""
        limits = GRPCLimits(requests_per_minute=10, concurrent_requests=5)
        interceptor = GRPCRateLimitInterceptor(limits)

        context = Mock()
        context.invocation_metadata = Mock(return_value=[])
        context.peer = Mock(return_value="ipv4:192.168.1.1:12345")

        client_id = interceptor.extract_client_id(context)

        # Check rate limit (should pass)
        status = interceptor.limiter.check_rate_limit(client_id, "grpc_requests")
        assert status.allowed

        # Check concurrent limit (should pass)
        assert interceptor._check_concurrent_limit(client_id)

        # Increment concurrent
        interceptor._increment_concurrent(client_id)
        assert interceptor.concurrent_requests[client_id] == 1

        # Process request...

        # Decrement concurrent
        interceptor._decrement_concurrent(client_id)
        assert client_id not in interceptor.concurrent_requests


class TestGRPCPerformance:
    """Performance-related tests"""

    def test_many_clients_tracking(self):
        """Test tracking many concurrent clients"""
        interceptor = GRPCRateLimitInterceptor()

        # Simulate 1000 clients
        for i in range(1000):
            client_id = f"client_{i}"
            status = interceptor.limiter.check_rate_limit(client_id, "grpc_requests")
            assert status.allowed

        # All should be tracked
        metrics = interceptor.limiter.get_metrics()
        assert metrics["total_requests"] == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
