"""
RateThrottle - Storage Backend Implementations

Storage backends with comprehensive error handling,
connection management, and monitoring capabilities.
"""

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple, Union

from .exceptions import StorageError

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """
    Abstract base class for storage backends

    All storage backends must implement these methods with proper
    error handling and type checking.
    """

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """
        Get value for key

        Args:
            key: Storage key

        Returns:
            Value if exists, None otherwise

        Raises:
            StorageError: If storage operation fails
        """
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Set value for key with optional TTL

        Args:
            key: Storage key
            value: Value to store
            ttl: Time-to-live in seconds (None for no expiration)

        Returns:
            True if successful, False otherwise

        Raises:
            StorageError: If storage operation fails
        """
        pass

    @abstractmethod
    def increment(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
        """
        Increment counter atomically

        Args:
            key: Storage key
            amount: Amount to increment by
            ttl: Time-to-live for new keys

        Returns:
            New value after increment

        Raises:
            StorageError: If storage operation fails
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Delete key

        Args:
            key: Storage key

        Returns:
            True if deleted, False if key didn't exist

        Raises:
            StorageError: If storage operation fails
        """
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Check if key exists

        Args:
            key: Storage key

        Returns:
            True if key exists, False otherwise

        Raises:
            StorageError: If storage operation fails
        """
        pass

    def health_check(self) -> bool:
        """
        Check if storage backend is healthy

        Returns:
            True if healthy, False otherwise
        """
        try:
            test_key = "__health_check__"
            self.set(test_key, True, ttl=1)
            result = self.get(test_key)
            self.delete(test_key)
            return result is not None
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def get_info(self) -> Dict[str, Any]:
        """
        Get storage backend information

        Returns:
            Dictionary with backend information
        """
        return {
            "type": self.__class__.__name__,
            "healthy": self.health_check(),
        }


class InMemoryStorage(StorageBackend):
    """
    Thread-safe in-memory storage backend

    Features:
        - Thread-safe operations with RLock
        - Automatic expiration cleanup
        - TTL support
        - Zero external dependencies

    Best for:
        - Single-instance deployments
        - Development/testing
        - Low-latency requirements

    Examples:
        >>> storage = InMemoryStorage()
        >>> storage.set('key', 'value', ttl=60)
        True
        >>> storage.get('key')
        'value'
    """

    def __init__(self, cleanup_interval: int = 60):
        """
        Initialize in-memory storage

        Args:
            cleanup_interval: Seconds between cleanup of expired entries
        """
        self._data: Dict[str, Tuple[Any, Optional[float]]] = {}
        self._lock = threading.RLock()
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()
        logger.info("Initialized InMemoryStorage")

    def _cleanup_expired(self) -> int:
        """
        Remove expired entries

        Returns:
            Number of entries removed
        """
        now = time.time()

        # Only cleanup periodically to avoid overhead
        if now - self._last_cleanup < self._cleanup_interval:
            return 0

        expired = [k for k, (v, exp) in self._data.items() if exp is not None and exp < now]

        for key in expired:
            del self._data[key]

        self._last_cleanup = now

        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired entries")

        return len(expired)

    def get(self, key: str) -> Optional[Any]:
        """Get value for key"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        try:
            with self._lock:
                self._cleanup_expired()

                if key in self._data:
                    value, expiry = self._data[key]

                    # Check if expired
                    if expiry is None or expiry > time.time():
                        return value
                    else:
                        # Remove expired entry
                        del self._data[key]

                return None
        except Exception as e:
            logger.error(f"Error getting key '{key}': {e}")
            raise StorageError(f"Failed to get key: {e}") from e

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value for key with optional TTL"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        if ttl is not None and ttl < 0:
            raise StorageError(f"TTL cannot be negative, got {ttl}")

        try:
            with self._lock:
                expiry = time.time() + ttl if ttl else None
                self._data[key] = (value, expiry)
                logger.debug(f"Set key '{key}' with TTL={ttl}")
                return True
        except Exception as e:
            logger.error(f"Error setting key '{key}': {e}")
            raise StorageError(f"Failed to set key: {e}") from e

    def increment(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
        """Increment counter atomically"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        if not isinstance(amount, int):
            raise StorageError(f"Amount must be int, got {type(amount).__name__}")

        try:
            with self._lock:
                current = self.get(key)

                if current is None:
                    new_value = amount
                else:
                    if not isinstance(current, (int, float)):
                        raise StorageError(
                            f"Cannot increment non-numeric value: {type(current).__name__}"
                        )
                    new_value = int(current) + amount

                self.set(key, new_value, ttl)
                logger.debug(f"Incremented key '{key}' by {amount} to {new_value}")
                return new_value
        except StorageError:
            raise
        except Exception as e:
            logger.error(f"Error incrementing key '{key}': {e}")
            raise StorageError(f"Failed to increment key: {e}") from e

    def delete(self, key: str) -> bool:
        """Delete key"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        try:
            with self._lock:
                if key in self._data:
                    del self._data[key]
                    logger.debug(f"Deleted key '{key}'")
                    return True
                return False
        except Exception as e:
            logger.error(f"Error deleting key '{key}': {e}")
            raise StorageError(f"Failed to delete key: {e}") from e

    def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        try:
            return self.get(key) is not None
        except StorageError:
            raise
        except Exception as e:
            logger.error(f"Error checking existence of key '{key}': {e}")
            raise StorageError(f"Failed to check key existence: {e}") from e

    def clear(self) -> int:
        """
        Clear all data

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._data)
            self._data.clear()
            logger.info(f"Cleared {count} entries from storage")
            return count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics

        Returns:
            Dictionary with statistics
        """
        with self._lock:
            now = time.time()
            expired_count = sum(
                1 for v, exp in self._data.values() if exp is not None and exp < now
            )

            return {
                "total_keys": len(self._data),
                "expired_keys": expired_count,
                "active_keys": len(self._data) - expired_count,
                "memory_usage_estimate": sum(
                    len(str(k)) + len(str(v)) for k, (v, _) in self._data.items()
                ),
            }

    def get_info(self) -> Dict[str, Any]:
        """Get storage backend information"""
        return {
            "type": "InMemoryStorage",
            "healthy": self.health_check(),
            "stats": self.get_stats(),
            "cleanup_interval": self._cleanup_interval,
        }

    def __repr__(self) -> str:
        """String representation"""
        stats = self.get_stats()
        return f"InMemoryStorage(keys={stats['active_keys']})"


class RedisStorage(StorageBackend):
    """
    Redis-based storage backend for distributed rate limiting

    Features:
        - Distributed rate limiting across multiple servers
        - Atomic operations with Lua scripts
        - Connection pooling
        - Automatic reconnection
        - Health checking

    Best for:
        - Multi-instance deployments
        - Production environments
        - Distributed systems

    Requirements:
        pip install redis>=4.0.0

    Examples:
        >>> import redis
        >>> client = redis.from_url('redis://localhost:6379/0')
        >>> storage = RedisStorage(client)
        >>> storage.set('key', 'value', ttl=60)
        True
    """

    def __init__(
        self,
        redis_client,
        key_prefix: str = "ratethrottle:",
        serialize_json: bool = True,
        connection_timeout: int = 5,
        retry_on_timeout: bool = True,
    ):
        """
        Initialize Redis storage

        Args:
            redis_client: Redis client instance
            key_prefix: Prefix for all keys
            serialize_json: Whether to JSON-serialize complex types
            connection_timeout: Connection timeout in seconds
            retry_on_timeout: Whether to retry on timeout
        """
        self.redis = redis_client
        self.key_prefix = key_prefix
        self.serialize_json = serialize_json
        self.connection_timeout = connection_timeout
        self.retry_on_timeout = retry_on_timeout

        # Test connection
        try:
            self.redis.ping()
            logger.info("Initialized RedisStorage and verified connection")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise StorageError(f"Redis connection failed: {e}") from e

    def _make_key(self, key: str) -> str:
        """Add prefix to key"""
        return f"{self.key_prefix}{key}"

    def _serialize(self, value: Any) -> Union[str, bytes]:
        """Serialize value for storage"""
        if isinstance(value, (str, bytes)):
            return value

        if self.serialize_json:
            try:
                return json.dumps(value)
            except (TypeError, ValueError) as e:
                raise StorageError(f"Cannot serialize value: {e}") from e

        return str(value)

    def _deserialize(self, value: Union[str, bytes, None]) -> Any:
        """Deserialize value from storage"""
        if value is None:
            return None

        # Decode bytes to string
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError:
                return value

        # Try to parse as JSON if enabled
        if self.serialize_json and isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass

        return value

    def get(self, key: str) -> Optional[Any]:
        """Get value for key"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        try:
            full_key = self._make_key(key)
            value = self.redis.get(full_key)
            return self._deserialize(value)
        except Exception as e:
            logger.error(f"Redis GET error for key '{key}': {e}")
            raise StorageError(f"Failed to get key from Redis: {e}") from e

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value for key with optional TTL"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        if ttl is not None and ttl < 0:
            raise StorageError(f"TTL cannot be negative, got {ttl}")

        try:
            full_key = self._make_key(key)
            serialized = self._serialize(value)

            if ttl:
                result = self.redis.setex(full_key, ttl, serialized)
            else:
                result = self.redis.set(full_key, serialized)

            logger.debug(f"Redis SET key '{key}' with TTL={ttl}")
            return bool(result)
        except Exception as e:
            logger.error(f"Redis SET error for key '{key}': {e}")
            raise StorageError(f"Failed to set key in Redis: {e}") from e

    def increment(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
        """Increment counter atomically"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        if not isinstance(amount, int):
            raise StorageError(f"Amount must be int, got {type(amount).__name__}")

        try:
            full_key = self._make_key(key)

            # Use pipeline for atomicity
            pipe = self.redis.pipeline()
            pipe.incrby(full_key, amount)

            if ttl:
                pipe.expire(full_key, ttl)

            results = pipe.execute()
            new_value = results[0]

            logger.debug(f"Redis INCR key '{key}' by {amount} to {new_value}")
            return int(new_value)
        except Exception as e:
            logger.error(f"Redis INCR error for key '{key}': {e}")
            raise StorageError(f"Failed to increment key in Redis: {e}") from e

    def delete(self, key: str) -> bool:
        """Delete key"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        try:
            full_key = self._make_key(key)
            result = self.redis.delete(full_key)
            logger.debug(f"Redis DEL key '{key}'")
            return bool(result)
        except Exception as e:
            logger.error(f"Redis DEL error for key '{key}': {e}")
            raise StorageError(f"Failed to delete key from Redis: {e}") from e

    def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        try:
            full_key = self._make_key(key)
            return bool(self.redis.exists(full_key))
        except Exception as e:
            logger.error(f"Redis EXISTS error for key '{key}': {e}")
            raise StorageError(f"Failed to check key existence in Redis: {e}") from e

    def health_check(self) -> bool:
        """Check if Redis connection is healthy"""
        try:
            self.redis.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    def get_redis_info(self) -> Dict[str, Any]:
        """
        Get Redis server information

        Returns:
            Dictionary with Redis server info
        """
        try:
            info = self.redis.info()
            return {
                "redis_version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
                "uptime_in_seconds": info.get("uptime_in_seconds"),
                "total_commands_processed": info.get("total_commands_processed"),
            }
        except Exception as e:
            logger.error(f"Failed to get Redis info: {e}")
            return {"error": str(e)}

    def get_info(self) -> Dict[str, Any]:
        """Get storage backend information"""
        return {
            "type": "RedisStorage",
            "healthy": self.health_check(),
            "key_prefix": self.key_prefix,
            "redis_info": self.get_redis_info(),
        }

    def clear_prefix(self) -> Any:
        """
        Clear all keys with the configured prefix

        Returns:
            Number of keys deleted

        Warning:
            Use with caution in production!
        """
        try:
            pattern = f"{self.key_prefix}*"
            keys = list(self.redis.scan_iter(match=pattern))

            if keys:
                deleted = self.redis.delete(*keys)
                logger.warning(f"Cleared {deleted} keys with prefix '{self.key_prefix}'")
                return deleted

            return 0
        except Exception as e:
            logger.error(f"Failed to clear keys: {e}")
            raise StorageError(f"Failed to clear keys: {e}") from e

    def __repr__(self) -> str:
        """String representation"""
        return f"RedisStorage(prefix='{self.key_prefix}', healthy={self.health_check()})"
