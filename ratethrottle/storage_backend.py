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
from typing import Any, Dict, List, Optional, Tuple, Union

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

    @abstractmethod
    def check_and_delete_if_expired(self, key: str) -> Tuple[bool, Optional[Any]]:
        """
        Atomically check if key exists, get its value, and delete if expired.

        Returns:
            Tuple of (exists: bool, value: Optional[Any])
            - (False, None) if key doesn't exist or has expired
            - (True, value) if key exists and not expired

        Raises:
            StorageError: If operation fails
        """
        pass

    @abstractmethod
    def set_if_not_exists(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Atomically set value only if key doesn't exist (SET NX for Redis).

        Returns:
            True if set successfully, False if already exists

        Raises:
            StorageError: If operation fails
        """
        pass

    @abstractmethod
    def delete_many(self, keys: List[str]) -> int:
        """
        Delete multiple keys atomically.

        Returns:
            Number of keys deleted

        Raises:
            StorageError: If operation fails
        """
        pass

    def evaluate_lua(self, script: str, keys: List[str], args: List[Any]) -> Any:
        """
        Evaluate a Lua script (if supported)
        """
        raise NotImplementedError("evaluate_lua is only supported in RedisStorage")

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
    Thread-safe in-memory storage with automatic TTL cleanup

    Features:
        - Thread-safe operations with RLock
        - Automatic expiration cleanup thread
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

    def __init__(self, cleanup_interval: int = 300, max_keys: int = 1000000):
        """
        Initialize in-memory storage.

        Args:
            cleanup_interval: Seconds between expired key cleanup (default: 5 min)
            max_keys: Maximum keys before cleanup (default: 1M)
        """
        self._data: Dict[str, Tuple[Any, Optional[float]]] = {}  # (value, expiry_time)
        self._lock = threading.RLock()
        self._cleanup_interval = cleanup_interval
        self.max_keys = max_keys
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stats = {"sets": 0, "gets": 0, "deletes": 0, "cleanups": 0, "evictions": 0}

        # Start cleanup daemon
        self._start_cleanup_daemon()
        logger.info(f"InMemoryStorage: cleanup every {cleanup_interval}s, max {max_keys} keys")

    def _start_cleanup_daemon(self):
        """Start background cleanup thread"""

        def cleanup_loop():
            while not self._stop_event.is_set():
                try:
                    self._cleanup_expired()
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
                finally:
                    # Wait with interruption support
                    self._stop_event.wait(self._cleanup_interval)

        self._cleanup_thread = threading.Thread(
            target=cleanup_loop, name="ratethrottle-memory-cleanup", daemon=True
        )
        self._cleanup_thread.start()

    def _cleanup_expired(self) -> int:
        """Remove expired keys"""
        with self._lock:
            now = time.time()
            expired = []

            for k, (_, expiry) in self._data.items():
                if expiry is not None and expiry <= now:
                    expired.append(k)

            for k in expired:
                del self._data[k]

            if expired:
                logger.debug(f"Cleaned {len(expired)} expired keys, {len(self._data)} remaining")
                self._stats["cleanups"] += 1

            return len(expired)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value with optional TTL"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        if ttl is not None and ttl < 0:
            raise StorageError(f"TTL cannot be negative, got {ttl}")

        expiry_time = (time.time() + ttl) if ttl else None

        with self._lock:
            # Evict if too many keys
            if len(self._data) >= self.max_keys:
                # Remove oldest expired or least recently used
                self._evict_lru()

            self._data[key] = (value, expiry_time)
            self._stats["sets"] += 1

        return True

    def get(self, key: str) -> Optional[Any]:
        """Get value if exists and not expired"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        with self._lock:
            if key not in self._data:
                return None

            value, expiry = self._data[key]

            # Check expiry
            if expiry is not None and expiry <= time.time():
                del self._data[key]
                return None

            self._stats["gets"] += 1
            return value

    def check_and_delete_if_expired(self, key: str) -> Tuple[bool, Optional[Any]]:
        """Atomically check, get, and delete if expired"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        with self._lock:
            if key not in self._data:
                return (False, None)

            value, expiry = self._data[key]

            if expiry is not None and expiry <= time.time():
                del self._data[key]
                return (False, None)

            return (True, value)

    def set_if_not_exists(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Atomically set only if doesn't exist"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        expiry_time = (time.time() + ttl) if ttl else None

        with self._lock:
            if key in self._data:
                value_, expiry = self._data[key]
                # Check if existing key is expired
                if expiry is not None and expiry <= time.time():
                    del self._data[key]
                else:
                    return False

            self._data[key] = (value, expiry_time)
            return True

    def increment(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
        """Increment counter atomically"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        if not isinstance(amount, int):
            raise StorageError(f"Amount must be int, got {type(amount).__name__}")

        with self._lock:
            if key in self._data:
                value, expiry = self._data[key]
                if expiry and expiry <= time.time():
                    del self._data[key]
                    value = 0
            else:
                value = 0

            if not isinstance(value, (int, float)):
                raise StorageError(f"Cannot increment non-numeric value: {type(value).__name__}")

            new_value = int(value) + amount
            expiry_time = (time.time() + ttl) if ttl else None
            self._data[key] = (new_value, expiry_time)
            self._stats["sets"] += 1

            return new_value

    def delete(self, key: str) -> bool:
        """Delete key"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        with self._lock:
            if key in self._data:
                del self._data[key]
                self._stats["deletes"] += 1
                return True
            return False

    def delete_many(self, keys: List[str]) -> int:
        """Delete multiple keys"""
        count = 0
        with self._lock:
            for key in keys:
                if not isinstance(key, str):
                    continue
                if key in self._data:
                    del self._data[key]
                    count += 1
            self._stats["deletes"] += count
        return count

    def exists(self, key: str) -> bool:
        """Check if key exists and not expired"""
        if not isinstance(key, str):
            raise StorageError(f"Key must be string, got {type(key).__name__}")

        with self._lock:
            if key not in self._data:
                return False

            _, expiry = self._data[key]
            if expiry is not None and expiry <= time.time():
                del self._data[key]
                return False

            return True

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
                **self._stats,
            }

    def _evict_lru(self):
        """Evict least recently used or first expired key"""
        # First try to evict expired
        now = time.time()
        for k, (_, expiry) in list(self._data.items()):
            if expiry and expiry <= now:
                del self._data[k]
                self._stats["evictions"] += 1
                return

        # If no expired, evict first key (FIFO)
        if self._data:
            k = next(iter(self._data))
            del self._data[k]
            self._stats["evictions"] += 1

    def shutdown(self):
        """Cleanup resources"""
        self._stop_event.set()
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
        self._data.clear()
        logger.info("InMemoryStorage shutdown")

    def get_info(self) -> Dict[str, Any]:
        """Get storage info"""
        with self._lock:
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

    def check_and_delete_if_expired(self, key: str) -> Tuple[bool, Optional[Any]]:
        """Atomically check and delete if expired using Lua script"""
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
            import time

            result = self.redis.eval(script, 1, full_key, str(time.time()))
            return bool(result[0]), self._deserialize(result[1]) if result[1] else None
        except Exception as e:
            raise StorageError(f"Atomic check_and_delete failed: {e}")

    def set_if_not_exists(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Atomically set only if doesn't exist (SET NX)"""
        try:
            full_key = self._make_key(key)
            serialized = self._serialize(value)

            if ttl:
                result = self.redis.set(full_key, serialized, nx=True, ex=ttl)
            else:
                result = self.redis.set(full_key, serialized, nx=True)

            return bool(result)
        except Exception as e:
            raise StorageError(f"set_if_not_exists failed: {e}")

    def delete_many(self, keys: List[str]) -> Any:
        """Delete multiple keys"""
        if not keys:
            return 0

        try:
            full_keys = [self._make_key(k) for k in keys]
            return self.redis.delete(*full_keys)
        except Exception as e:
            raise StorageError(f"delete_many failed: {e}")

    def evaluate_lua(self, script: str, keys: List[str], args: List[Any]) -> Any:
        """Evaluate a Lua script atomically"""
        try:
            full_keys = [self._make_key(k) for k in keys]
            return self.redis.eval(script, len(keys), *(full_keys + args))
        except Exception as e:
            logger.error(f"Redis script execution error: {e}")
            raise StorageError(f"Failed to execute Lua script: {e}") from e

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
