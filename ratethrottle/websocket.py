"""
WebSocket Rate Limiting

WebSocket rate limiting with support for:
- Connection-level rate limiting
- Message-level rate limiting
- Bandwidth limiting
- Per-channel/room limits
- FastAPI, Socket.IO, Django Channels support
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class WebSocketLimits:
    """
    Configuration for WebSocket rate limits

    Args:
        connections_per_minute: Max new connections per minute per client
        messages_per_minute: Max messages per minute per connection
        bytes_per_minute: Max bytes per minute per connection (optional)
        max_concurrent_connections: Max concurrent connections per client
        max_message_size: Max size of individual message in bytes

    Example:
        >>> limits = WebSocketLimits(
        ...     connections_per_minute=10,
        ...     messages_per_minute=100,
        ...     bytes_per_minute=1048576,  # 1MB
        ...     max_concurrent_connections=5
        ... )
    """

    connections_per_minute: int = 60
    messages_per_minute: int = 1000
    bytes_per_minute: Optional[int] = None
    max_concurrent_connections: int = 10
    max_message_size: int = 65536  # 64KB


@dataclass
class ConnectionInfo:
    """Information about a WebSocket connection"""

    client_id: str
    connected_at: float
    message_count: int = 0
    bytes_sent: int = 0
    last_message_time: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class WebSocketRateLimiter:
    """
    Comprehensive WebSocket rate limiting

    Features:
    - Connection rate limiting (prevent connection spam)
    - Message rate limiting (prevent message spam)
    - Bandwidth limiting (prevent bandwidth abuse)
    - Concurrent connection limiting
    - Message size limiting

    Example:
        >>> limiter = WebSocketRateLimiter(
        ...     WebSocketLimits(
        ...         connections_per_minute=10,
        ...         messages_per_minute=100
        ...     )
        ... )
        >>>
        >>> # Check if connection allowed
        >>> if await limiter.check_connection("client_id"):
        ...     # Accept connection
        ...     await limiter.register_connection("client_id", websocket)
    """

    def __init__(
        self,
        limits: Optional[WebSocketLimits] = None,
        storage=None,
        on_violation: Optional[Callable] = None,
    ):
        """
        Initialize WebSocket rate limiter

        Args:
            limits: Rate limit configuration
            storage: Storage backend (defaults to in-memory)
            on_violation: Callback for violations
        """
        from .core import RateThrottleCore, RateThrottleRule
        from .storage_backend import InMemoryStorage

        self.limits = limits or WebSocketLimits()
        self.storage = storage or InMemoryStorage()
        self.on_violation = on_violation

        # Core rate limiter for different aspects
        self.limiter = RateThrottleCore(storage=self.storage)

        # Connection rate limiting
        self.limiter.add_rule(
            RateThrottleRule(
                name="ws_connections",
                limit=self.limits.connections_per_minute,
                window=60,
                scope="ip",
            )
        )

        # Message rate limiting
        self.limiter.add_rule(
            RateThrottleRule(
                name="ws_messages", limit=self.limits.messages_per_minute, window=60, scope="ip"
            )
        )

        # Bandwidth limiting (if configured)
        if self.limits.bytes_per_minute:
            self.limiter.add_rule(
                RateThrottleRule(
                    name="ws_bandwidth", limit=self.limits.bytes_per_minute, window=60, scope="ip"
                )
            )

        # Track active connections
        self.active_connections: Dict[str, ConnectionInfo] = {}
        self.connections_by_client: Dict[str, set] = defaultdict(set)

        logger.info(f"WebSocket rate limiter initialized: {self.limits}")

    async def check_connection(self, client_id: str) -> bool:
        """
        Check if new connection is allowed

        Args:
            client_id: Client identifier (IP, user ID, etc.)

        Returns:
            True if connection allowed, False otherwise

        Example:
            >>> if await limiter.check_connection("192.168.1.1"):
            ...     await websocket.accept()
        """
        try:
            # Check concurrent connection limit
            current_connections = len(self.connections_by_client[client_id])
            if current_connections >= self.limits.max_concurrent_connections:
                logger.warning(
                    f"Connection denied: {client_id} - "
                    f"max concurrent connections reached ({current_connections})"
                )

                if self.on_violation:
                    self.on_violation(
                        {
                            "type": "concurrent_connections",
                            "client_id": client_id,
                            "current": current_connections,
                            "limit": self.limits.max_concurrent_connections,
                        }
                    )

                return False

            # Check connection rate limit
            status = self.limiter.check_rate_limit(client_id, "ws_connections")

            if not status.allowed:
                logger.warning(
                    f"Connection denied: {client_id} - "
                    f"connection rate limit exceeded (retry after {status.retry_after}s)"
                )

                if self.on_violation:
                    self.on_violation(
                        {
                            "type": "connection_rate",
                            "client_id": client_id,
                            "retry_after": status.retry_after,
                        }
                    )

                return False

            logger.debug(f"Connection allowed: {client_id}")
            return True

        except Exception as e:
            logger.error(f"Error checking connection for {client_id}: {e}")
            return False

    async def register_connection(
        self, connection_id: str, client_id: str, metadata: Optional[Dict] = None
    ) -> None:
        """
        Register a new WebSocket connection

        Args:
            connection_id: Unique connection identifier
            client_id: Client identifier
            metadata: Optional connection metadata

        Example:
            >>> await limiter.register_connection(
            ...     connection_id="conn_123",
            ...     client_id="192.168.1.1",
            ...     metadata={"user_id": "user_456"}
            ... )
        """
        try:
            conn_info = ConnectionInfo(
                client_id=client_id, connected_at=time.time(), metadata=metadata or {}
            )

            self.active_connections[connection_id] = conn_info
            self.connections_by_client[client_id].add(connection_id)

            logger.info(
                f"Connection registered: {connection_id} from {client_id} "
                f"(total: {len(self.connections_by_client[client_id])})"
            )

        except Exception as e:
            logger.error(f"Error registering connection {connection_id}: {e}")

    async def unregister_connection(self, connection_id: str) -> None:
        """
        Unregister a WebSocket connection

        Args:
            connection_id: Connection identifier

        Example:
            >>> await limiter.unregister_connection("conn_123")
        """
        try:
            if connection_id in self.active_connections:
                conn_info = self.active_connections[connection_id]
                client_id = conn_info.client_id

                # Remove from tracking
                del self.active_connections[connection_id]
                self.connections_by_client[client_id].discard(connection_id)

                # Cleanup empty entries
                if not self.connections_by_client[client_id]:
                    del self.connections_by_client[client_id]

                logger.info(f"Connection unregistered: {connection_id}")

        except Exception as e:
            logger.error(f"Error unregistering connection {connection_id}: {e}")

    async def check_message(self, connection_id: str, message_size: int = 0) -> Dict[str, Any]:
        """
        Check if message is allowed

        Args:
            connection_id: Connection identifier
            message_size: Size of message in bytes

        Returns:
            Dict with 'allowed' (bool) and 'reason' (str)

        Example:
            >>> result = await limiter.check_message("conn_123", len(message))
            >>> if result['allowed']:
            ...     await websocket.send(message)
        """
        try:
            # Get connection info
            if connection_id not in self.active_connections:
                return {"allowed": False, "reason": "connection_not_found"}

            conn_info = self.active_connections[connection_id]
            client_id = conn_info.client_id

            # Check message size limit
            if message_size > self.limits.max_message_size:
                logger.warning(
                    f"Message denied: {connection_id} - "
                    f"message too large ({message_size} > {self.limits.max_message_size})"
                )

                if self.on_violation:
                    self.on_violation(
                        {
                            "type": "message_size",
                            "connection_id": connection_id,
                            "client_id": client_id,
                            "size": message_size,
                            "limit": self.limits.max_message_size,
                        }
                    )

                return {
                    "allowed": False,
                    "reason": "message_too_large",
                    "max_size": self.limits.max_message_size,
                }

            # Check message rate limit
            status = self.limiter.check_rate_limit(client_id, "ws_messages")

            if not status.allowed:
                logger.warning(f"Message denied: {connection_id} - " f"message rate limit exceeded")

                if self.on_violation:
                    self.on_violation(
                        {
                            "type": "message_rate",
                            "connection_id": connection_id,
                            "client_id": client_id,
                            "retry_after": status.retry_after,
                        }
                    )

                return {
                    "allowed": False,
                    "reason": "rate_limit_exceeded",
                    "retry_after": status.retry_after,
                }

            # Check bandwidth limit (if configured)
            if self.limits.bytes_per_minute:
                bandwidth_status = self.limiter.check_rate_limit(client_id, "ws_bandwidth")

                # Use remaining as available bytes
                if bandwidth_status.remaining < message_size:
                    logger.warning(
                        f"Message denied: {connection_id} - " f"bandwidth limit exceeded"
                    )

                    if self.on_violation:
                        self.on_violation(
                            {
                                "type": "bandwidth",
                                "connection_id": connection_id,
                                "client_id": client_id,
                                "message_size": message_size,
                                "remaining": bandwidth_status.remaining,
                            }
                        )

                    return {
                        "allowed": False,
                        "reason": "bandwidth_exceeded",
                        "remaining_bytes": bandwidth_status.remaining,
                    }

            # Update connection stats
            conn_info.message_count += 1
            conn_info.bytes_sent += message_size
            conn_info.last_message_time = time.time()

            logger.debug(
                f"Message allowed: {connection_id} "
                f"(size: {message_size}, total: {conn_info.message_count})"
            )

            return {"allowed": True, "reason": "ok"}

        except Exception as e:
            logger.error(f"Error checking message for {connection_id}: {e}")
            return {"allowed": False, "reason": "internal_error"}

    def get_connection_info(self, connection_id: str) -> Optional[ConnectionInfo]:
        """Get information about a connection"""
        return self.active_connections.get(connection_id)

    def get_client_connections(self, client_id: str) -> int:
        """Get number of active connections for a client"""
        return len(self.connections_by_client.get(client_id, set()))

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get WebSocket statistics

        Returns:
            Statistics dictionary
        """
        total_connections = len(self.active_connections)
        total_clients = len(self.connections_by_client)

        total_messages = sum(conn.message_count for conn in self.active_connections.values())

        total_bytes = sum(conn.bytes_sent for conn in self.active_connections.values())

        return {
            "active_connections": total_connections,
            "unique_clients": total_clients,
            "total_messages": total_messages,
            "total_bytes_sent": total_bytes,
            "limits": {
                "connections_per_minute": self.limits.connections_per_minute,
                "messages_per_minute": self.limits.messages_per_minute,
                "bytes_per_minute": self.limits.bytes_per_minute,
                "max_concurrent": self.limits.max_concurrent_connections,
                "max_message_size": self.limits.max_message_size,
            },
        }

    def __repr__(self) -> str:
        return (
            f"WebSocketRateLimiter("
            f"connections={len(self.active_connections)}, "
            f"clients={len(self.connections_by_client)})"
        )


# ============================================
# FastAPI WebSocket Integration
# ============================================


class FastAPIWebSocketLimiter:
    """
    FastAPI WebSocket rate limiting integration

    Example:
        >>> from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        >>> from ratethrottle import FastAPIWebSocketLimiter
        >>>
        >>> app = FastAPI()
        >>> limiter = FastAPIWebSocketLimiter()
        >>>
        >>> @app.websocket("/ws/{client_id}")
        >>> async def websocket_endpoint(websocket: WebSocket, client_id: str):
        ...     if not await limiter.connect(websocket, client_id):
        ...         return
        ...
        ...     try:
        ...         while True:
        ...             data = await websocket.receive_text()
        ...
        ...             if not await limiter.check_message(websocket, data):
        ...                 await websocket.send_text("Rate limit exceeded")
        ...                 continue
        ...
        ...             await websocket.send_text(f"Echo: {data}")
        ...
        ...     except WebSocketDisconnect:
        ...         await limiter.disconnect(websocket)
    """

    def __init__(
        self, limits: Optional[WebSocketLimits] = None, get_client_id: Optional[Callable] = None
    ):
        """
        Initialize FastAPI WebSocket limiter

        Args:
            limits: Rate limit configuration
            get_client_id: Custom function to extract client ID from websocket
        """
        self.limiter = WebSocketRateLimiter(limits)
        self.get_client_id = get_client_id or self._default_get_client_id

        # Map websocket to connection_id
        self.websocket_map: Dict[Any, str] = {}

    def _default_get_client_id(self, websocket) -> str:
        """Extract client ID from WebSocket"""
        # Try to get from headers
        client_ip = websocket.client.host if websocket.client else "unknown"
        return client_ip

    async def connect(self, websocket, client_id: Optional[str] = None) -> bool:
        """
        Handle WebSocket connection with rate limiting

        Args:
            websocket: FastAPI WebSocket instance
            client_id: Optional client ID (extracted from websocket if not provided)

        Returns:
            True if connection accepted, False if rejected
        """
        if client_id is None:
            client_id = self.get_client_id(websocket)

        # Check if connection allowed
        if not await self.limiter.check_connection(client_id):
            await websocket.close(code=1008, reason="Rate limit exceeded")
            return False

        # Accept connection
        await websocket.accept()

        # Register connection
        connection_id = f"ws_{id(websocket)}"
        await self.limiter.register_connection(connection_id, client_id)

        # Map for tracking
        self.websocket_map[websocket] = connection_id

        return True

    async def check_message(self, websocket, message: Union[str, bytes]) -> bool:
        """
        Check if message is allowed

        Args:
            websocket: FastAPI WebSocket instance
            message: Message content

        Returns:
            True if allowed, False otherwise
        """
        connection_id = self.websocket_map.get(websocket)
        if not connection_id:
            return False

        message_size = len(message) if isinstance(message, (str, bytes)) else 0

        result = await self.limiter.check_message(connection_id, message_size)
        return bool(result["allowed"])

    async def disconnect(self, websocket) -> None:
        """Handle WebSocket disconnection"""
        connection_id = self.websocket_map.pop(websocket, None)
        if connection_id:
            await self.limiter.unregister_connection(connection_id)


# ============================================
# Socket.IO Integration
# ============================================


class SocketIOLimiter:
    """
    Socket.IO rate limiting integration

    Example:
        >>> from socketio import AsyncServer
        >>> from ratethrottle import SocketIOLimiter
        >>>
        >>> sio = AsyncServer(async_mode='asgi')
        >>> limiter = SocketIOLimiter()
        >>>
        >>> @sio.event
        >>> async def connect(sid, environ):
        ...     client_ip = environ.get('REMOTE_ADDR')
        ...     return await limiter.on_connect(sid, client_ip)
        >>>
        >>> @sio.event
        >>> async def message(sid, data):
        ...     if not await limiter.check_message(sid, data):
        ...         await sio.emit('error', {'message': 'Rate limit'}, to=sid)
        ...         return
        ...
        ...     await sio.emit('response', {'data': data}, to=sid)
        >>>
        >>> @sio.event
        >>> async def disconnect(sid):
        ...     await limiter.on_disconnect(sid)
    """

    def __init__(self, limits: Optional[WebSocketLimits] = None):
        """Initialize Socket.IO rate limiter"""
        self.limiter = WebSocketRateLimiter(limits)
        self.sid_to_client: Dict[str, str] = {}

    async def on_connect(self, sid: str, client_id: str) -> bool:
        """
        Handle Socket.IO connection

        Returns:
            True to accept, False to reject
        """
        if not await self.limiter.check_connection(client_id):
            return False

        await self.limiter.register_connection(sid, client_id)
        self.sid_to_client[sid] = client_id

        return True

    async def check_message(self, sid: str, data: Any) -> bool:
        """Check if message is allowed"""
        import json

        # Estimate message size
        try:
            message_size = len(json.dumps(data))
        except Exception:
            message_size = len(str(data))

        result = await self.limiter.check_message(sid, message_size)
        return bool(result["allowed"])

    async def on_disconnect(self, sid: str) -> None:
        """Handle Socket.IO disconnection"""
        await self.limiter.unregister_connection(sid)
        self.sid_to_client.pop(sid, None)


# ============================================
# Django Channels Integration
# ============================================


class ChannelsRateLimiter:
    """
    Django Channels WebSocket rate limiting

    Example:
        >>> from channels.generic.websocket import AsyncWebsocketConsumer
        >>> from ratethrottle import ChannelsRateLimiter
        >>>
        >>> limiter = ChannelsRateLimiter()
        >>>
        >>> class ChatConsumer(AsyncWebsocketConsumer):
        ...     async def connect(self):
        ...         client_id = self.scope['client'][0]
        ...         if await limiter.check_connection(client_id):
        ...             await self.accept()
        ...             await limiter.register_connection(self.channel_name, client_id)
        ...         else:
        ...             await self.close()
        ...
        ...     async def receive(self, text_data):
        ...         if not await limiter.check_message(self.channel_name, text_data):
        ...             await self.send(text_data="Rate limit exceeded")
        ...             return
        ...
        ...         await self.send(text_data=f"Echo: {text_data}")
        ...
        ...     async def disconnect(self, close_code):
        ...         await limiter.unregister_connection(self.channel_name)
    """

    def __init__(self, limits: Optional[WebSocketLimits] = None):
        """Initialize Django Channels rate limiter"""
        self.limiter = WebSocketRateLimiter(limits)

    async def check_connection(self, client_id: str) -> bool:
        """Check if connection is allowed"""
        return await self.limiter.check_connection(client_id)

    async def register_connection(
        self, channel_name: str, client_id: str, metadata: Optional[Dict] = None
    ) -> None:
        """Register a new connection"""
        await self.limiter.register_connection(channel_name, client_id, metadata)

    async def unregister_connection(self, channel_name: str) -> None:
        """Unregister a connection"""
        await self.limiter.unregister_connection(channel_name)

    async def check_message(self, channel_name: str, message: Union[str, bytes, dict]) -> bool:
        """Check if message is allowed"""
        import json

        # Estimate message size
        if isinstance(message, dict):
            message_size = len(json.dumps(message))
        elif isinstance(message, (str, bytes)):
            message_size = len(message)
        else:
            message_size = len(str(message))

        result = await self.limiter.check_message(channel_name, message_size)
        return bool(result["allowed"])
