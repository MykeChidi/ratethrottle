"""
RateThrottle - Async Middleware Integrations

Native asyncio middleware for FastAPI and Starlette, preventing
event loop blocking by natively awaiting AsyncRateThrottleCore.
"""

import logging
from typing import Callable, List, Optional

from .async_core import AsyncRateThrottleCore
from .async_storage import AsyncStorageBackend
from .core import RateThrottleRule

logger = logging.getLogger(__name__)


# ============================================
# FastAPI Integration (Native Async)
# ============================================


class AsyncFastAPIRateLimiter:
    """
    Native async dependency for FastAPI rate limiting
    """

    def __init__(self, storage: Optional[AsyncStorageBackend] = None):
        self.limiter = AsyncRateThrottleCore(storage=storage)
        logger.info("AsyncFastAPIRateLimiter initialized")

    def add_rule(self, rule: RateThrottleRule) -> None:
        self.limiter.add_rule(rule)

    def get_rule(self, rule_name: str):
        return self.limiter.get_rule(rule_name)

    def remove_rule(self, rule_name: str) -> bool:
        return self.limiter.remove_rule(rule_name)

    def list_rules(self):
        return self.limiter.list_rules()

    async def add_to_whitelist(self, identifier: str, persistent: bool = True) -> None:
        await self.limiter.add_to_whitelist(identifier, persistent=persistent)

    async def remove_from_whitelist(self, identifier: str) -> bool:
        return await self.limiter.remove_from_whitelist(identifier)

    async def add_to_blacklist(
        self, identifier: str, duration: Optional[int] = None, persistent: bool = True
    ) -> None:
        await self.limiter.add_to_blacklist(
            identifier, duration=duration, persistent=persistent
        )

    async def remove_from_blacklist(self, identifier: str) -> bool:
        return await self.limiter.remove_from_blacklist(identifier)

    async def get_metrics(self):
        return await self.limiter.get_metrics()

    async def get_status(self):
        return await self.limiter.get_status()

    async def shutdown(self) -> None:
        shutdown = getattr(self.limiter.storage, "shutdown", None)
        if shutdown is not None:
            await shutdown()

    def limit(self, rule_name: str, key_func: Optional[Callable] = None):
        try:
            from fastapi import HTTPException, Request
        except ImportError:
            raise ImportError("FastAPI is not installed. Run 'pip install fastapi'")

        async def dependency(request: Request):
            identifier = None
            if key_func:
                identifier = key_func(request)
            else:
                identifier = request.client.host if request.client else "127.0.0.1"

            try:
                # Natively await without threadpool!
                status = await self.limiter.check_rate_limit(
                    identifier,
                    rule_name,
                    metadata={
                        "path": str(request.url.path),
                        "method": request.method,
                        "client": identifier,
                    },
                )

                request.state.ratelimit_status = status

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

                return status

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Async Rate limit check error: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")

        return dependency


# ============================================
# Starlette/ASGI Integration (Native Async)
# ============================================


class AsyncStarletteRateLimitMiddleware:
    """
    Native async Starlette ASGI middleware for rate limiting
    """

    def __init__(
        self,
        app,
        storage: Optional[AsyncStorageBackend] = None,
        rules: Optional[List[RateThrottleRule]] = None,
        key_func: Optional[Callable] = None,
    ):
        self.app = app
        self.limiter = AsyncRateThrottleCore(storage=storage)
        self.key_func = key_func or self._default_key_func

        if rules:
            for rule in rules:
                try:
                    self.limiter.add_rule(rule)
                except Exception as e:
                    logger.error(f"Failed to add rule: {e}")

        logger.info("AsyncStarletteRateLimitMiddleware initialized")

    def _default_key_func(self, scope):
        try:
            client = scope.get("client", [""])[0]
            return client or "0.0.0.0"
        except Exception as e:
            logger.error(f"Error extracting client IP: {e}")
            return "0.0.0.0"

    def _get_rule_for_path(self, path):
        for rule_name in self.limiter.rules:
            if rule_name in path:
                return rule_name
        return None

    def add_rule(self, rule: RateThrottleRule) -> None:
        self.limiter.add_rule(rule)

    def get_rule(self, rule_name: str):
        return self.limiter.get_rule(rule_name)

    def remove_rule(self, rule_name: str) -> bool:
        return self.limiter.remove_rule(rule_name)

    def list_rules(self):
        return self.limiter.list_rules()

    async def add_to_whitelist(self, identifier: str, persistent: bool = True) -> None:
        await self.limiter.add_to_whitelist(identifier, persistent=persistent)

    async def remove_from_whitelist(self, identifier: str) -> bool:
        return await self.limiter.remove_from_whitelist(identifier)

    async def add_to_blacklist(
        self, identifier: str, duration: Optional[int] = None, persistent: bool = True
    ) -> None:
        await self.limiter.add_to_blacklist(
            identifier, duration=duration, persistent=persistent
        )

    async def remove_from_blacklist(self, identifier: str) -> bool:
        return await self.limiter.remove_from_blacklist(identifier)

    async def get_metrics(self):
        return await self.limiter.get_metrics()

    async def get_status(self):
        return await self.limiter.get_status()

    async def shutdown(self) -> None:
        shutdown = getattr(self.limiter.storage, "shutdown", None)
        if shutdown is not None:
            await shutdown()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        identifier = self.key_func(scope)
        path = scope.get("path", "/")
        rule_name = self._get_rule_for_path(path)

        if rule_name:
            try:
                # Natively await without threadpool!
                status = await self.limiter.check_rate_limit(
                    identifier,
                    rule_name,
                    metadata={"path": path, "method": scope.get("method")},
                )

                if "state" not in scope:
                    scope["state"] = {}
                scope["state"]["ratelimit_status"] = status

                if not status.allowed:

                    async def send_wrapper(message):
                        if message["type"] == "http.response.start":
                            headers = [
                                (k.lower().encode(), str(v).encode())
                                for k, v in status.to_headers().items()
                            ]
                            message.setdefault("headers", []).extend(headers)
                            message["status"] = 429
                        elif message["type"] == "http.response.body":
                            import json

                            message["body"] = json.dumps(
                                {
                                    "error": "Rate limit exceeded",
                                    "retry_after": status.retry_after,
                                    "limit": status.limit,
                                }
                            ).encode()
                        await send(message)

                    await send_wrapper(
                        {"type": "http.response.start", "status": 429, "headers": []}
                    )
                    await send_wrapper({"type": "http.response.body", "body": b""})
                    return

            except Exception as e:
                logger.error(f"Async Rate limit middleware error: {e}")

        # Continue if allowed or error
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                status = scope.get("state", {}).get("ratelimit_status")
                if status:
                    headers = [
                        (k.lower().encode(), str(v).encode())
                        for k, v in status.to_headers().items()
                    ]
                    message.setdefault("headers", []).extend(headers)
            await send(message)

        await self.app(scope, receive, send_with_headers)
