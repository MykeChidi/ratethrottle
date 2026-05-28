"""
Tests for async middleware integrations
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from ratethrottle.async_middleware import AsyncFastAPIRateLimiter, AsyncStarletteRateLimitMiddleware
from ratethrottle.core import RateThrottleRule
from ratethrottle.async_storage import AsyncInMemoryStorage


@pytest.fixture
async def fastapi_limiter():
    """Create FastAPI rate limiter"""
    storage = AsyncInMemoryStorage()
    limiter = AsyncFastAPIRateLimiter(storage=storage)
    yield limiter
    await storage.shutdown()


@pytest.fixture
async def starlette_limiter():
    """Create Starlette rate limiter"""
    app = AsyncMock()
    storage = AsyncInMemoryStorage()
    limiter = AsyncStarletteRateLimitMiddleware(app, storage=storage)
    yield limiter
    await storage.shutdown()


class TestAsyncFastAPIRateLimiter:
    """Test AsyncFastAPIRateLimiter"""

    @pytest.mark.asyncio
    async def test_initialization(self, fastapi_limiter):
        """Test FastAPI limiter initialization"""
        assert fastapi_limiter.limiter is not None
        assert fastapi_limiter.limiter.storage is not None

    @pytest.mark.asyncio
    async def test_add_rule(self, fastapi_limiter):
        """Test adding rule to FastAPI limiter"""
        rule = RateThrottleRule(
            name="api_rule",
            limit=100,
            window=60,
            strategy="fixed_window",
        )
        fastapi_limiter.add_rule(rule)
        assert "api_rule" in fastapi_limiter.limiter.rules

    @pytest.mark.asyncio
    async def test_get_rule(self, fastapi_limiter):
        """Test getting rule from FastAPI limiter"""
        rule = RateThrottleRule(
            name="api_rule",
            limit=100,
            window=60,
            strategy="fixed_window",
        )
        fastapi_limiter.add_rule(rule)
        retrieved_rule = fastapi_limiter.get_rule("api_rule")
        assert retrieved_rule == rule

    @pytest.mark.asyncio
    async def test_remove_rule(self, fastapi_limiter):
        """Test removing rule from FastAPI limiter"""
        rule = RateThrottleRule(
            name="api_rule",
            limit=100,
            window=60,
            strategy="fixed_window",
        )
        fastapi_limiter.add_rule(rule)
        assert fastapi_limiter.remove_rule("api_rule")
        assert "api_rule" not in fastapi_limiter.limiter.rules

    @pytest.mark.asyncio
    async def test_list_rules(self, fastapi_limiter):
        """Test listing rules"""
        rule1 = RateThrottleRule(name="rule1", limit=100, window=60)
        rule2 = RateThrottleRule(name="rule2", limit=50, window=60)
        
        fastapi_limiter.add_rule(rule1)
        fastapi_limiter.add_rule(rule2)
        
        rules = fastapi_limiter.list_rules()
        assert set(rules) == {"rule1", "rule2"}

    @pytest.mark.asyncio
    async def test_add_to_whitelist(self, fastapi_limiter):
        """Test adding to whitelist"""
        await fastapi_limiter.add_to_whitelist("192.168.1.1")
        status = await fastapi_limiter.limiter.is_whitelisted("192.168.1.1")
        assert status

    @pytest.mark.asyncio
    async def test_remove_from_whitelist(self, fastapi_limiter):
        """Test removing from whitelist"""
        await fastapi_limiter.add_to_whitelist("192.168.1.1")
        assert await fastapi_limiter.remove_from_whitelist("192.168.1.1")
        status = await fastapi_limiter.limiter.is_whitelisted("192.168.1.1")
        assert not status

    @pytest.mark.asyncio
    async def test_add_to_blacklist(self, fastapi_limiter):
        """Test adding to blacklist"""
        await fastapi_limiter.add_to_blacklist("192.168.1.1")
        status = await fastapi_limiter.limiter.is_blacklisted("192.168.1.1")
        assert status

    @pytest.mark.asyncio
    async def test_remove_from_blacklist(self, fastapi_limiter):
        """Test removing from blacklist"""
        await fastapi_limiter.add_to_blacklist("192.168.1.1")
        assert await fastapi_limiter.remove_from_blacklist("192.168.1.1")
        status = await fastapi_limiter.limiter.is_blacklisted("192.168.1.1")
        assert not status

    @pytest.mark.asyncio
    async def test_get_metrics(self, fastapi_limiter):
        """Test getting metrics"""
        rule = RateThrottleRule(name="api_rule", limit=100, window=60)
        fastapi_limiter.add_rule(rule)
        
        await fastapi_limiter.limiter.check_rate_limit("192.168.1.1", "api_rule")
        
        metrics = await fastapi_limiter.get_metrics()
        assert metrics["total_requests"] >= 1

    @pytest.mark.asyncio
    async def test_get_status(self, fastapi_limiter):
        """Test getting status"""
        rule = RateThrottleRule(name="api_rule", limit=100, window=60)
        fastapi_limiter.add_rule(rule)
        
        status = await fastapi_limiter.get_status()
        assert "rules" in status
        assert len(status["rules"]) == 1

    @pytest.mark.asyncio
    async def test_shutdown(self, fastapi_limiter):
        """Test shutdown"""
        await fastapi_limiter.shutdown()
        # Should not raise


class TestAsyncStarletteRateLimitMiddleware:
    """Test AsyncStarletteRateLimitMiddleware"""

    @pytest.mark.asyncio
    async def test_initialization(self, starlette_limiter):
        """Test Starlette middleware initialization"""
        assert starlette_limiter.limiter is not None
        assert starlette_limiter.app is not None

    @pytest.mark.asyncio
    async def test_init_with_rules(self):
        """Test Starlette middleware initialization with rules"""
        app = AsyncMock()
        storage = AsyncInMemoryStorage()
        
        rules = [
            RateThrottleRule(name="api_rule", limit=100, window=60),
            RateThrottleRule(name="upload_rule", limit=10, window=60),
        ]
        
        middleware = AsyncStarletteRateLimitMiddleware(app, storage=storage, rules=rules)
        
        assert len(middleware.limiter.rules) == 2
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_default_key_func(self, starlette_limiter):
        """Test default key function"""
        scope = {
            "type": "http",
            "client": ("192.168.1.1", 54321),
        }
        key = starlette_limiter._default_key_func(scope)
        assert key == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_default_key_func_missing_client(self, starlette_limiter):
        """Test default key function with missing client"""
        scope = {"type": "http"}
        key = starlette_limiter._default_key_func(scope)
        assert key == "0.0.0.0"

    @pytest.mark.asyncio
    async def test_get_rule_for_path(self, starlette_limiter):
        """Test getting rule for path"""
        rule1 = RateThrottleRule(name="api_rule", limit=100, window=60)
        rule2 = RateThrottleRule(name="upload_rule", limit=10, window=60)
        
        starlette_limiter.limiter.add_rule(rule1)
        starlette_limiter.limiter.add_rule(rule2)
        
        # Path matching based on rule name in path
        found_rule = starlette_limiter._get_rule_for_path("/api_rule/endpoint")
        assert found_rule == "api_rule"

    @pytest.mark.asyncio
    async def test_add_rule(self, starlette_limiter):
        """Test adding rule"""
        rule = RateThrottleRule(name="api_rule", limit=100, window=60)
        starlette_limiter.add_rule(rule)
        assert "api_rule" in starlette_limiter.limiter.rules

    @pytest.mark.asyncio
    async def test_remove_rule(self, starlette_limiter):
        """Test removing rule"""
        rule = RateThrottleRule(name="api_rule", limit=100, window=60)
        starlette_limiter.add_rule(rule)
        assert starlette_limiter.remove_rule("api_rule")

    @pytest.mark.asyncio
    async def test_list_rules(self, starlette_limiter):
        """Test listing rules"""
        rule1 = RateThrottleRule(name="rule1", limit=100, window=60)
        rule2 = RateThrottleRule(name="rule2", limit=50, window=60)
        
        starlette_limiter.add_rule(rule1)
        starlette_limiter.add_rule(rule2)
        
        rules = starlette_limiter.list_rules()
        assert set(rules) == {"rule1", "rule2"}

    @pytest.mark.asyncio
    async def test_add_to_whitelist(self, starlette_limiter):
        """Test adding to whitelist"""
        await starlette_limiter.add_to_whitelist("192.168.1.1")
        status = await starlette_limiter.limiter.is_whitelisted("192.168.1.1")
        assert status

    @pytest.mark.asyncio
    async def test_add_to_blacklist(self, starlette_limiter):
        """Test adding to blacklist"""
        await starlette_limiter.add_to_blacklist("192.168.1.1")
        status = await starlette_limiter.limiter.is_blacklisted("192.168.1.1")
        assert status

    @pytest.mark.asyncio
    async def test_get_metrics(self, starlette_limiter):
        """Test getting metrics"""
        metrics = await starlette_limiter.get_metrics()
        assert "total_requests" in metrics

    @pytest.mark.asyncio
    async def test_get_status(self, starlette_limiter):
        """Test getting status"""
        status = await starlette_limiter.get_status()
        assert "rules" in status

    @pytest.mark.asyncio
    async def test_shutdown(self, starlette_limiter):
        """Test shutdown"""
        await starlette_limiter.shutdown()
        # Should not raise

    @pytest.mark.asyncio
    async def test_middleware_call_non_http(self, starlette_limiter):
        """Test middleware with non-HTTP request"""
        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()
        
        starlette_limiter.app = AsyncMock()
        await starlette_limiter(scope, receive, send)
        
        # App should be called
        starlette_limiter.app.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_call_http_no_rule(self, starlette_limiter):
        """Test middleware with HTTP request but no matching rule"""
        scope = {
            "type": "http",
            "client": ("192.168.1.1", 54321),
            "path": "/unknown",
        }
        receive = AsyncMock()
        send = AsyncMock()
        
        starlette_limiter.app = AsyncMock(return_value=None)
        
        await starlette_limiter(scope, receive, send)
        
        # App should be called
        starlette_limiter.app.assert_called_once()


class TestAsyncMiddlewareWithStorage:
    """Test middleware with different storage backends"""

    @pytest.mark.asyncio
    async def test_fastapi_limiter_with_in_memory_storage(self):
        """Test FastAPI limiter with in-memory storage"""
        storage = AsyncInMemoryStorage()
        limiter = AsyncFastAPIRateLimiter(storage=storage)
        
        rule = RateThrottleRule(name="api", limit=10, window=60)
        limiter.add_rule(rule)
        
        # Should work without errors
        metrics = await limiter.get_metrics()
        assert metrics is not None
        
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_starlette_limiter_with_in_memory_storage(self):
        """Test Starlette limiter with in-memory storage"""
        app = AsyncMock()
        storage = AsyncInMemoryStorage()
        
        rules = [RateThrottleRule(name="api", limit=10, window=60)]
        middleware = AsyncStarletteRateLimitMiddleware(app, storage=storage, rules=rules)
        
        # Should work without errors
        status = await middleware.get_status()
        assert status is not None
        
        await storage.shutdown()


class TestAsyncMiddlewareEdgeCases:
    """Test edge cases in async middleware"""

    @pytest.mark.asyncio
    async def test_fastapi_limiter_with_none_client(self):
        """Test FastAPI limiter when request has no client"""
        storage = AsyncInMemoryStorage()
        limiter = AsyncFastAPIRateLimiter(storage=storage)
        
        rule = RateThrottleRule(name="api", limit=10, window=60)
        limiter.add_rule(rule)
        
        # Mock request with no client
        request = MagicMock()
        request.client = None
        request.url.path = "/api"
        request.method = "GET"
        
        # This would normally raise HTTPException in the dependency
        # but we're testing the dependency creation
        dep = limiter.limit("api")
        assert callable(dep)
        
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_starlette_limiter_missing_state(self):
        """Test Starlette middleware when state is missing"""
        app = AsyncMock(return_value=None)
        storage = AsyncInMemoryStorage()
        
        middleware = AsyncStarletteRateLimitMiddleware(app, storage=storage)
        
        scope = {
            "type": "http",
            "client": ("192.168.1.1", 54321),
            "path": "/test",
            "method": "GET",
            # No state
        }
        
        receive = AsyncMock()
        send = AsyncMock()
        
        await middleware(scope, receive, send)
        
        # Should not raise and should add state
        assert "state" in scope or app.called
        
        await storage.shutdown()

    @pytest.mark.asyncio
    async def test_starlette_limiter_error_handling(self):
        """Test Starlette middleware error handling"""
        app = AsyncMock(side_effect=Exception("App error"))
        storage = AsyncInMemoryStorage()
        
        middleware = AsyncStarletteRateLimitMiddleware(app, storage=storage)
        
        scope = {
            "type": "http",
            "client": ("192.168.1.1", 54321),
            "path": "/test",
            "method": "GET",
        }
        
        receive = AsyncMock()
        send = AsyncMock()
        
        # Should handle error
        with pytest.raises(Exception):
            await middleware(scope, receive, send)
        
        await storage.shutdown()
