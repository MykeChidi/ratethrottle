"""
RateThrottle - Async Storage Backend Implementations

Async storage backends with comprehensive error handling,
non-blocking I/O operations, and asyncio integration.
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from .exceptions import StorageError

logger = logging.getLogger(__name__)


class AsyncStorageBackend(ABC):
    """
    Abstract base class for async storage backends
    """

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        pass

    @abstractmethod
    async def check_and_delete_if_expired(self, key: str) -> Tuple[bool, Optional[Any]]:
        pass

    @abstractmethod
    async def set_if_not_exists(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        pass

    @abstractmethod
    async def increment(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        pass

    @abstractmethod
    async def delete_many(self, keys: List[str]) -> int:
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        pass

    @abstractmethod
    async def clear(self) -> int:
        pass

    @abstractmethod
    async def get_stats(self) -> Dict[str, Any]:
        pass

    async def evaluate_lua(self, script: str, keys: List[str], args: List[Any]) -> Any:
        raise NotImplementedError("evaluate_lua is only supported in AsyncRedisStorage")

    async def health_check(self) -> bool:
        try:
            test_key = "__health_check_async__"
            await self.set(test_key, True, ttl=1)
            result = await self.get(test_key)
            await self.delete(test_key)
            return result is not None
        except Exception as e:
            logger.error(f"Async health check failed: {e}")
            return False

    async def get_info(self) -> Dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "healthy": await self.health_check(),
        }


class AsyncInMemoryStorage(AsyncStorageBackend):
    """
    Async-safe in-memory storage.
    Uses asyncio.Lock for concurrency control.
    """

    def __init__(self, cleanup_interval: int = 300, max_keys: int = 1000000):
        self._data: Dict[str, Tuple[Any, Optional[float]]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_interval = cleanup_interval
        self.max_keys = max_keys
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stats = {"sets": 0, "gets": 0, "deletes": 0, "cleanups": 0, "evictions": 0}

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_daemon())
        logger.info(f"AsyncInMemoryStorage: cleanup every {cleanup_interval}s")

    async def _cleanup_daemon(self):
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Async cleanup error: {e}")

    async def _cleanup_expired(self) -> int:
        async with self._lock:
            now = time.time()
            expired = [k for k, (_, expiry) in self._data.items() if expiry and expiry <= now]
            for k in expired:
                del self._data[k]
            if expired:
                self._stats["cleanups"] += 1
            return len(expired)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        if not isinstance(key, str):
            raise StorageError("Key must be string")
        if ttl is not None and ttl < 0:
            raise StorageError("TTL cannot be negative")

        expiry_time = (time.time() + ttl) if ttl else None
        async with self._lock:
            if len(self._data) >= self.max_keys:
                await self._evict_lru()
            self._data[key] = (value, expiry_time)
            self._stats["sets"] += 1
        return True

    async def get(self, key: str) -> Optional[Any]:
        if not isinstance(key, str):
            raise StorageError("Key must be string")

        async with self._lock:
            if key not in self._data:
                return None
            value, expiry = self._data[key]
            if expiry is not None and expiry <= time.time():
                del self._data[key]
                return None
            self._stats["gets"] += 1
            return value

    async def check_and_delete_if_expired(self, key: str) -> Tuple[bool, Optional[Any]]:
        if not isinstance(key, str):
            raise StorageError("Key must be string")

        async with self._lock:
            if key not in self._data:
                return False, None
            value, expiry = self._data[key]
            if expiry is not None and expiry <= time.time():
                del self._data[key]
                return False, None
            return True, value

    async def set_if_not_exists(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        if not isinstance(key, str):
            raise StorageError("Key must be string")

        expiry_time = (time.time() + ttl) if ttl else None
        async with self._lock:
            if key in self._data:
                _, expiry = self._data[key]
                if expiry is not None and expiry <= time.time():
                    del self._data[key]
                else:
                    return False
            self._data[key] = (value, expiry_time)
            return True

    async def increment(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
        if not isinstance(key, str):
            raise StorageError("Key must be string")
        if not isinstance(amount, int):
            raise StorageError("Amount must be int")

        async with self._lock:
            value = 0
            if key in self._data:
                val, expiry = self._data[key]
                if expiry and expiry <= time.time():
                    del self._data[key]
                else:
                    value = val

            if not isinstance(value, (int, float)):
                raise StorageError("Cannot increment non-numeric value")

            new_value = int(value) + amount
            expiry_time = (time.time() + ttl) if ttl else None
            self._data[key] = (new_value, expiry_time)
            self._stats["sets"] += 1
            return new_value

    async def delete(self, key: str) -> bool:
        if not isinstance(key, str):
            raise StorageError("Key must be string")
        async with self._lock:
            if key in self._data:
                del self._data[key]
                self._stats["deletes"] += 1
                return True
            return False

    async def delete_many(self, keys: List[str]) -> int:
        count = 0
        async with self._lock:
            for key in keys:
                if isinstance(key, str) and key in self._data:
                    del self._data[key]
                    count += 1
            self._stats["deletes"] += count
        return count

    async def exists(self, key: str) -> bool:
        if not isinstance(key, str):
            raise StorageError("Key must be string")
        async with self._lock:
            if key not in self._data:
                return False
            _, expiry = self._data[key]
            if expiry is not None and expiry <= time.time():
                del self._data[key]
                return False
            return True

    async def clear(self) -> int:
        async with self._lock:
            count = len(self._data)
            self._data.clear()
            return count

    async def get_stats(self) -> Dict[str, Any]:
        async with self._lock:
            now = time.time()
            expired = sum(1 for _, exp in self._data.values() if exp and exp < now)
            return {
                "total_keys": len(self._data),
                "expired_keys": expired,
                "active_keys": len(self._data) - expired,
                **self._stats,
            }

    async def _evict_lru(self):
        now = time.time()
        for k, (_, expiry) in list(self._data.items()):
            if expiry and expiry <= now:
                del self._data[k]
                self._stats["evictions"] += 1
                return
        if self._data:
            k = next(iter(self._data))
            del self._data[k]
            self._stats["evictions"] += 1

    async def shutdown(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
        async with self._lock:
            self._data.clear()


class AsyncRedisStorage(AsyncStorageBackend):
    """
    Async Redis-based storage backend for distributed rate limiting.
    Uses redis.asyncio for non-blocking I/O.
    """

    def __init__(
        self, redis_url: str = "redis://localhost:6379/0", key_prefix: str = "rt:", **kwargs
    ):
        try:
            import redis.asyncio as redis

            decode_responses = kwargs.pop("decode_responses", False)
            self.redis = redis.from_url(
                redis_url, decode_responses=decode_responses, **kwargs
            )
            self.key_prefix = key_prefix
        except ImportError:
            raise StorageError("redis.asyncio package is required for AsyncRedisStorage")
        except Exception as e:
            raise StorageError(f"Failed to initialize AsyncRedisStorage: {e}")

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def _serialize(self, value: Any) -> bytes:
        return json.dumps(value).encode("utf-8")

    def _deserialize(self, value: Optional[bytes]) -> Optional[Any]:
        if value is None:
            return None
        try:
            return json.loads(value.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return value.decode("utf-8") if isinstance(value, bytes) else value

    async def get(self, key: str) -> Optional[Any]:
        if not isinstance(key, str):
            raise StorageError("Key must be string")
        try:
            full_key = self._make_key(key)
            value = await self.redis.get(full_key)
            return self._deserialize(value)
        except Exception as e:
            raise StorageError(f"Async Redis GET error: {e}")

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        if not isinstance(key, str):
            raise StorageError("Key must be string")
        try:
            full_key = self._make_key(key)
            serialized = self._serialize(value)
            result = await self.redis.set(full_key, serialized, ex=ttl)
            return bool(result)
        except Exception as e:
            raise StorageError(f"Async Redis SET error: {e}")

    async def check_and_delete_if_expired(self, key: str) -> Tuple[bool, Optional[Any]]:
        script = """
        local value = redis.call('GET', KEYS[1])
        if not value then
            return {0, nil}
        end
        local expiry = tonumber(value) or 0
        if expiry > 0 and expiry <= tonumber(ARGV[1]) then
            redis.call('DEL', KEYS[1])
            return {0, nil}
        end
        return {1, value}
        """
        try:
            full_key = self._make_key(key)
            result = await self.redis.eval(script, 1, full_key, str(time.time()))
            return bool(result[0]), self._deserialize(result[1]) if result[1] else None
        except Exception as e:
            raise StorageError(f"Async Redis check_and_delete failed: {e}")

    async def set_if_not_exists(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        try:
            full_key = self._make_key(key)
            serialized = self._serialize(value)
            if ttl:
                result = await self.redis.set(full_key, serialized, nx=True, ex=ttl)
            else:
                result = await self.redis.set(full_key, serialized, nx=True)
            return bool(result)
        except Exception as e:
            raise StorageError(f"Async Redis set_if_not_exists failed: {e}")

    async def increment(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
        if not isinstance(key, str):
            raise StorageError("Key must be string")
        try:
            full_key = self._make_key(key)
            if ttl is not None:
                pipeline = self.redis.pipeline()
                pipeline.incrby(full_key, amount)
                pipeline.expire(full_key, ttl)
                results = await pipeline.execute()
                return int(results[0])
            else:
                return int(await self.redis.incrby(full_key, amount))
        except Exception as e:
            raise StorageError(f"Async Redis INCR error: {e}")

    async def delete(self, key: str) -> bool:
        if not isinstance(key, str):
            raise StorageError("Key must be string")
        try:
            return bool(await self.redis.delete(self._make_key(key)))
        except Exception as e:
            raise StorageError(f"Async Redis DEL error: {e}")

    async def delete_many(self, keys: List[str]) -> int:
        if not keys:
            return 0
        try:
            full_keys = [self._make_key(k) for k in keys]
            return int(await self.redis.delete(*full_keys))
        except Exception as e:
            raise StorageError(f"Async Redis delete_many failed: {e}")

    async def exists(self, key: str) -> bool:
        if not isinstance(key, str):
            raise StorageError("Key must be string")
        try:
            return bool(await self.redis.exists(self._make_key(key)))
        except Exception as e:
            raise StorageError(f"Async Redis EXISTS error: {e}")

    async def clear(self) -> int:
        try:
            pattern = f"{self.key_prefix}*"
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                return int(await self.redis.delete(*keys))
            return 0
        except Exception as e:
            raise StorageError(f"Async Redis CLEAR error: {e}")

    async def get_stats(self) -> Dict[str, Any]:
        try:
            info = await self.redis.info()
            return {"redis_info": info}
        except Exception as e:
            logger.error(f"Failed to get Redis stats: {e}")
            return {}

    async def evaluate_lua(self, script: str, keys: List[str], args: List[Any]) -> Any:
        try:
            full_keys = [self._make_key(k) for k in keys]
            return await self.redis.eval(script, len(keys), *(full_keys + args))
        except Exception as e:
            raise StorageError(f"Async Redis Lua evaluation failed: {e}")

    async def shutdown(self):
        try:
            close = getattr(self.redis, "aclose", self.redis.close)
            await close()
        except Exception as e:
            logger.error(f"Async Redis shutdown error: {e}")
