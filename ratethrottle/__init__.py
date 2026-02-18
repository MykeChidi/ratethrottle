"""
RateThrottle - Production-grade rate limiting and DDoS protection

A comprehensive rate limiting library for Python web applications with
enterprise features including DDoS protection, analytics, and multi-framework support.
"""

import logging
from typing import Optional

from .core import RateThrottleCore, RateThrottleRule
from .storage_backend import StorageBackend, InMemoryStorage
from .config import ConfigManager
from .ddos import DDoSProtection
from .analytics import RateThrottleAnalytics
from .helpers import create_limiter

__version__ = "1.0.0"
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

    elif name in ["StarletteRateLimitMiddleware", "WSGIRateLimitMiddleware"]:
        from .middleware import StarletteRateLimitMiddleware, WSGIRateLimitMiddleware  # noqa

        return locals()[name]

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
