"""
Tests for WebSocket rate limiting
"""

import pytest
from unittest.mock import Mock, AsyncMock
from ratethrottle.websocket import (
    WebSocketLimits,
    WebSocketRateLimiter,
    ConnectionInfo,
    FastAPIWebSocketLimiter,
    SocketIOLimiter,
    ChannelsRateLimiter,
)


class TestWebSocketLimits:
    """Test WebSocketLimits configuration"""

    def test_default_limits(self):
        """Test default limit values"""
        limits = WebSocketLimits()

        assert limits.connections_per_minute == 60
        assert limits.messages_per_minute == 1000
        assert limits.bytes_per_minute is None
        assert limits.max_concurrent_connections == 10
        assert limits.max_message_size == 65536

    def test_custom_limits(self):
        """Test custom limit values"""
        limits = WebSocketLimits(
            connections_per_minute=10,
            messages_per_minute=100,
            bytes_per_minute=1048576,
            max_concurrent_connections=5,
            max_message_size=1024,
        )

        assert limits.connections_per_minute == 10
        assert limits.messages_per_minute == 100
        assert limits.bytes_per_minute == 1048576
        assert limits.max_concurrent_connections == 5
        assert limits.max_message_size == 1024


class TestConnectionInfo:
    """Test ConnectionInfo dataclass"""

    def test_connection_info_creation(self):
        """Test creating connection info"""
        info = ConnectionInfo(
            client_id="client_123", connected_at=1234567890.0, metadata={"user_id": "user_456"}
        )

        assert info.client_id == "client_123"
        assert info.connected_at == 1234567890.0
        assert info.message_count == 0
        assert info.bytes_sent == 0
        assert info.metadata == {"user_id": "user_456"}


class TestWebSocketRateLimiter:
    """Test WebSocketRateLimiter core functionality"""

    @pytest.fixture
    def limiter(self):
        """Create rate limiter instance"""
        limits = WebSocketLimits(
            connections_per_minute=5,
            messages_per_minute=10,
            bytes_per_minute=1000,
            max_concurrent_connections=3,
            max_message_size=100,
        )
        return WebSocketRateLimiter(limits)

    @pytest.mark.asyncio
    async def test_check_connection_allowed(self, limiter):
        """Test that connection is allowed within limits"""
        result = await limiter.check_connection("client1")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_connection_rate_limit(self, limiter):
        """Test connection rate limiting"""
        # Make connections up to limit
        for i in range(5):
            result = await limiter.check_connection("client1")
            assert result is True

        # 6th connection should fail
        result = await limiter.check_connection("client1")
        assert result is False

    @pytest.mark.asyncio
    async def test_concurrent_connection_limit(self, limiter):
        """Test concurrent connection limit"""
        # Register 3 connections (at limit)
        await limiter.register_connection("conn1", "client1")
        await limiter.register_connection("conn2", "client1")
        await limiter.register_connection("conn3", "client1")

        # 4th connection should be denied
        result = await limiter.check_connection("client1")
        assert result is False

        # Unregister one
        await limiter.unregister_connection("conn1")

        # Now should be allowed
        result = await limiter.check_connection("client1")
        assert result is True

    @pytest.mark.asyncio
    async def test_register_connection(self, limiter):
        """Test registering a connection"""
        await limiter.register_connection(
            "conn_123", "client_456", metadata={"user_id": "user_789"}
        )

        assert "conn_123" in limiter.active_connections
        assert "client_456" in limiter.connections_by_client
        assert "conn_123" in limiter.connections_by_client["client_456"]

        info = limiter.get_connection_info("conn_123")
        assert info.client_id == "client_456"
        assert info.metadata == {"user_id": "user_789"}

    @pytest.mark.asyncio
    async def test_unregister_connection(self, limiter):
        """Test unregistering a connection"""
        await limiter.register_connection("conn_123", "client_456")
        await limiter.unregister_connection("conn_123")

        assert "conn_123" not in limiter.active_connections
        assert "client_456" not in limiter.connections_by_client

    @pytest.mark.asyncio
    async def test_check_message_allowed(self, limiter):
        """Test that message is allowed"""
        await limiter.register_connection("conn_123", "client_456")

        result = await limiter.check_message("conn_123", message_size=50)

        assert result["allowed"] is True
        assert result["reason"] == "ok"

    @pytest.mark.asyncio
    async def test_check_message_rate_limit(self, limiter):
        """Test message rate limiting"""
        await limiter.register_connection("conn_123", "client_456")

        # Send messages up to limit (10)
        for i in range(10):
            result = await limiter.check_message("conn_123", message_size=10)
            assert result["allowed"] is True

        # 11th message should fail
        result = await limiter.check_message("conn_123", message_size=10)
        assert result["allowed"] is False
        assert result["reason"] == "rate_limit_exceeded"

    @pytest.mark.asyncio
    async def test_check_message_size_limit(self, limiter):
        """Test message size limiting"""
        await limiter.register_connection("conn_123", "client_456")

        # Message too large
        result = await limiter.check_message("conn_123", message_size=200)

        assert result["allowed"] is False
        assert result["reason"] == "message_too_large"
        assert result["max_size"] == 100

    @pytest.mark.asyncio
    async def test_check_message_bandwidth_limit(self, limiter):
        """Test bandwidth limiting"""
        await limiter.register_connection("conn_123", "client_456")

        # Send messages totaling 1000 bytes (at limit)
        for i in range(10):
            result = await limiter.check_message("conn_123", message_size=100)
            assert result["allowed"] is True

        # Next message exceeds bandwidth
        result = await limiter.check_message("conn_123", message_size=100)
        assert result["allowed"] is False
        assert result["reason"] == "rate_limit_exceeded"

    @pytest.mark.asyncio
    async def test_check_message_updates_stats(self, limiter):
        """Test that message check updates connection stats"""
        await limiter.register_connection("conn_123", "client_456")

        await limiter.check_message("conn_123", message_size=50)

        info = limiter.get_connection_info("conn_123")
        assert info.message_count == 1
        assert info.bytes_sent == 50

    @pytest.mark.asyncio
    async def test_violation_callback(self, limiter):
        """Test violation callback is called"""
        violations = []

        def on_violation(violation):
            violations.append(violation)

        limiter = WebSocketRateLimiter(
            WebSocketLimits(connections_per_minute=1), on_violation=on_violation
        )

        # First connection OK
        await limiter.check_connection("client1")

        # Second connection triggers violation
        await limiter.check_connection("client1")

        assert len(violations) == 1
        assert violations[0]["type"] == "connection_rate"
        assert violations[0]["client_id"] == "client1"

    def test_get_client_connections(self, limiter):
        """Test getting connection count for client"""
        limiter.connections_by_client["client1"] = {"conn1", "conn2", "conn3"}

        count = limiter.get_client_connections("client1")
        assert count == 3

        count = limiter.get_client_connections("client2")
        assert count == 0

    def test_get_statistics(self, limiter):
        """Test getting statistics"""
        # Add some test data
        limiter.active_connections["conn1"] = ConnectionInfo(
            client_id="client1", connected_at=1234567890.0, message_count=10, bytes_sent=1000
        )
        limiter.connections_by_client["client1"] = {"conn1"}

        stats = limiter.get_statistics()

        assert stats["active_connections"] == 1
        assert stats["unique_clients"] == 1
        assert stats["total_messages"] == 10
        assert stats["total_bytes_sent"] == 1000
        assert "limits" in stats


class TestFastAPIWebSocketLimiter:
    """Test FastAPI WebSocket integration"""

    @pytest.fixture
    def limiter(self):
        """Create FastAPI limiter"""
        limits = WebSocketLimits(connections_per_minute=5, messages_per_minute=10)
        return FastAPIWebSocketLimiter(limits)

    @pytest.fixture
    def mock_websocket(self):
        """Create mock WebSocket"""
        ws = AsyncMock()
        ws.client = Mock()
        ws.client.host = "192.168.1.1"
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect_allowed(self, limiter, mock_websocket):
        """Test successful connection"""
        result = await limiter.connect(mock_websocket, "client1")

        assert result is True
        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_denied(self, limiter, mock_websocket):
        """Test connection denied by rate limit"""
        # Exhaust connection limit
        for i in range(5):
            await limiter.connect(mock_websocket, "client1")

        # Should be denied
        result = await limiter.connect(mock_websocket, "client1")

        assert result is False
        mock_websocket.close.assert_called()

    @pytest.mark.asyncio
    async def test_check_message(self, limiter, mock_websocket):
        """Test message checking"""
        await limiter.connect(mock_websocket, "client1")

        result = await limiter.check_message(mock_websocket, "test message")
        assert result is True

    @pytest.mark.asyncio
    async def test_disconnect(self, limiter, mock_websocket):
        """Test disconnect"""
        await limiter.connect(mock_websocket, "client1")

        connection_id = limiter.websocket_map.get(mock_websocket)
        assert connection_id is not None

        await limiter.disconnect(mock_websocket)

        assert mock_websocket not in limiter.websocket_map

    @pytest.mark.asyncio
    async def test_custom_client_id_extraction(self, mock_websocket):
        """Test custom client ID extraction"""

        def custom_extractor(ws):
            return "custom_client_id"

        limiter = FastAPIWebSocketLimiter(get_client_id=custom_extractor)

        await limiter.connect(mock_websocket)

        # Verify custom ID was used
        connection_id = limiter.websocket_map.get(mock_websocket)
        conn_info = limiter.limiter.get_connection_info(connection_id)
        assert conn_info.client_id == "custom_client_id"


class TestSocketIOLimiter:
    """Test Socket.IO integration"""

    @pytest.fixture
    def limiter(self):
        """Create Socket.IO limiter"""
        limits = WebSocketLimits(connections_per_minute=5, messages_per_minute=10)
        return SocketIOLimiter(limits)

    @pytest.mark.asyncio
    async def test_on_connect_allowed(self, limiter):
        """Test successful connection"""
        result = await limiter.on_connect("sid_123", "192.168.1.1")
        assert result is True
        assert "sid_123" in limiter.sid_to_client

    @pytest.mark.asyncio
    async def test_on_connect_denied(self, limiter):
        """Test connection denied"""
        # Exhaust limit
        for i in range(5):
            await limiter.on_connect(f"sid_{i}", "client1")

        # Should be denied
        result = await limiter.on_connect("sid_6", "client1")
        assert result is False

    @pytest.mark.asyncio
    async def test_check_message(self, limiter):
        """Test message checking"""
        await limiter.on_connect("sid_123", "client1")

        result = await limiter.check_message("sid_123", {"data": "test"})
        assert result is True

    @pytest.mark.asyncio
    async def test_on_disconnect(self, limiter):
        """Test disconnect"""
        await limiter.on_connect("sid_123", "client1")
        await limiter.on_disconnect("sid_123")

        assert "sid_123" not in limiter.sid_to_client


class TestChannelsRateLimiter:
    """Test Django Channels integration"""

    @pytest.fixture
    def limiter(self):
        """Create Channels limiter"""
        limits = WebSocketLimits(connections_per_minute=5, messages_per_minute=10)
        return ChannelsRateLimiter(limits)

    @pytest.mark.asyncio
    async def test_check_connection(self, limiter):
        """Test connection check"""
        result = await limiter.check_connection("192.168.1.1")
        assert result is True

    @pytest.mark.asyncio
    async def test_register_connection(self, limiter):
        """Test registering connection"""
        await limiter.register_connection(
            "channel_123", "192.168.1.1", metadata={"user_id": "user_456"}
        )

        info = limiter.limiter.get_connection_info("channel_123")
        assert info.client_id == "192.168.1.1"
        assert info.metadata == {"user_id": "user_456"}

    @pytest.mark.asyncio
    async def test_unregister_connection(self, limiter):
        """Test unregistering connection"""
        await limiter.register_connection("channel_123", "192.168.1.1")
        await limiter.unregister_connection("channel_123")

        info = limiter.limiter.get_connection_info("channel_123")
        assert info is None

    @pytest.mark.asyncio
    async def test_check_message_string(self, limiter):
        """Test checking string message"""
        await limiter.register_connection("channel_123", "192.168.1.1")

        result = await limiter.check_message("channel_123", "test message")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_message_dict(self, limiter):
        """Test checking dict message"""
        await limiter.register_connection("channel_123", "192.168.1.1")

        result = await limiter.check_message("channel_123", {"data": "test"})
        assert result is True


class TestWebSocketEdgeCases:
    """Test edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_check_message_unknown_connection(self):
        """Test checking message for unknown connection"""
        limiter = WebSocketRateLimiter()

        result = await limiter.check_message("unknown_conn", message_size=100)

        assert result["allowed"] is False
        assert result["reason"] == "connection_not_found"

    @pytest.mark.asyncio
    async def test_unregister_unknown_connection(self):
        """Test unregistering unknown connection (should not crash)"""
        limiter = WebSocketRateLimiter()

        # Should not raise
        await limiter.unregister_connection("unknown_conn")

    @pytest.mark.asyncio
    async def test_multiple_clients_independent(self):
        """Test that different clients have independent limits"""
        limiter = WebSocketRateLimiter(WebSocketLimits(connections_per_minute=2))

        # Client 1 makes 2 connections
        await limiter.register_connection("conn1", "client1")
        await limiter.register_connection("conn2", "client1")

        # Client 2 should still be able to connect
        result = await limiter.check_connection("client2")
        assert result is True


class TestWebSocketIntegration:
    """Integration tests"""

    @pytest.mark.asyncio
    async def test_full_connection_lifecycle(self):
        """Test complete connection lifecycle"""
        limiter = WebSocketRateLimiter(
            WebSocketLimits(connections_per_minute=10, messages_per_minute=20, max_message_size=100)
        )

        # Check connection allowed
        assert await limiter.check_connection("client1") is True

        # Register connection
        await limiter.register_connection("conn1", "client1")

        # Send some messages
        for i in range(5):
            result = await limiter.check_message("conn1", message_size=50)
            assert result["allowed"] is True

        # Get stats
        info = limiter.get_connection_info("conn1")
        assert info.message_count == 5
        assert info.bytes_sent == 250

        # Disconnect
        await limiter.unregister_connection("conn1")

        # Connection no longer exists
        info = limiter.get_connection_info("conn1")
        assert info is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
