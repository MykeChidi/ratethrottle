"""
Tests for storage backend implementations
"""

import time

import pytest

from ratethrottle.exceptions import StorageError
from ratethrottle.storage_backend import InMemoryStorage, StorageBackend


class TestStorageBackend:
    """Test abstract storage backend"""

    def test_abstract_methods(self):
        """Test that StorageBackend cannot be instantiated"""
        with pytest.raises(TypeError):
            StorageBackend()


class TestInMemoryStorage:
    """Test in-memory storage backend"""

    @pytest.fixture
    def storage(self):
        """Create storage instance"""
        return InMemoryStorage()

    def test_initialization(self):
        """Test storage initialization"""
        storage = InMemoryStorage(cleanup_interval=30)
        assert storage._cleanup_interval == 30
        assert len(storage._data) == 0

    def test_get_nonexistent_key(self, storage):
        """Test getting a non-existent key"""
        assert storage.get("nonexistent") is None

    def test_set_and_get(self, storage):
        """Test setting and getting a value"""
        storage.set("key1", "value1")
        assert storage.get("key1") == "value1"

    def test_set_with_ttl(self, storage):
        """Test setting a value with TTL"""
        storage.set("key1", "value1", ttl=1)
        assert storage.get("key1") == "value1"

        # Wait for expiration
        time.sleep(1.1)
        assert storage.get("key1") is None

    def test_set_overwrite(self, storage):
        """Test overwriting a value"""
        storage.set("key1", "value1")
        storage.set("key1", "value2")
        assert storage.get("key1") == "value2"

    def test_increment_new_key(self, storage):
        """Test incrementing a non-existent key"""
        result = storage.increment("counter")
        assert result == 1
        assert storage.get("counter") == 1

    def test_increment_existing_key(self, storage):
        """Test incrementing an existing key"""
        storage.set("counter", 5)
        result = storage.increment("counter")
        assert result == 6
        assert storage.get("counter") == 6

    def test_increment_by_amount(self, storage):
        """Test incrementing by a specific amount"""
        storage.set("counter", 10)
        result = storage.increment("counter", amount=5)
        assert result == 15

    def test_increment_with_ttl(self, storage):
        """Test incrementing with TTL"""
        result = storage.increment("counter", amount=1, ttl=1)
        assert result == 1

        time.sleep(1.1)
        assert storage.get("counter") is None

    def test_increment_non_numeric_raises_error(self, storage):
        """Test incrementing a non-numeric value raises error"""
        storage.set("key1", "string")

        with pytest.raises(StorageError, match="Cannot increment non-numeric"):
            storage.increment("key1")

    def test_delete_existing_key(self, storage):
        """Test deleting an existing key"""
        storage.set("key1", "value1")
        result = storage.delete("key1")
        assert result is True
        assert storage.get("key1") is None

    def test_delete_nonexistent_key(self, storage):
        """Test deleting a non-existent key"""
        result = storage.delete("nonexistent")
        assert result is False

    def test_exists_key_present(self, storage):
        """Test exists returns True for present key"""
        storage.set("key1", "value1")
        assert storage.exists("key1") is True

    def test_exists_key_absent(self, storage):
        """Test exists returns False for absent key"""
        assert storage.exists("nonexistent") is False

    def test_exists_expired_key(self, storage):
        """Test exists returns False for expired key"""
        storage.set("key1", "value1", ttl=1)
        time.sleep(1.1)
        assert storage.exists("key1") is False

    def test_cleanup_expired(self, storage):
        """Test cleanup of expired entries"""
        storage.set("key1", "value1", ttl=1)
        storage.set("key2", "value2")

        time.sleep(1.1)

        # Trigger cleanup
        storage.get("key2")

        # Check stats
        stats = storage.get_stats()
        assert stats["active_keys"] == 1

    def test_clear(self, storage):
        """Test clearing all data"""
        storage.set("key1", "value1")
        storage.set("key2", "value2")

        count = storage.clear()
        assert count == 2
        assert storage.get("key1") is None
        assert storage.get("key2") is None

    def test_get_stats(self, storage):
        """Test getting storage statistics"""
        storage.set("key1", "value1")
        storage.set("key2", "value2", ttl=1)

        stats = storage.get_stats()
        assert stats["total_keys"] == 2
        assert stats["active_keys"] == 2

        time.sleep(1.1)
        stats = storage.get_stats()
        assert stats["expired_keys"] > 0

    def test_get_info(self, storage):
        """Test getting storage info"""
        info = storage.get_info()
        assert info["type"] == "InMemoryStorage"
        assert "healthy" in info
        assert "stats" in info

    def test_health_check(self, storage):
        """Test health check"""
        assert storage.health_check() is True

    def test_invalid_key_type(self, storage):
        """Test that invalid key type raises error"""
        with pytest.raises(StorageError, match="Key must be string"):
            storage.get(123)

        with pytest.raises(StorageError, match="Key must be string"):
            storage.set(123, "value")

    def test_invalid_ttl(self, storage):
        """Test that negative TTL raises error"""
        with pytest.raises(StorageError, match="TTL cannot be negative"):
            storage.set("key", "value", ttl=-1)

    def test_invalid_increment_amount(self, storage):
        """Test that invalid increment amount raises error"""
        with pytest.raises(StorageError, match="Amount must be int"):
            storage.increment("key", amount="invalid")

    def test_multiple_values(self, storage):
        """Test storing different value types"""
        storage.set("string", "value")
        storage.set("int", 42)
        storage.set("float", 3.14)
        storage.set("list", [1, 2, 3])
        storage.set("dict", {"key": "value"})

        assert storage.get("string") == "value"
        assert storage.get("int") == 42
        assert storage.get("float") == 3.14
        assert storage.get("list") == [1, 2, 3]
        assert storage.get("dict") == {"key": "value"}

    def test_repr(self, storage):
        """Test string representation"""
        storage.set("key1", "value1")
        repr_str = repr(storage)
        assert "InMemoryStorage" in repr_str
        assert "keys=" in repr_str


class TestRedisStorage:
    """Test Redis storage backend"""

    @pytest.fixture
    def mock_redis(self, mocker):
        """Create mock Redis client"""
        mock = mocker.Mock()
        mock.ping.return_value = True
        return mock

    @pytest.fixture
    def storage(self, mock_redis):
        """Create Redis storage with mock client"""
        from ratethrottle.storage_backend import RedisStorage

        return RedisStorage(mock_redis)

    def test_initialization(self, mock_redis):
        """Test Redis storage initialization"""
        from ratethrottle.storage_backend import RedisStorage

        storage = RedisStorage(mock_redis, key_prefix="test:", serialize_json=True)

        assert storage.redis == mock_redis
        assert storage.key_prefix == "test:"
        assert storage.serialize_json is True
        mock_redis.ping.assert_called_once()

    def test_initialization_connection_failure(self, mocker):
        """Test initialization with connection failure"""
        from ratethrottle.storage_backend import RedisStorage

        mock_redis = mocker.Mock()
        mock_redis.ping.side_effect = Exception("Connection failed")

        with pytest.raises(StorageError, match="Redis connection failed"):
            RedisStorage(mock_redis)

    def test_get(self, storage, mock_redis):
        """Test getting a value"""
        mock_redis.get.return_value = b'"value"'

        result = storage.get("key")
        assert result == "value"
        mock_redis.get.assert_called_once_with("ratethrottle:key")

    def test_get_none(self, storage, mock_redis):
        """Test getting non-existent key"""
        mock_redis.get.return_value = None

        result = storage.get("key")
        assert result is None

    def test_set(self, storage, mock_redis):
        """Test setting a value"""
        mock_redis.set.return_value = True

        result = storage.set("key", "value")
        assert result is True
        mock_redis.set.assert_called_once()

    def test_set_with_ttl(self, storage, mock_redis):
        """Test setting with TTL"""
        mock_redis.setex.return_value = True

        result = storage.set("key", "value", ttl=60)
        assert result is True

        # Check that setex was called with correct arguments
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args

        # Verify the key and TTL
        assert call_args[0][0] == "ratethrottle:key"
        assert call_args[0][1] == 60

    def test_increment(self, storage, mock_redis):
        """Test incrementing a counter"""
        mock_redis.pipeline.return_value.execute.return_value = [5]

        result = storage.increment("counter")
        assert result == 5

    def test_increment_with_ttl(self, storage, mock_redis):
        """Test incrementing with TTL"""
        mock_redis.pipeline.return_value.execute.return_value = [1]

        result = storage.increment("counter", amount=1, ttl=60)
        assert result == 1

    def test_delete(self, storage, mock_redis):
        """Test deleting a key"""
        mock_redis.delete.return_value = 1

        result = storage.delete("key")
        assert result is True
        mock_redis.delete.assert_called_once_with("ratethrottle:key")

    def test_exists(self, storage, mock_redis):
        """Test checking key existence"""
        mock_redis.exists.return_value = 1

        result = storage.exists("key")
        assert result is True
        mock_redis.exists.assert_called_once_with("ratethrottle:key")

    def test_health_check(self, storage, mock_redis):
        """Test health check"""
        mock_redis.ping.return_value = True
        assert storage.health_check() is True

        mock_redis.ping.side_effect = Exception("Connection lost")
        assert storage.health_check() is False

    def test_get_redis_info(self, storage, mock_redis):
        """Test getting Redis info"""
        mock_redis.info.return_value = {
            "redis_version": "7.0.0",
            "connected_clients": 10,
            "used_memory_human": "1.5M",
            "uptime_in_seconds": 3600,
            "total_commands_processed": 1000,
        }

        info = storage.get_redis_info()
        assert info["redis_version"] == "7.0.0"
        assert info["connected_clients"] == 10

    def test_clear_prefix(self, storage, mock_redis):
        """Test clearing keys with prefix"""
        mock_redis.scan_iter.return_value = [b"ratethrottle:key1", b"ratethrottle:key2"]
        mock_redis.delete.return_value = 2

        count = storage.clear_prefix()
        assert count == 2

    def test_repr(self, storage):
        """Test string representation"""
        repr_str = repr(storage)
        assert "RedisStorage" in repr_str
        assert "prefix=" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
