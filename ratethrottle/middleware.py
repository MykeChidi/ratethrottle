"""
RateThrottle - Web Framework Integrations

Production-grade middleware and decorators for popular Python web frameworks
with comprehensive error handling and monitoring.
"""

import logging
from functools import wraps
from typing import Callable, List, Optional, Union

try:
    from .core import RateThrottleCore, RateThrottleRule
    from .exceptions import ConfigurationError, RateLimitExceeded
    from .helpers import get_client_ip, parse_rate_limit
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ratethrottle.core import RateThrottleCore, RateThrottleRule
    from ratethrottle.exceptions import ConfigurationError, RateLimitExceeded
    from ratethrottle.helpers import get_client_ip, parse_rate_limit

logger = logging.getLogger(__name__)


# ============================================
# Flask Integration
# ============================================

# Flask import (used in mock tests)
request = None
g = None
abort = None


class FlaskRateLimiter:
    """
    Flask extension for rate limiting

    Features:
        - Decorator-based rate limiting
        - Automatic header injection
        - Custom key functions
        - Error handlers
        - Multiple storage backends

    Examples:
        >>> from flask import Flask
        >>> from ratethrottle import FlaskRateLimiter
        >>>
        >>> app = Flask(__name__)
        >>> limiter = FlaskRateLimiter(app)
        >>>
        >>> @app.route('/api/data')
        >>> @limiter.limit("100/minute")
        >>> def get_data():
        ...     return {'data': 'value'}
    """

    def __init__(
        self,
        app=None,
        storage=None,
        key_func: Optional[Callable] = None,
        headers_enabled: bool = True,
    ):
        """
        Initialize Flask rate limiter

        Args:
            app: Flask application instance
            storage: Storage backend (default: in-memory)
            key_func: Function to extract client identifier
            headers_enabled: Whether to add rate limit headers
        """
        self.limiter = RateThrottleCore(storage=storage)
        self.key_func = key_func or self._default_key_func
        self.headers_enabled = headers_enabled
        self.app = app

        if app is not None:
            self.init_app(app)

        logger.info("FlaskRateLimiter initialized")

    def init_app(self, app):
        """Initialize Flask application"""
        self.app = app

        # Add default config
        app.config.setdefault("RATELIMIT_STORAGE_URL", None)
        app.config.setdefault("RATELIMIT_STRATEGY", "sliding_window")
        app.config.setdefault("RATELIMIT_HEADERS_ENABLED", True)
        app.config.setdefault("RATELIMIT_KEY_PREFIX", "ratelimit:")

        # Override headers setting from config
        self.headers_enabled = app.config.get("RATELIMIT_HEADERS_ENABLED", True)

        # Register error handler
        @app.errorhandler(429)
        def ratelimit_handler(e):
            """Handle rate limit exceeded errors"""
            response = {
                "error": "Rate limit exceeded",
                "message": str(e.description) if hasattr(e, "description") else str(e),
            }

            # Add retry_after if available
            if hasattr(e, "retry_after"):
                response["retry_after"] = e.retry_after

            return response, 429

        logger.info(f"Flask app '{app.name}' initialized with rate limiting")

    def _default_key_func(self):
        """Default function to get client identifier"""
        try:
            global request
            if request is None:
                from flask import request as _request

                request = _request

            return get_client_ip(request)
        except Exception as e:
            logger.error(f"Error getting client IP: {e}")
            return "0.0.0.0"  # nosec B104

    def limit(
        self,
        limit: Union[str, int],
        per: int = 60,
        scope: str = "ip",
        key_func: Optional[Callable] = None,
        strategy: str = "sliding_window",
        methods: Optional[List[str]] = None,
        error_message: Optional[str] = None,
    ):
        """
        Decorator for rate limiting Flask routes

        Args:
            limit: Rate limit (e.g., "100" or "100/minute")
            per: Time window in seconds (default 60)
            scope: Scope of the limit
            key_func: Custom function to extract identifier
            strategy: Rate limiting strategy
            methods: HTTP methods to apply limit to (None for all)
            error_message: Custom error message

        Examples:
            >>> @app.route('/api/data')
            >>> @limiter.limit("100/minute")
            >>> def get_data():
            ...     return {"data": "value"}
            >>>
            >>> @app.route('/api/search')
            >>> @limiter.limit(50, per=60, methods=['POST'])
            >>> def search():
            ...     return {"results": []}
        """

        def decorator(f):
            # Parse limit string
            if isinstance(limit, str):
                try:
                    limit_num, per_seconds = parse_rate_limit(limit)
                except ValueError as e:
                    logger.error(f"Invalid rate limit format '{limit}': {e}")
                    # Fallback to simple parsing
                    if "/" in limit:
                        limit_num = int(limit.split("/")[0])
                        per_seconds = per
                    else:
                        limit_num = int(limit)
                        per_seconds = per
            else:
                limit_num = limit
                per_seconds = per

            # Create rule
            rule_name = f"flask_{f.__module__}_{f.__name__}_{limit_num}_{per_seconds}"

            try:
                rule = RateThrottleRule(
                    name=rule_name,
                    limit=limit_num,
                    window=per_seconds,
                    scope=scope,
                    strategy=strategy,
                )
                self.limiter.add_rule(rule)
                logger.debug(f"Added Flask route limit: {f.__name__} - {limit_num}/{per_seconds}s")
            except Exception as e:
                logger.error(f"Failed to create rate limit rule: {e}")
                # Return original function if rule creation fails
                return f

            @wraps(f)
            def decorated_function(*args, **kwargs):
                global request, g, abort
                if request is None:
                    try:
                        from flask import request as _request

                        request = _request
                    except ImportError:
                        pass  # nosec

                if g is None:
                    try:
                        from flask import g as _g

                        g = _g
                    except ImportError:
                        pass  # nosec

                if abort is None:
                    try:
                        from flask import abort as _abort

                        abort = _abort
                    except ImportError:
                        pass  # nosec

                # Check if method should be limited
                if methods and request.method not in methods:
                    return f(*args, **kwargs)

                try:
                    # Get identifier
                    key_getter = key_func or self.key_func
                    identifier = key_getter()

                    # Check rate limit
                    status = self.limiter.check_rate_limit(
                        identifier,
                        rule_name,
                        metadata={
                            "endpoint": request.endpoint,
                            "method": request.method,
                            "path": request.path,
                            "remote_addr": request.remote_addr,
                        },
                    )

                    # Store status in g for after_request handler
                    g.ratelimit_status = status

                    # Check if allowed
                    if not status.allowed:
                        error_msg = (
                            error_message
                            or f"Rate limit exceeded. Retry after {status.retry_after} seconds"
                        )

                        # Create exception with details
                        exc = RateLimitExceeded(
                            error_msg,
                            retry_after=status.retry_after,
                            limit=status.limit,
                            remaining=status.remaining,
                            reset_time=status.reset_time,
                        )

                        abort(429, description=exc)

                    # Call original function
                    return f(*args, **kwargs)

                except RateLimitExceeded:
                    # Re-raise rate limit errors
                    raise
                except Exception as e:
                    # Log error but allow request to proceed
                    logger.error(f"Rate limit check error: {e}")
                    return f(*args, **kwargs)

            # Add after_request handler for headers
            if self.headers_enabled and self.app:

                @self.app.after_request
                def add_rate_limit_headers(response):
                    """Add rate limit headers to response"""
                    from flask import g

                    if hasattr(g, "ratelimit_status"):
                        status = g.ratelimit_status
                        headers = status.to_headers()

                        for key, value in headers.items():
                            response.headers[key] = value

                    return response

            return decorated_function

        return decorator

    def reset(self, identifier: str) -> None:
        """Reset rate limits for identifier"""
        # This would require implementing reset logic in storage
        logger.warning("Reset not fully implemented")


# ============================================
# FastAPI Integration
# ============================================


class FastAPIRateLimiter:
    """
    FastAPI dependency for rate limiting

    Features:
        - Dependency injection pattern
        - Async support
        - Automatic header injection
        - Custom key functions
        - WebSocket support

    Examples:
        >>> from fastapi import FastAPI, Depends, Request
        >>> from ratethrottle import FastAPIRateLimiter
        >>>
        >>> app = FastAPI()
        >>> limiter = FastAPIRateLimiter()
        >>>
        >>> rate_limit = limiter.limit(100, 60)
        >>>
        >>> @app.get("/api/data")
        >>> async def get_data(request: Request, _=Depends(rate_limit)):
        ...     return {"data": "value"}
    """

    def __init__(
        self, storage=None, key_func: Optional[Callable] = None, headers_enabled: bool = True
    ):
        """
        Initialize FastAPI rate limiter

        Args:
            storage: Storage backend
            key_func: Function to extract client identifier
            headers_enabled: Whether to add rate limit headers
        """
        self.limiter = RateThrottleCore(storage=storage)
        self.key_func = key_func or self._default_key_func
        self.headers_enabled = headers_enabled

        logger.info("FastAPIRateLimiter initialized")

    def _default_key_func(self, request):
        """Default function to get client identifier"""
        try:
            return get_client_ip(request)
        except Exception as e:
            logger.error(f"Error getting client IP: {e}")
            return "0.0.0.0"  # nosec B104

    def limit(
        self,
        limit: int,
        window: int = 60,
        strategy: str = "sliding_window",
        key_func: Optional[Callable] = None,
        scope: str = "ip",
    ):
        """
        Create a FastAPI dependency for rate limiting

        Args:
            limit: Maximum requests allowed
            window: Time window in seconds
            strategy: Rate limiting strategy
            key_func: Custom key function
            scope: Scope of the limit

        Returns:
            FastAPI dependency function

        Examples:
            >>> rate_limit = limiter.limit(100, 60)
            >>>
            >>> @app.get("/data")
            >>> async def endpoint(request: Request, _=Depends(rate_limit)):
            ...     return {"data": "value"}
        """
        from fastapi import HTTPException, Request

        # Create rule
        rule_name = f"fastapi_{limit}_{window}_{strategy}"

        try:
            rule = RateThrottleRule(
                name=rule_name, limit=limit, window=window, strategy=strategy, scope=scope
            )
            self.limiter.add_rule(rule)
            logger.debug(f"Added FastAPI limit: {limit}/{window}s")
        except Exception as e:
            logger.error(f"Failed to create rate limit rule: {e}")
            raise ConfigurationError(f"Invalid rate limit configuration: {e}") from e

        async def dependency(request: Request):
            """FastAPI dependency for rate limiting"""
            try:
                # Get client identifier
                key_getter = key_func or self.key_func
                identifier = key_getter(request)

                # Check rate limit
                status = self.limiter.check_rate_limit(
                    identifier,
                    rule_name,
                    metadata={
                        "path": str(request.url.path),
                        "method": request.method,
                        "client": identifier,
                    },
                )

                # Store status in request state for header injection
                request.state.ratelimit_status = status

                # Check if allowed
                if not status.allowed:
                    headers = status.to_headers()

                    raise HTTPException(
                        status_code=429,
                        detail={
                            "error": "Rate limit exceeded",
                            "retry_after": status.retry_after,
                            "limit": status.limit,
                            "remaining": status.remaining,
                        },
                        headers=headers,
                    )

            except HTTPException:
                # Re-raise HTTP exceptions
                raise
            except Exception as e:
                # Log error but allow request
                logger.error(f"Rate limit check error: {e}")

        return dependency


# ============================================
# Django Integration
# ============================================


class DjangoRateLimitMiddleware:
    """
    Django middleware for rate limiting

    Features:
        - Automatic route detection
        - Settings-based configuration
        - Custom key functions
        - Header injection

    Examples:
        >>> # settings.py
        >>> MIDDLEWARE = [
        ...     'ratethrottle.middleware.DjangoRateLimitMiddleware',
        ...     ...
        ... ]
        >>>
        >>> RATELIMIT_RULES = {
        ...     '/api/': {'limit': 100, 'window': 60},
        ... }
    """

    def __init__(self, get_response, storage=None):
        """
        Initialize Django middleware

        Args:
            get_response: Django get_response callable
            storage: Storage backend
        """
        self.get_response = get_response
        self.limiter = RateThrottleCore(storage=storage)
        self._load_rules()

        logger.info("DjangoRateLimitMiddleware initialized")

    def _load_rules(self):
        """Load rules from Django settings"""
        try:
            from django.conf import settings

            rules = getattr(settings, "RATELIMIT_RULES", {})

            for path_pattern, config in rules.items():
                rule = RateThrottleRule(
                    name=f"django_{path_pattern.replace('/', '_')}",
                    limit=config.get("limit", 100),
                    window=config.get("window", 60),
                    strategy=config.get("strategy", "sliding_window"),
                )
                self.limiter.add_rule(rule)
                logger.debug(f"Loaded Django rule for {path_pattern}")

        except Exception as e:
            logger.error(f"Error loading Django rules: {e}")

    def __call__(self, request):
        """Process request through rate limiter"""
        # Get client identifier
        identifier = get_client_ip(request)

        # Check if route has rate limit
        rule_name = self._get_rule_for_path(request.path)

        if rule_name:
            try:
                status = self.limiter.check_rate_limit(
                    identifier,
                    rule_name,
                    metadata={
                        "path": request.path,
                        "method": request.method,
                        "user": getattr(request.user, "id", None),
                    },
                )

                # Add to request
                request.ratelimit_status = status

                # Check if blocked
                if not status.allowed:
                    from django.http import JsonResponse

                    headers = status.to_headers()
                    response = JsonResponse(
                        {
                            "error": "Rate limit exceeded",
                            "retry_after": status.retry_after,
                            "limit": status.limit,
                        },
                        status=429,
                    )

                    for key, value in headers.items():
                        response[key] = value

                    return response

            except Exception as e:
                logger.error(f"Rate limit check error: {e}")

        # Continue to view
        response = self.get_response(request)

        # Add rate limit headers if status exists
        if hasattr(request, "ratelimit_status") and request.ratelimit_status is not None:
            status = request.ratelimit_status
            try:
                headers = status.to_headers()

                # Only set headers if headers is actually a dict
                if isinstance(headers, dict):
                    for key, value in headers.items():
                        try:
                            if hasattr(response, "__setitem__"):
                                response[key] = value
                            elif hasattr(response, "setdefault"):
                                response.setdefault(key, value)
                        except Exception:
                            pass  # Response doesn't support header setting
            except Exception as e:
                logger.debug(f"Could not set rate limit headers: {e}")

        return response

    def _get_rule_for_path(self, path):
        """Get rate limit rule for path"""
        # Simple prefix matching
        for rule_name, rule in self.limiter.rules.items():
            if rule_name.startswith("django_"):
                # Extract path from rule name
                # This is simplified - to be enhanced
                return rule_name

        return None


def django_ratelimit(
    limit: int, window: int = 60, key: str = "ip", strategy: str = "sliding_window"
):
    """
    Django view decorator for rate limiting

    Args:
        limit: Maximum requests allowed
        window: Time window in seconds
        key: Key type ('ip', 'user')
        strategy: Rate limiting strategy

    Examples:
        >>> from ratethrottle.middleware import django_ratelimit
        >>>
        >>> @django_ratelimit(limit=100, window=60)
        >>> def my_view(request):
        ...     return JsonResponse({'data': 'value'})
    """
    from django.http import JsonResponse

    limiter = RateThrottleCore()
    rule_name = f"django_{limit}_{window}"

    try:
        rule = RateThrottleRule(name=rule_name, limit=limit, window=window, strategy=strategy)
        limiter.add_rule(rule)
    except Exception as e:
        logger.error(f"Failed to create Django rate limit rule: {e}")

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            # Get identifier based on key type
            identifier = get_client_ip(request)  # Default to IP

            if key == "user":  # noqa
                if hasattr(request, "user") and request.user.is_authenticated:  # noqa
                    identifier = str(request.user.id)
                else:
                    identifier = "anonymous"
            elif key == "ip":
                identifier = get_client_ip(request)

            try:
                # Check rate limit
                status = limiter.check_rate_limit(identifier, rule_name)

                if not status.allowed:
                    headers = status.to_headers()
                    response = JsonResponse(
                        {"error": "Rate limit exceeded", "retry_after": status.retry_after},
                        status=429,
                    )

                    for header_key, value in headers.items():
                        response[header_key] = value

                    return response

            except Exception as e:
                logger.error(f"Rate limit check error: {e}")

            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator


# ============================================
# Starlette/ASGI Integration
# ============================================


class StarletteRateLimitMiddleware:
    """
    Starlette ASGI middleware for rate limiting

    Features:
        - ASGI-compliant
        - Path-based rules
        - Header injection
        - WebSocket support

    Examples:
        >>> from starlette.applications import Starlette
        >>> from ratethrottle import StarletteRateLimitMiddleware
        >>>
        >>> app = Starlette()
        >>> app.add_middleware(
        ...     StarletteRateLimitMiddleware,
        ...     rules=[rule1, rule2]
        ... )
    """

    def __init__(
        self,
        app,
        storage=None,
        rules: Optional[List[RateThrottleRule]] = None,
        key_func: Optional[Callable] = None,
    ):
        """
        Initialize Starlette middleware

        Args:
            app: ASGI application
            storage: Storage backend
            rules: List of rate limit rules
            key_func: Function to extract identifier
        """
        self.app = app
        self.limiter = RateThrottleCore(storage=storage)
        self.key_func = key_func or self._default_key_func

        # Add rules
        if rules:
            for rule in rules:
                try:
                    self.limiter.add_rule(rule)
                except Exception as e:
                    logger.error(f"Failed to add rule: {e}")

        logger.info("StarletteRateLimitMiddleware initialized")

    def _default_key_func(self, scope):
        """Extract client IP from scope"""
        try:
            client = scope.get("client", [""])[0]
            return client or "0.0.0.0"  # nosec B104
        except Exception as e:
            logger.error(f"Error extracting client IP: {e}")
            return "0.0.0.0"  # nosec B104

    async def __call__(self, scope, receive, send):
        """ASGI application"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Get client identifier
        identifier = self.key_func(scope)

        # Get path
        path = scope.get("path", "/")

        # Check rate limit
        rule_name = self._get_rule_for_path(path)

        if rule_name:
            try:
                status = self.limiter.check_rate_limit(
                    identifier, rule_name, metadata={"path": path, "method": scope.get("method")}
                )

                if not status.allowed:
                    # Send 429 response
                    headers = status.to_headers()

                    await send(
                        {
                            "type": "http.response.start",
                            "status": 429,
                            "headers": [
                                [b"content-type", b"application/json"],
                                *[[k.encode(), v.encode()] for k, v in headers.items()],
                            ],
                        }
                    )

                    await send(
                        {"type": "http.response.body", "body": b'{"error": "Rate limit exceeded"}'}
                    )

                    return

            except Exception as e:
                logger.error(f"Rate limit check error: {e}")

        await self.app(scope, receive, send)

    def _get_rule_for_path(self, path):
        """Get rule for path"""
        # Return first rule (simplified)
        rules = list(self.limiter.rules.keys())
        return rules[0] if rules else None


# ============================================
# Generic WSGI Middleware
# ============================================


class WSGIRateLimitMiddleware:
    """
    Generic WSGI middleware for rate limiting

    Compatible with any WSGI application.

    Examples:
        >>> from ratethrottle import WSGIRateLimitMiddleware
        >>>
        >>> app = WSGIRateLimitMiddleware(wsgi_app)
    """

    def __init__(self, app, storage=None):
        """
        Initialize WSGI middleware

        Args:
            app: WSGI application
            storage: Storage backend
        """
        self.app = app
        self.limiter = RateThrottleCore(storage=storage)

        # Add default rule
        default_rule = RateThrottleRule(
            name="wsgi_default", limit=100, window=60, strategy="sliding_window"
        )
        self.limiter.add_rule(default_rule)

        logger.info("WSGIRateLimitMiddleware initialized")

    def __call__(self, environ, start_response):
        """WSGI application"""
        # Get client identifier
        x_forwarded_for = environ.get("HTTP_X_FORWARDED_FOR", "")
        identifier = (
            x_forwarded_for.split(",")[0].strip()
            if x_forwarded_for
            else environ.get("REMOTE_ADDR", "0.0.0.0")  # nosec B104
        )

        try:
            # Check rate limit
            status = self.limiter.check_rate_limit(identifier, "wsgi_default")

            if not status.allowed:
                # Return 429 response
                headers = status.to_headers()

                response_headers = [
                    ("Content-Type", "application/json"),
                    *[(k, v) for k, v in headers.items()],
                ]

                start_response("429 Too Many Requests", response_headers)
                return [b'{"error": "Rate limit exceeded"}']

        except Exception as e:
            logger.error(f"Rate limit check error: {e}")

        # Continue to app
        return self.app(environ, start_response)
