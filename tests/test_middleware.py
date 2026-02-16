"""
Tests for web framework middleware integrations
"""

from unittest.mock import Mock, patch

import pytest

from ratethrottle.core import RateThrottleRule
from ratethrottle.exceptions import ConfigurationError

# ==============================================
# Flask Middleware Tests
# ==============================================


class TestFlaskRateLimiter:
    """Test Flask integration"""

    @pytest.fixture
    def mock_flask_app(self):
        """Create mock Flask app"""
        app = Mock()
        app.name = "test_app"
        app.config = {
            "TESTING": True,
            "RATELIMIT_STORAGE_URL": None,
            "RATELIMIT_STRATEGY": "sliding_window",
            "RATELIMIT_HEADERS_ENABLED": True,
            "RATELIMIT_KEY_PREFIX": "ratelimit:",
        }
        app.errorhandler = Mock(return_value=lambda f: f)
        app.after_request = Mock(return_value=lambda f: f)
        return app

    @pytest.fixture
    def limiter(self, mock_flask_app):
        """Create Flask rate limiter"""
        from ratethrottle.middleware import FlaskRateLimiter

        return FlaskRateLimiter(mock_flask_app)

    def test_initialization(self, mock_flask_app):
        """Test Flask limiter initialization"""
        from ratethrottle.middleware import FlaskRateLimiter

        limiter = FlaskRateLimiter(mock_flask_app)

        assert limiter.app == mock_flask_app
        assert limiter.limiter is not None
        assert limiter.headers_enabled is True

    def test_initialization_without_app(self):
        """Test initialization without app"""
        from ratethrottle.middleware import FlaskRateLimiter

        limiter = FlaskRateLimiter()
        assert limiter.app is None

    def test_init_app(self, mock_flask_app):
        """Test init_app method"""
        from ratethrottle.middleware import FlaskRateLimiter

        limiter = FlaskRateLimiter()
        limiter.init_app(mock_flask_app)

        assert limiter.app == mock_flask_app

    def test_default_key_func(self, limiter, mocker):
        """Test default key function"""
        # Mock Flask request
        mock_request = Mock()
        mock_request.remote_addr = "192.168.1.100"

        with patch("ratethrottle.middleware.get_client_ip", return_value="192.168.1.100"):
            key = limiter._default_key_func()
            assert key == "192.168.1.100"

    def test_limit_decorator_basic(self, limiter):
        """Test basic limit decorator"""

        @limiter.limit("100/minute")
        def test_view():
            return {"success": True}

        # Decorator should wrap the function
        assert callable(test_view)

    def test_limit_decorator_with_numbers(self, limiter):
        """Test limit decorator with numeric parameters"""

        @limiter.limit(50, per=60)
        def test_view():
            return {"success": True}

        assert callable(test_view)

    def test_limit_decorator_parse_rate_string(self, limiter, mocker):
        """Test parsing rate limit strings"""
        mock_view = Mock(return_value={"success": True})
        mock_view.__name__ = "test_view"
        mock_view.__module__ = "test_module"

        decorated = limiter.limit("100/minute")(mock_view)

        # Check that a rule was added
        assert len(limiter.limiter.rules) > 0

    def test_limit_decorator_allows_request(self, limiter, mocker):
        """Test that decorator allows requests under limit"""
        # Mock Flask components
        mock_request = Mock()
        mock_request.remote_addr = "192.168.1.100"
        mock_request.endpoint = "test_view"
        mock_request.method = "GET"
        mock_request.path = "/test"

        mock_g = Mock()

        with (
            patch("ratethrottle.middleware.request", mock_request),
            patch("ratethrottle.middleware.g", mock_g),
            patch("ratethrottle.middleware.get_client_ip", return_value="192.168.1.100"),
        ):

            @limiter.limit("100/minute")
            def test_view():
                return {"success": True}

            result = test_view()
            assert result == {"success": True}

    def test_limit_decorator_blocks_request(self, limiter, mocker):
        """Test that decorator blocks requests over limit"""
        from ratethrottle.exceptions import RateLimitExceeded

        # Mock Flask components
        mock_request = Mock()
        mock_request.remote_addr = "192.168.1.100"
        mock_request.endpoint = "test_view"
        mock_request.method = "GET"
        mock_request.path = "/test"

        mock_g = Mock()
        mock_abort = Mock(
            side_effect=RateLimitExceeded(
                "Rate limit exceeded", retry_after=60, limit=1, remaining=0, reset_time=1234567890
            )
        )

        with (
            patch("ratethrottle.middleware.request", mock_request),
            patch("ratethrottle.middleware.g", mock_g),
            patch("ratethrottle.middleware.abort", mock_abort),
            patch("ratethrottle.middleware.get_client_ip", return_value="192.168.1.100"),
        ):

            @limiter.limit(1, per=60)
            def test_view():
                return {"success": True}

            # First request should work
            test_view()

            # Second request should be blocked
            with pytest.raises(RateLimitExceeded):
                test_view()

    def test_limit_decorator_method_filtering(self, limiter, mocker):
        """Test that decorator filters by HTTP method"""
        mock_request = Mock()
        mock_request.remote_addr = "192.168.1.100"
        mock_request.endpoint = "test_view"
        mock_request.method = "GET"
        mock_request.path = "/test"

        mock_g = Mock()

        with (
            patch("ratethrottle.middleware.request", mock_request),
            patch("ratethrottle.middleware.g", mock_g),
            patch("ratethrottle.middleware.get_client_ip", return_value="192.168.1.100"),
        ):

            @limiter.limit("100/minute", methods=["POST"])
            def test_view():
                return {"success": True}

            # GET request should bypass limit
            result = test_view()
            assert result == {"success": True}


# ==============================================
# FastAPI Middleware Tests
# ==============================================


class TestFastAPIRateLimiter:
    """Test FastAPI integration"""

    @pytest.fixture
    def limiter(self):
        """Create FastAPI rate limiter"""
        from ratethrottle.middleware import FastAPIRateLimiter

        return FastAPIRateLimiter()

    def test_initialization(self):
        """Test FastAPI limiter initialization"""
        from ratethrottle.middleware import FastAPIRateLimiter

        limiter = FastAPIRateLimiter()
        assert limiter.limiter is not None
        assert limiter.headers_enabled is True

    def test_default_key_func(self, limiter):
        """Test default key function"""
        mock_request = Mock()
        mock_request.client = ("192.168.1.100", 12345)

        with patch("ratethrottle.middleware.get_client_ip", return_value="192.168.1.100"):
            key = limiter._default_key_func(mock_request)
            assert key == "192.168.1.100"

    def test_limit_creates_dependency(self, limiter):
        """Test that limit creates a dependency"""
        dependency = limiter.limit(100, 60)

        assert callable(dependency)

    def test_limit_with_invalid_config(self, limiter):
        """Test that invalid config raises error"""
        with pytest.raises(ConfigurationError):
            limiter.limit(-1, 60)

    @pytest.mark.asyncio
    async def test_dependency_allows_request(self, limiter):
        """Test that dependency allows requests under limit"""
        from unittest.mock import AsyncMock

        mock_request = Mock()
        mock_request.url = Mock()
        mock_request.url.path = "/test"
        mock_request.method = "GET"
        mock_request.state = Mock()

        with patch("ratethrottle.middleware.get_client_ip", return_value="192.168.1.100"):
            dependency = limiter.limit(100, 60)

            # Should not raise exception
            await dependency(mock_request)

    @pytest.mark.asyncio
    async def test_dependency_blocks_request(self, limiter):
        """Test that dependency blocks requests over limit"""
        from fastapi import HTTPException

        mock_request = Mock()
        mock_request.url = Mock()
        mock_request.url.path = "/test"
        mock_request.method = "GET"
        mock_request.state = Mock()

        with patch("ratethrottle.middleware.get_client_ip", return_value="192.168.1.100"):
            dependency = limiter.limit(1, 60)

            # First request should work
            await dependency(mock_request)

            # Second request should be blocked
            with pytest.raises(HTTPException) as exc_info:
                await dependency(mock_request)

            assert exc_info.value.status_code == 429


# ==============================================
# Django Middleware Tests
# ==============================================


class TestDjangoRateLimitMiddleware:
    """Test Django middleware"""

    @pytest.fixture
    def mock_get_response(self):
        """Create mock get_response callable"""

        def get_response(request):
            response = Mock()
            response.status_code = 200
            return response

        return get_response

    @pytest.fixture
    def middleware(self, mock_get_response):
        """Create Django middleware"""
        from ratethrottle.middleware import DjangoRateLimitMiddleware

        return DjangoRateLimitMiddleware(mock_get_response)

    def test_initialization(self, mock_get_response):
        """Test Django middleware initialization"""
        from ratethrottle.middleware import DjangoRateLimitMiddleware

        middleware = DjangoRateLimitMiddleware(mock_get_response)
        assert middleware.limiter is not None

    def test_call_allows_request(self, middleware):
        """Test that middleware allows requests"""
        mock_request = Mock()
        mock_request.path = "/test/"
        mock_request.method = "GET"
        mock_request.user = Mock()
        mock_request.user.id = 1

        with patch("ratethrottle.middleware.get_client_ip", return_value="192.168.1.100"):
            response = middleware(mock_request)
            assert response.status_code == 200


class TestDjangoRateLimitDecorator:
    """Test Django decorator"""

    def test_decorator_creation(self):
        """Test creating Django decorator"""
        from ratethrottle.middleware import django_ratelimit

        decorator = django_ratelimit(limit=100, window=60)
        assert callable(decorator)

    def test_decorator_wraps_view(self):
        """Test that decorator wraps view"""
        from ratethrottle.middleware import django_ratelimit

        @django_ratelimit(limit=100, window=60)
        def test_view(request):
            return {"success": True}

        assert callable(test_view)

    def test_decorator_allows_request(self):
        """Test that decorator allows requests"""
        from ratethrottle.middleware import django_ratelimit

        mock_request = Mock()
        mock_request.user = Mock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 1

        @django_ratelimit(limit=100, window=60, key="user")
        def test_view(request):
            return {"success": True}

        with patch("ratethrottle.middleware.get_client_ip", return_value="192.168.1.100"):
            result = test_view(mock_request)
            assert result == {"success": True}


# ==============================================
# Starlette Middleware Tests
# ==============================================


class TestStarletteRateLimitMiddleware:
    """Test Starlette middleware"""

    @pytest.fixture
    def mock_app(self):
        """Create mock ASGI app"""

        async def app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [[b"content-type", b"application/json"]],
                }
            )
            await send({"type": "http.response.body", "body": b'{"success": true}'})

        return app

    @pytest.fixture
    def rule(self):
        """Create test rule"""
        return RateThrottleRule(name="test", limit=100, window=60, strategy="sliding_window")

    def test_initialization(self, mock_app, rule):
        """Test Starlette middleware initialization"""
        from ratethrottle.middleware import StarletteRateLimitMiddleware

        middleware = StarletteRateLimitMiddleware(mock_app, rules=[rule])
        assert middleware.app == mock_app
        assert len(middleware.limiter.rules) > 0

    def test_default_key_func(self, mock_app):
        """Test default key function"""
        from ratethrottle.middleware import StarletteRateLimitMiddleware

        middleware = StarletteRateLimitMiddleware(mock_app)

        scope = {"type": "http", "client": ("192.168.1.100", 12345)}

        key = middleware._default_key_func(scope)
        assert key == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_call_non_http(self, mock_app):
        """Test that non-HTTP requests pass through"""
        from ratethrottle.middleware import StarletteRateLimitMiddleware

        middleware = StarletteRateLimitMiddleware(mock_app)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        # Should call underlying app

    @pytest.mark.asyncio
    async def test_call_allows_request(self, mock_app, rule):
        """Test that middleware allows requests"""
        from ratethrottle.middleware import StarletteRateLimitMiddleware

        middleware = StarletteRateLimitMiddleware(mock_app, rules=[rule])

        scope = {
            "type": "http",
            "client": ("192.168.1.100", 12345),
            "path": "/test",
            "method": "GET",
        }

        receive = Mock()
        send = AsyncMock()

        await middleware(scope, receive, send)


# ==============================================
# WSGI Middleware Tests
# ==============================================


class TestWSGIRateLimitMiddleware:
    """Test WSGI middleware"""

    @pytest.fixture
    def mock_app(self):
        """Create mock WSGI app"""

        def app(environ, start_response):
            start_response("200 OK", [("Content-Type", "application/json")])
            return [b'{"success": true}']

        return app

    def test_initialization(self, mock_app):
        """Test WSGI middleware initialization"""
        from ratethrottle.middleware import WSGIRateLimitMiddleware

        middleware = WSGIRateLimitMiddleware(mock_app)
        assert middleware.app == mock_app
        assert middleware.limiter is not None

    def test_call_allows_request(self, mock_app):
        """Test that middleware allows requests"""
        from ratethrottle.middleware import WSGIRateLimitMiddleware

        middleware = WSGIRateLimitMiddleware(mock_app)

        environ = {"REMOTE_ADDR": "192.168.1.100", "REQUEST_METHOD": "GET", "PATH_INFO": "/test"}

        start_response = Mock()

        result = middleware(environ, start_response)
        assert result is not None

    def test_call_with_forwarded_for(self, mock_app):
        """Test with X-Forwarded-For header"""
        from ratethrottle.middleware import WSGIRateLimitMiddleware

        middleware = WSGIRateLimitMiddleware(mock_app)

        environ = {
            "REMOTE_ADDR": "10.0.0.1",
            "HTTP_X_FORWARDED_FOR": "192.168.1.100",
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/test",
        }

        start_response = Mock()

        result = middleware(environ, start_response)
        assert result is not None


# ==============================================
# Helper Function for AsyncMock
# ==============================================


class AsyncMock(Mock):
    """Async mock for Python < 3.9 compatibility"""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
