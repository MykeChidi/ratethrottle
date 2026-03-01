"""
RateThrottle - Production-grade rate limiting and DDoS protection

A comprehensive rate limiting library for Python web applications with enterprise features
including DDoS protection, analytics, multi-framework support and multi protocol support.
"""

import logging
from typing import Optional

from .analytics import RateThrottleAnalytics
from .config import ConfigManager
from .core import RateThrottleCore, RateThrottleRule
from .ddos import DDoSProtection
from .graphQL import (
    AriadneRateLimiter,
    ComplexityAnalyzer,
    DepthAnalyzer,
    GraphQLLimits,
    GraphQLRateLimiter,
)
from .gRPC import (
    GRPCLimits,
    GRPCRateLimitInterceptor,
    ServiceRateLimiter,
    grpc_ratelimit,
)
from .helpers import create_limiter, get_client_ip
from .middleware import (
    DjangoRateLimitMiddleware,
    FastAPIRateLimiter,
    FlaskRateLimiter,
    StarletteRateLimitMiddleware,
    WSGIRateLimitMiddleware,
    django_ratelimit,
)
from .storage_backend import InMemoryStorage, RedisStorage, StorageBackend
from .websocket import (
    ChannelsRateLimiter,
    FastAPIWebSocketLimiter,
    SocketIOLimiter,
    WebSocketLimits,
    WebSocketRateLimiter,
)

__version__ = "1.2.0"
__author__ = "MykeChidi"
__license__ = "MIT"
__all__ = [
    # Core
    "RateThrottleCore",
    "RateThrottleRule",
    "RateThrottleStatus",
    "RateThrottleViolation",
    # Storage
    "StorageBackend",
    "InMemoryStorage",
    "RedisStorage",
    # Middleware
    "FlaskRateLimiter",
    "FastAPIRateLimiter",
    "DjangoRateLimitMiddleware",
    "django_ratelimit",
    "StarletteRateLimitMiddleware",
    "WSGIRateLimitMiddleware",
    # Config & Protection
    "ConfigManager",
    "DDoSProtection",
    "RateThrottleAnalytics",
    # Helpers
    "create_limiter",
    "get_client_ip",
    # Websocket
    "WebSocketLimits",
    "WebSocketRateLimiter",
    "FastAPIWebSocketLimiter",
    "SocketIOLimiter",
    "ChannelsRateLimiter",
    # GRPC
    "GRPCLimits",
    "GRPCRateLimitInterceptor",
    "grpc_ratelimit",
    "ServiceRateLimiter",
    # GraphQL
    "GraphQLLimits",
    "GraphQLRateLimiter",
    "ComplexityAnalyzer",
    "DepthAnalyzer",
    "AriadneRateLimiter",
]


# Lazy imports to avoid import errors when optional dependencies are missing
def __getattr__(name: str):
    """Lazy import for optional components"""

    if name == "RedisStorage":
        try:
            from .storage_backend import RedisStorage

            return RedisStorage
        except ImportError as e:
            raise ImportError(
                "RedisStorage requires 'redis' package. "
                "Install it with: pip install ratethrottle[redis]"
            ) from e

    # Middleware imports
    elif name == "FlaskRateLimiter":
        try:
            from .middleware import FlaskRateLimiter

            return FlaskRateLimiter
        except ImportError as e:
            raise ImportError(
                "FlaskRateLimiter requires 'flask' package. "
                "Install it with: pip install ratethrottle[flask]"
            ) from e

    elif name == "FastAPIRateLimiter":
        try:
            from .middleware import FastAPIRateLimiter

            return FastAPIRateLimiter
        except ImportError as e:
            raise ImportError(
                "FastAPIRateLimiter requires 'fastapi' package. "
                "Install it with: pip install ratethrottle[fastapi]"
            ) from e

    elif name in ["DjangoRateLimitMiddleware", "django_ratelimit"]:
        try:
            from .middleware import DjangoRateLimitMiddleware, django_ratelimit  # noqa

            return locals()[name]
        except ImportError as e:
            raise ImportError(
                "Django components require 'django' package. "
                "Install it with: pip install ratethrottle[django]"
            ) from e

    elif name == "FastAPIWebSocketLimiter":
        try:
            from .websocket import FastAPIWebSocketLimiter

            return FastAPIWebSocketLimiter
        except ImportError as e:
            raise ImportError(
                "FastAPIWebSocketLimiter requires 'fastapi' package. "
                "Install it with: pip install ratethrottle[fastapi]"
            ) from e

    elif name == "SocketIOLimiter":
        try:
            from .websocket import SocketIOLimiter

            return SocketIOLimiter
        except ImportError as e:
            raise ImportError(
                "SocketIOLimiter requires 'python-socketio' package. "
                "Install it with: pip install ratethrottle[websocket]"
            ) from e

    elif name == "ChannelsRateLimiter":
        try:
            from .websocket import ChannelsRateLimiter

            return ChannelsRateLimiter
        except ImportError as e:
            raise ImportError(
                "ChannelsRateLimiter requires 'channels' package. "
                "Install it with: pip install ratethrottle[websocket]"
            ) from e

    # gRPC components (requires grpcio)
    elif name in [
        "GRPCRateLimitInterceptor",
        "grpc_ratelimit",
        "ServiceRateLimiter",
    ]:
        try:
            from .gRPC import (  # noqa
                GRPCRateLimitInterceptor,
                ServiceRateLimiter,
                grpc_ratelimit,
            )

            return locals()[name]
        except ImportError as e:
            raise ImportError(
                "gRPC components require 'grpcio' package. "
                "Install it with: pip install ratethrottle[grpc]"
            ) from e

    # GraphQL components (requires graphql-core)
    elif name in [
        "GraphQLRateLimiter",
        "ComplexityAnalyzer",
        "DepthAnalyzer",
        "AriadneRateLimiter",
    ]:
        try:
            from .graphQL import (  # noqa
                AriadneRateLimiter,
                ComplexityAnalyzer,
                DepthAnalyzer,
                GraphQLRateLimiter,
            )

            return locals()[name]
        except ImportError as e:
            raise ImportError(
                "GraphQL components require 'graphql-core' package. "
                "Install it with: pip install ratethrottle[graphql]"
            ) from e

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def get_version() -> str:
    """Return the current version"""
    return __version__


def configure_logging(level: int = logging.INFO, handler: Optional[logging.Handler] = None):
    """
    Configure logging for RateThrottle

    Args:
        level: Logging level (logging.DEBUG, logging.INFO, etc.)
        handler: Custom logging handler (default: StreamHandler)
    """
    logger = logging.getLogger("ratethrottle")
    logger.setLevel(level)

    if handler is None:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)

    logger.addHandler(handler)
