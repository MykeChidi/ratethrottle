"""
Tests for async storage backends
"""

import pytest
import asyncio
from ratethrottle.async_storage import AsyncInMemoryStorage, AsyncRedisStorage
from ratethrottle.exceptions import StorageError


@pytest.fixture
async def in_memory_storage():
    """Create in-memory storage"""
    storage = AsyncInMemoryStorage()
    yield storage
    await storage.shutdown()


class TestAsyncInMemoryStorage:
    """Test AsyncInMemoryStorage"""

    @pytest.mark.asyncio
    async def test_set_and_get(self, in_memory_storage):
        """Test setting and getting values"""
        await in_memory_storage.set("key1", "value1")
        value = await in_memory_storage.get("key1")
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, in_memory_storage):
        """Test getting nonexistent key"""
        value = await in_memory_storage.get("nonexistent")
        assert value is None

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, in_memory_storage):
        """Test setting value with TTL"""
        await in_memory_storage.set("key1", "value1", ttl=1)
        value = await in_memory_storage.get("key1")
        assert value == "value1"
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        value = await in_memory_storage.get("key1")
        assert value is None

    @pytest.mark.asyncio
    async def test_set_if_not_exists_new_key(self, in_memory_storage):
        """Test set_if_not_exists with new key"""
        result = await in_memory_storage.set_if_not_exists("key1", "value1")
        assert result is True
        
        value = await in_memory_storage.get("key1")
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_set_if_not_exists_existing_key(self, in_memory_storage):
        """Test set_if_not_exists with existing key"""
        await in_memory_storage.set("key1", "original")
        
        result = await in_memory_storage.set_if_not_exists("key1", "new")
        assert result is False
        
        value = await in_memory_storage.get("key1")
        assert value == "original"

    @pytest.mark.asyncio
    async def test_increment(self, in_memory_storage):
        """Test incrementing counter"""
        result1 = await in_memory_storage.increment("counter", 1)
        assert result1 == 1
        
        result2 = await in_memory_storage.increment("counter", 5)
        assert result2 == 6

    @pytest.mark.asyncio
    async def test_increment_with_ttl(self, in_memory_storage):
        """Test incrementing counter with TTL"""
        result = await in_memory_storage.increment("counter", 1, ttl=60)
        assert result == 1
        
        value = await in_memory_storage.get("counter")
        assert value == 1

    @pytest.mark.asyncio
    async def test_delete(self, in_memory_storage):
        """Test deleting key"""
        await in_memory_storage.set("key1", "value1")
        
        result = await in_memory_storage.delete("key1")
        assert result is True
        
        value = await in_memory_storage.get("key1")
        assert value is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, in_memory_storage):
        """Test deleting nonexistent key"""
        result = await in_memory_storage.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_many(self, in_memory_storage):
        """Test deleting multiple keys"""
        await in_memory_storage.set("key1", "value1")
        await in_memory_storage.set("key2", "value2")
        await in_memory_storage.set("key3", "value3")
        
        count = await in_memory_storage.delete_many(["key1", "key2", "nonexistent"])
        assert count == 2
        
        assert await in_memory_storage.get("key1") is None
        assert await in_memory_storage.get("key2") is None
        assert await in_memory_storage.get("key3") == "value3"

    @pytest.mark.asyncio
    async def test_exists(self, in_memory_storage):
        """Test checking key existence"""
        await in_memory_storage.set("key1", "value1")
        
        assert await in_memory_storage.exists("key1") is True
        assert await in_memory_storage.exists("nonexistent") is False

    @pytest.mark.asyncio
    async def test_exists_expired(self, in_memory_storage):
        """Test checking existence of expired key"""
        await in_memory_storage.set("key1", "value1", ttl=1)
        
        await asyncio.sleep(1.1)
        assert await in_memory_storage.exists("key1") is False

    @pytest.mark.asyncio
    async def test_clear(self, in_memory_storage):
        """Test clearing all data"""
        await in_memory_storage.set("key1", "value1")
        await in_memory_storage.set("key2", "value2")
        
        count = await in_memory_storage.clear()
        assert count == 2
        
        assert await in_memory_storage.get("key1") is None
        assert await in_memory_storage.get("key2") is None

    @pytest.mark.asyncio
    async def test_get_stats(self, in_memory_storage):
        """Test getting statistics"""
        await in_memory_storage.set("key1", "value1")
        await in_memory_storage.get("key1")
        await in_memory_storage.delete("key1")
        
        stats = await in_memory_storage.get_stats()
        assert "total_keys" in stats
        assert "sets" in stats
        assert "gets" in stats
        assert "deletes" in stats
        assert stats["sets"] >= 1
        assert stats["gets"] >= 1
        assert stats["deletes"] >= 1

    @pytest.mark.asyncio
    async def test_check_and_delete_if_expired(self, in_memory_storage):
        """Test checking and deleting if expired"""
        await in_memory_storage.set("key1", "value1")
        
        # Key not expired
        exists, value = await in_memory_storage.check_and_delete_if_expired("key1")
        assert exists is True
        assert value == "value1"
        
        # Set with TTL and wait
        await in_memory_storage.set("key2", "value2", ttl=1)
        await asyncio.sleep(1.1)
        
        exists, value = await in_memory_storage.check_and_delete_if_expired("key2")
        assert exists is False
        assert value is None

    @pytest.mark.asyncio
    async def test_health_check(self, in_memory_storage):
        """Test health check"""
        result = await in_memory_storage.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_get_info(self, in_memory_storage):
        """Test getting storage info"""
        info = await in_memory_storage.get_info()
        assert "type" in info
        assert "healthy" in info
        assert info["type"] == "AsyncInMemoryStorage"

    @pytest.mark.asyncio
    async def test_invalid_key_type(self, in_memory_storage):
        """Test invalid key type raises error"""
        with pytest.raises(StorageError):
            await in_memory_storage.set(123, "value")

    @pytest.mark.asyncio
    async def test_negative_ttl(self, in_memory_storage):
        """Test negative TTL raises error"""
        with pytest.raises(StorageError):
            await in_memory_storage.set("key1", "value1", ttl=-1)

    @pytest.mark.asyncio
    async def test_increment_invalid_amount(self, in_memory_storage):
        """Test incrementing with invalid amount type"""
        with pytest.raises(StorageError):
            await in_memory_storage.increment("counter", "invalid")

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, in_memory_storage):
        """Test concurrent storage operations"""
        async def set_and_get(key, value):
            await in_memory_storage.set(key, value)
            return await in_memory_storage.get(key)
        
        tasks = [
            set_and_get(f"key_{i}", f"value_{i}")
            for i in range(20)
        ]
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 20
        assert all(results)

    @pytest.mark.asyncio
    async def test_concurrent_increments(self, in_memory_storage):
        """Test concurrent increment operations"""
        tasks = [
            in_memory_storage.increment("counter", 1)
            for _ in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 10
        
        # Final value should be 10
        final_value = await in_memory_storage.get("counter")
        assert final_value == 10

    @pytest.mark.asyncio
    async def test_serialization_of_complex_types(self, in_memory_storage):
        """Test storing and retrieving complex types"""
        complex_value = {
            "nested": {
                "list": [1, 2, 3],
                "dict": {"key": "value"}
            },
            "timestamp": 1234567890
        }
        
        await in_memory_storage.set("complex", complex_value)
        retrieved = await in_memory_storage.get("complex")
        assert retrieved == complex_value

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """Test LRU eviction when max keys reached"""
        storage = AsyncInMemoryStorage(max_keys=5)
        
        # Fill to max
        for i in range(5):
            await storage.set(f"key_{i}", f"value_{i}")
        
        # Next set should trigger eviction
        await storage.set("key_5", "value_5")
        
        # Should have 5 keys
        stats = await storage.get_stats()
        assert stats["total_keys"] == 5
        
        await storage.shutdown()
