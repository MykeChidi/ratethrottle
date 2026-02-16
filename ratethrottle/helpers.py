"""
Helper functions for RateThrottle
"""

import logging
from typing import List, Optional

from .core import RateThrottleCore
from .exceptions import ConfigurationError
from .storage_backend import InMemoryStorage, StorageBackend

logger = logging.getLogger(__name__)


def create_limiter(
    storage: str = "memory", redis_url: Optional[str] = None, **storage_kwargs
) -> RateThrottleCore:
    """
    Quick start helper to create a rate limiter

    Args:
        storage: Storage type - 'memory' or 'redis'
        redis_url: Redis connection URL (required if storage='redis')
        **storage_kwargs: Additional arguments to pass to storage backend

    Returns:
        RateThrottleCore: Configured rate limiter instance

    Raises:
        ConfigurationError: If configuration is invalid
        ImportError: If required packages are missing

    Examples:
        >>> # In-memory storage (single instance)
        >>> limiter = create_limiter()

        >>> # Redis storage (distributed)
        >>> limiter = create_limiter('redis', 'redis://localhost:6379/0')

        >>> # Redis with connection pool
        >>> limiter = create_limiter(
        ...     'redis',
        ...     'redis://localhost:6379/0',
        ...     max_connections=50,
        ...     decode_responses=True
        ... )
    """
    storage_backend: StorageBackend

    if storage == "memory":
        logger.info("Creating rate limiter with in-memory storage")
        storage_backend = InMemoryStorage()

    elif storage == "redis":
        if not redis_url:
            raise ConfigurationError(
                "redis_url is required when using Redis storage. "
                "Example: create_limiter('redis', 'redis://localhost:6379/0')"
            )

        try:
            import redis

            from .storage_backend import RedisStorage
        except ImportError as e:
            raise ImportError(
                "Redis storage requires 'redis' package. "
                "Install it with: pip install ratethrottle[redis]"
            ) from e

        try:
            logger.info(f"Creating rate limiter with Redis storage: {redis_url}")

            # Parse connection arguments
            connection_kwargs = {
                "decode_responses": storage_kwargs.pop("decode_responses", False),
                "socket_timeout": storage_kwargs.pop("socket_timeout", 5),
                "socket_connect_timeout": storage_kwargs.pop("socket_connect_timeout", 5),
                "retry_on_timeout": storage_kwargs.pop("retry_on_timeout", True),
                "health_check_interval": storage_kwargs.pop("health_check_interval", 30),
            }

            # Add any remaining kwargs
            connection_kwargs.update(storage_kwargs)

            # Create Redis client
            redis_client = redis.from_url(redis_url, **connection_kwargs)

            # Test connection
            redis_client.ping()
            logger.info("Successfully connected to Redis")

            storage_backend = RedisStorage(redis_client)

        except redis.ConnectionError as e:
            raise ConfigurationError(f"Failed to connect to Redis at {redis_url}: {e}") from e
        except Exception as e:
            raise ConfigurationError(f"Error creating Redis storage backend: {e}") from e

    else:
        raise ConfigurationError(
            f"Unknown storage type: {storage}. " f"Valid options are: 'memory', 'redis'"
        )

    return RateThrottleCore(storage=storage_backend)


def parse_rate_limit(rate_string: str) -> tuple[int, int]:
    """
    Parse rate limit string into limit and window

    Args:
        rate_string: Rate limit string (e.g., "100/minute", "5/second", "1000/hour")

    Returns:
        tuple: (limit: int, window_seconds: int)

    Raises:
        ValueError: If rate string format is invalid

    Examples:
        >>> parse_rate_limit("100/minute")
        (100, 60)
        >>> parse_rate_limit("5/second")
        (5, 1)
        >>> parse_rate_limit("1000/hour")
        (1000, 3600)
    """
    if not isinstance(rate_string, str):
        raise ValueError("Rate string must be a string")

    if "/" not in rate_string:
        raise ValueError("Rate string must contain '/' separator")

    parts = rate_string.strip().split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid rate limit format: '{rate_string}'")

    limit_str, period = parts

    try:
        limit = int(limit_str.strip())
    except ValueError:
        raise ValueError(f"Invalid rate limit format: '{rate_string}")

    if limit <= 0:
        raise ValueError(f"Limit must be positive, got {limit}")

    period = period.strip().lower()

    # Map period names to seconds
    period_map = {
        "second": 1,
        "seconds": 1,
        "sec": 1,
        "s": 1,
        "minute": 60,
        "minutes": 60,
        "min": 60,
        "m": 60,
        "hour": 3600,
        "hours": 3600,
        "hr": 3600,
        "h": 3600,
        "day": 86400,
        "days": 86400,
        "d": 86400,
    }

    if period not in period_map:
        raise ValueError(f"Unknown time period: {period}")

    window = period_map[period]
    return limit, window


def get_client_ip(
    request, trusted_proxies: Optional[List[str]] = None, default="0.0.0.0"  # nosec B104
) -> str:
    """
    Extract client IP address from request, considering proxy headers

    Args:
        request: HTTP request object (Flask, Django, FastAPI, etc.)
        trusted_proxies: List of trusted proxy IP addresses

    Returns:
        str: Client IP address or default if not found

    Examples:
        >>> # Flask
        >>> ip = get_client_ip(request)

        >>> # With trusted proxies
        >>> ip = get_client_ip(request, ['10.0.0.1', '10.0.0.2'])
    """
    # Try different ways to get headers based on framework
    headers = {}

    # Flask/Werkzeug
    if hasattr(request, "headers"):
        headers = request.headers
    # Django
    elif hasattr(request, "META"):
        headers = request.META
    # FastAPI/Starlette
    elif hasattr(request, "headers"):
        headers = dict(request.headers)

    # Try X-Forwarded-For header
    x_forwarded_for = (
        headers.get("X-Forwarded-For")
        or headers.get("HTTP_X_FORWARDED_FOR")
        or headers.get("x-forwarded-for", "")
    )

    if x_forwarded_for:
        # X-Forwarded-For can contain multiple IPs: "client, proxy1, proxy2"
        ips = [ip.strip() for ip in x_forwarded_for.split(",")]

        if trusted_proxies:
            # Find the first IP that's not a trusted proxy
            for ip in ips:
                if ip not in trusted_proxies:
                    return ip

        # Return the first (leftmost) IP
        return ips[0]

    # Try X-Real-IP header
    x_real_ip = (
        headers.get("X-Real-IP") or headers.get("HTTP_X_REAL_IP") or headers.get("x-real-ip")
    )

    if x_real_ip:
        return x_real_ip.strip()

    # Fallback to remote address
    if hasattr(request, "remote_addr") and request.remote_addr:
        return request.remote_addr
    elif hasattr(request, "client") and request.client:
        return request.client.host
    elif hasattr(request, "META") and request.META.get("REMOTE_ADDR"):
        return request.META.get("REMOTE_ADDR")

    return default
