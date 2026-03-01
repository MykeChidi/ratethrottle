"""
RateThrottle - gRPC Rate Limiting

GRPC rate limiting with support for:
- Server interceptors (global rate limiting)
- Method-specific rate limiting
- Per-service rate limiting
- Stream rate limiting (both unary and streaming)
- Custom metadata extraction
"""

import logging
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, Optional

import grpc
from grpc import ServerInterceptor, StatusCode

logger = logging.getLogger(__name__)


@dataclass
class GRPCLimits:
    """
    Configuration for gRPC rate limits

    Args:
        requests_per_minute: Max requests per minute per client
        concurrent_requests: Max concurrent requests per client
        stream_messages_per_minute: Max messages in streams per minute

    Example:
        >>> limits = GRPCLimits(
        ...     requests_per_minute=100,
        ...     concurrent_requests=10,
        ...     stream_messages_per_minute=1000
        ... )
    """

    requests_per_minute: int = 1000
    concurrent_requests: int = 50
    stream_messages_per_minute: int = 5000


class GRPCRateLimitInterceptor(ServerInterceptor):
    """
    gRPC server interceptor for rate limiting

    Intercepts all gRPC calls and applies rate limiting based on:
    - Client IP address (default)
    - Custom metadata (configurable)
    - Method name (for per-method limits)

    Example:
        >>> from concurrent import futures
        >>> import grpc
        >>> from ratethrottle import GRPCRateLimitInterceptor, GRPCLimits
        >>>
        >>> # Create interceptor
        >>> interceptor = GRPCRateLimitInterceptor(
        ...     GRPCLimits(
        ...         requests_per_minute=100,
        ...         concurrent_requests=10
        ...     )
        ... )
        >>>
        >>> # Create server with rate limiting
        >>> server = grpc.server(
        ...     futures.ThreadPoolExecutor(max_workers=10),
        ...     interceptors=[interceptor]
        ... )
    """

    def __init__(
        self,
        limits: Optional[GRPCLimits] = None,
        storage=None,
        extract_client_id: Optional[Callable] = None,
        on_violation: Optional[Callable] = None,
        method_limits: Optional[Dict[str, GRPCLimits]] = None,
    ):
        """
        Initialize gRPC rate limit interceptor

        Args:
            limits: Default rate limits
            storage: Storage backend (defaults to in-memory)
            extract_client_id: Custom function to extract client ID from context
            on_violation: Callback for rate limit violations
            method_limits: Per-method rate limit overrides
        """

        from .core import RateThrottleCore, RateThrottleRule
        from .storage_backend import InMemoryStorage

        self.limits = limits or GRPCLimits()
        self.storage = storage or InMemoryStorage()
        self.extract_client_id = extract_client_id or self._default_extract_client_id
        self.on_violation = on_violation
        self.method_limits = method_limits or {}

        # Core rate limiter
        self.limiter = RateThrottleCore(storage=self.storage)

        # Add default rate limiting rule
        self.limiter.add_rule(
            RateThrottleRule(
                name="grpc_requests", limit=self.limits.requests_per_minute, window=60, scope="ip"
            )
        )

        # Add streaming rate limiting rule
        self.limiter.add_rule(
            RateThrottleRule(
                name="grpc_stream_messages",
                limit=self.limits.stream_messages_per_minute,
                window=60,
                scope="ip",
            )
        )

        # Track concurrent requests
        self.concurrent_requests: Dict[str, int] = {}

        logger.info(f"gRPC rate limiter initialized: {self.limits}")

    def _default_extract_client_id(self, context) -> str:
        """
        Extract client identifier from gRPC context

        Tries in order:
        1. x-forwarded-for header
        2. peer address
        3. 'unknown'
        """
        # Try to get from invocation metadata
        metadata = dict(context.invocation_metadata())

        # Check for forwarded IP
        forwarded = metadata.get("x-forwarded-for", "")
        if forwarded:
            return str(forwarded).split(",")[0].strip()

        # Try peer address
        peer = context.peer()
        if peer:
            # peer format: "ipv4:127.0.0.1:54321" or "ipv6:[::1]:54321"
            if ":" in peer:
                parts = peer.split(":")
                if len(parts) >= 2:
                    return str(parts[1] if parts[0] == "ipv4" else parts[0])

        return "unknown"

    def _get_method_name(self, handler_call_details) -> str:
        """Extract method name from handler call details"""
        method = handler_call_details.method
        # Format: /package.Service/Method
        if method:
            return str(method).split("/")[-1]
        return "unknown"

    def _get_limits_for_method(self, method_name: str) -> GRPCLimits:
        """Get rate limits for specific method"""
        return self.method_limits.get(method_name, self.limits)

    def _check_concurrent_limit(self, client_id: str) -> bool:
        """Check if concurrent request limit exceeded"""
        current = self.concurrent_requests.get(client_id, 0)
        return current < self.limits.concurrent_requests

    def _increment_concurrent(self, client_id: str):
        """Increment concurrent request counter"""
        self.concurrent_requests[client_id] = self.concurrent_requests.get(client_id, 0) + 1

    def _decrement_concurrent(self, client_id: str):
        """Decrement concurrent request counter"""
        if client_id in self.concurrent_requests:
            self.concurrent_requests[client_id] -= 1
            if self.concurrent_requests[client_id] <= 0:
                del self.concurrent_requests[client_id]

    def intercept_service(self, continuation, handler_call_details):
        """
        Intercept gRPC service calls

        This is called for every RPC to the server
        """

        def rate_limited_handler(request_or_iterator, context):
            """Wrapper that applies rate limiting"""
            # Extract client identifier
            client_id = self.extract_client_id(context)
            method_name = self._get_method_name(handler_call_details)
            method_limits = self._get_limits_for_method(method_name)  # noqa

            logger.debug(f"gRPC call: {method_name} from {client_id}")

            # Check concurrent request limit
            if not self._check_concurrent_limit(client_id):
                logger.warning(
                    f"gRPC call denied: {method_name} from {client_id} - "
                    f"concurrent limit exceeded"
                )

                if self.on_violation:
                    self.on_violation(
                        {
                            "type": "concurrent_requests",
                            "client_id": client_id,
                            "method": method_name,
                            "limit": self.limits.concurrent_requests,
                        }
                    )

                context.abort(
                    StatusCode.RESOURCE_EXHAUSTED,
                    f"Concurrent request limit exceeded. Max: {self.limits.concurrent_requests}",
                )

            # Check rate limit
            status = self.limiter.check_rate_limit(client_id, "grpc_requests")

            if not status.allowed:
                logger.warning(
                    f"gRPC call denied: {method_name} from {client_id} - "
                    f"rate limit exceeded (retry after {status.retry_after}s)"
                )

                if self.on_violation:
                    self.on_violation(
                        {
                            "type": "rate_limit",
                            "client_id": client_id,
                            "method": method_name,
                            "retry_after": status.retry_after,
                        }
                    )

                # Set metadata for client
                context.set_trailing_metadata(
                    (
                        ("x-ratelimit-limit", str(status.limit)),
                        ("x-ratelimit-remaining", str(status.remaining)),
                        ("x-ratelimit-reset", str(status.reset_time)),
                        ("retry-after", str(status.retry_after)),
                    )
                )

                context.abort(
                    StatusCode.RESOURCE_EXHAUSTED,
                    f"Rate limit exceeded. Retry after {status.retry_after} seconds.",
                )

            # Increment concurrent counter
            self._increment_concurrent(client_id)

            try:
                # Check if this is a streaming RPC
                handler = continuation(handler_call_details)

                # Wrap streaming responses
                if handler and hasattr(handler, "unary_stream"):
                    # Unary-stream: wrap response iterator
                    original_response = handler.unary_stream(request_or_iterator, context)
                    return self._rate_limit_stream(original_response, client_id, context)
                elif handler and hasattr(handler, "stream_stream"):
                    # Stream-stream: wrap both
                    return self._rate_limit_bidirectional_stream(
                        handler, request_or_iterator, client_id, context
                    )
                else:
                    # Unary-unary: execute normally
                    if handler:
                        return handler.unary_unary(request_or_iterator, context)
                    return None

            finally:
                # Decrement concurrent counter
                self._decrement_concurrent(client_id)

        # Get the actual handler
        handler = continuation(handler_call_details)

        if handler is None:
            return None

        # Wrap the handler with rate limiting
        if handler.request_streaming and handler.response_streaming:
            # Bidirectional streaming
            return grpc.stream_stream_rpc_method_handler(
                rate_limited_handler,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )
        elif handler.request_streaming:
            # Client streaming
            return grpc.stream_unary_rpc_method_handler(
                rate_limited_handler,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )
        elif handler.response_streaming:
            # Server streaming
            return grpc.unary_stream_rpc_method_handler(
                rate_limited_handler,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )
        else:
            # Unary
            return grpc.unary_unary_rpc_method_handler(
                rate_limited_handler,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

    def _rate_limit_stream(self, response_iterator, client_id: str, context):
        """Apply rate limiting to streaming responses"""
        for response in response_iterator:
            # Check stream message rate limit
            status = self.limiter.check_rate_limit(client_id, "grpc_stream_messages")

            if not status.allowed:
                logger.warning(
                    f"gRPC stream message denied for {client_id} - " f"stream rate limit exceeded"
                )

                context.abort(StatusCode.RESOURCE_EXHAUSTED, "Stream message rate limit exceeded")

            yield response

    def _rate_limit_bidirectional_stream(self, handler, request_iterator, client_id: str, context):
        """Apply rate limiting to bidirectional streams"""

        def request_generator():
            for request in request_iterator:
                # Check rate limit for incoming stream messages
                status = self.limiter.check_rate_limit(client_id, "grpc_stream_messages")

                if not status.allowed:
                    context.abort(
                        StatusCode.RESOURCE_EXHAUSTED, "Stream message rate limit exceeded"
                    )

                yield request

        # Process with rate-limited request iterator
        response_iterator = handler.stream_stream(request_generator(), context)

        # Rate limit responses
        return self._rate_limit_stream(response_iterator, client_id, context)

    def get_statistics(self) -> Dict[str, Any]:
        """Get rate limiting statistics"""
        return {
            "limits": {
                "requests_per_minute": self.limits.requests_per_minute,
                "concurrent_requests": self.limits.concurrent_requests,
                "stream_messages_per_minute": self.limits.stream_messages_per_minute,
            },
            "current_concurrent_requests": sum(self.concurrent_requests.values()),
            "unique_clients": len(self.concurrent_requests),
            "metrics": self.limiter.get_metrics(),
        }


# ============================================
# Method-level decorator
# ============================================


def grpc_ratelimit(
    limit: int, window: int = 60, scope: str = "ip", extract_client_id: Optional[Callable] = None
):
    """
    Decorator for rate limiting specific gRPC methods

    Can be used on servicer methods to apply fine-grained rate limiting.

    Args:
        limit: Maximum requests allowed
        window: Time window in seconds
        scope: Rate limit scope ('ip', 'user', etc.)
        extract_client_id: Custom function to extract client ID

    Example:
        >>> class UserService(user_pb2_grpc.UserServiceServicer):
        ...
        ...     @grpc_ratelimit(limit=10, window=60)
        ...     def GetUser(self, request, context):
        ...         # This method is rate limited to 10 req/min
        ...         user = get_user_from_db(request.user_id)
        ...         return user_pb2.User(
        ...             id=user.id,
        ...             name=user.name
        ...         )
        ...
        ...     @grpc_ratelimit(limit=100, window=60)
        ...     def ListUsers(self, request, context):
        ...         # This method has different limits
        ...         users = list_users_from_db()
        ...         for user in users:
        ...             yield user
    """
    from .core import RateThrottleCore, RateThrottleRule

    # Create method-specific limiter
    limiter = RateThrottleCore()
    rule_name = f"grpc_method_{limit}_{window}"

    limiter.add_rule(RateThrottleRule(name=rule_name, limit=limit, window=window, scope=scope))

    # Default client ID extraction
    def default_extract_client_id(context):
        metadata = dict(context.invocation_metadata())
        forwarded = metadata.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()

        peer = context.peer()
        if peer and ":" in peer:
            parts = peer.split(":")
            if len(parts) >= 2:
                return parts[1] if parts[0] == "ipv4" else parts[0]

        return "unknown"

    extract_fn = extract_client_id or default_extract_client_id

    def decorator(func):
        @wraps(func)
        def wrapper(self, request_or_iterator, context):
            # Extract client identifier
            client_id = extract_fn(context)

            # Check rate limit
            status = limiter.check_rate_limit(client_id, rule_name)

            if not status.allowed:
                # Set metadata
                context.set_trailing_metadata(
                    (
                        ("x-ratelimit-limit", str(status.limit)),
                        ("x-ratelimit-remaining", str(status.remaining)),
                        ("retry-after", str(status.retry_after)),
                    )
                )

                # Abort with rate limit error
                context.abort(
                    StatusCode.RESOURCE_EXHAUSTED,
                    f"Rate limit exceeded for this method. "
                    f"Retry after {status.retry_after} seconds.",
                )

            # Call original method
            return func(self, request_or_iterator, context)

        return wrapper

    return decorator


# ============================================
# Helper for custom metadata extraction
# ============================================


def extract_user_id_from_metadata(metadata_key: str = "user-id"):
    """
    Create a client ID extractor that uses custom metadata

    Args:
        metadata_key: Metadata key to extract user ID from

    Returns:
        Extractor function

    Example:
        >>> # In your gRPC service
        >>> extractor = extract_user_id_from_metadata('x-user-id')
        >>>
        >>> interceptor = GRPCRateLimitInterceptor(
        ...     extract_client_id=extractor
        ... )
    """

    def extractor(context) -> str:
        metadata = dict(context.invocation_metadata())
        user_id = metadata.get(metadata_key, "")

        if user_id:
            return str(user_id)

        # Fallback to IP
        peer = context.peer()
        if peer and ":" in peer:
            parts = peer.split(":")
            if len(parts) >= 2:
                return str(parts[1] if parts[0] == "ipv4" else parts[0])

        return "unknown"

    return extractor


# ============================================
# Per-service rate limiter
# ============================================


class ServiceRateLimiter:
    """
    Rate limiter for specific gRPC services

    Allows different rate limits for different services.

    Example:
        >>> # Different limits for different services
        >>> user_limiter = ServiceRateLimiter(
        ...     GRPCLimits(requests_per_minute=100)
        ... )
        >>>
        >>> admin_limiter = ServiceRateLimiter(
        ...     GRPCLimits(requests_per_minute=1000)
        ... )
        >>>
        >>> # Apply to services
        >>> user_pb2_grpc.add_UserServiceServicer_to_server(
        ...     UserService(),
        ...     server
        ... )
    """

    def __init__(self, limits: GRPCLimits, service_name: Optional[str] = None):
        """
        Initialize service-specific rate limiter

        Args:
            limits: Rate limits for this service
            service_name: Name of the service (for logging)
        """
        from .core import RateThrottleCore, RateThrottleRule

        self.limits = limits
        self.service_name = service_name or "unknown"
        self.limiter = RateThrottleCore()

        # Add service-specific rule
        self.limiter.add_rule(
            RateThrottleRule(
                name=f"grpc_service_{self.service_name}",
                limit=limits.requests_per_minute,
                window=60,
            )
        )

    def check_rate_limit(self, client_id: str, context) -> bool:
        """
        Check if request is allowed for this service

        Returns:
            True if allowed, False otherwise (also aborts context)
        """
        rule_name = f"grpc_service_{self.service_name}"
        status = self.limiter.check_rate_limit(client_id, rule_name)

        if not status.allowed:
            context.set_trailing_metadata(
                (
                    ("x-ratelimit-limit", str(status.limit)),
                    ("x-ratelimit-remaining", str(status.remaining)),
                    ("retry-after", str(status.retry_after)),
                )
            )

            context.abort(
                StatusCode.RESOURCE_EXHAUSTED,
                f"Rate limit exceeded for {self.service_name}. "
                f"Retry after {status.retry_after} seconds.",
            )
            return False

        return True
