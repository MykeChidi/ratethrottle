Storage Backends
================

RateThrottle supports multiple storage backends to persist rate limiting state. Choose the right backend based on your deployment architecture.

Available Backends
------------------

In-Memory Storage
~~~~~~~~~~~~~~~~~

**Best for**: Development, testing, single-instance applications

**Pros**:
* No external dependencies
* Extremely fast
* Simple setup

**Cons**:
* State lost on restart
* Not suitable for distributed systems
* Limited by available RAM

Redis Storage
~~~~~~~~~~~~~

**Best for**: Production, distributed systems, high availability

**Pros**:
* Distributed across multiple servers
* Persistent (survives restarts)
* Supports clustering
* Atomic operations

**Cons**:
* Requires Redis server
* Network latency
* Additional infrastructure

In-Memory Storage
-----------------

Usage
~~~~~

.. code-block:: python

    from ratethrottle import RateThrottleCore, InMemoryStorage

    # Create storage
    storage = InMemoryStorage()
    
    # Use with limiter
    limiter = RateThrottleCore(storage=storage)

Or use the helper:

.. code-block:: python

    from ratethrottle import create_limiter

    limiter = create_limiter()  # Defaults to in-memory

Configuration
~~~~~~~~~~~~~

In-memory storage has no configuration options. It automatically manages cleanup of expired entries.

When to Use
~~~~~~~~~~~

* Development and testing
* Single-instance applications
* Very high-performance requirements (no network)
* Temporary or ephemeral rate limiting

Redis Storage
-------------

Installation
~~~~~~~~~~~~

.. code-block:: bash

    pip install ratethrottle[redis]

Basic Usage
~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import create_limiter

    limiter = create_limiter(
        storage='redis',
        redis_url='redis://localhost:6379/0'
    )

Advanced Configuration
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import redis
    from ratethrottle import RateThrottleCore, RedisStorage

    # Create Redis client with options
    redis_client = redis.from_url(
        'redis://localhost:6379/0',
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
        max_connections=50
    )

    # Create storage
    storage = RedisStorage(redis_client)
    
    # Use with limiter
    limiter = RateThrottleCore(storage=storage)

Redis Connection Options
~~~~~~~~~~~~~~~~~~~~~~~~

Connection Pooling
^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from redis import ConnectionPool
    import redis
    from ratethrottle import RedisStorage

    # Create connection pool
    pool = ConnectionPool(
        host='localhost',
        port=6379,
        db=0,
        max_connections=50,
        socket_timeout=5,
        socket_connect_timeout=5
    )

    # Create client from pool
    redis_client = redis.Redis(connection_pool=pool)
    storage = RedisStorage(redis_client)

SSL/TLS Connection
^^^^^^^^^^^^^^^^^^

.. code-block:: python

    redis_client = redis.from_url(
        'rediss://localhost:6380/0',  # Note: rediss://
        ssl_cert_reqs='required',
        ssl_ca_certs='/path/to/ca.pem',
        ssl_certfile='/path/to/client.crt',
        ssl_keyfile='/path/to/client.key'
    )

Redis Sentinel
^^^^^^^^^^^^^^

For high availability:

.. code-block:: python

    from redis.sentinel import Sentinel

    # Connect to Sentinel
    sentinel = Sentinel([
        ('sentinel1', 26379),
        ('sentinel2', 26379),
        ('sentinel3', 26379)
    ], socket_timeout=0.5)

    # Get master
    redis_client = sentinel.master_for(
        'mymaster',
        socket_timeout=5,
        decode_responses=False
    )

    storage = RedisStorage(redis_client)

Redis Cluster
^^^^^^^^^^^^^

For distributed Redis:

.. code-block:: python

    from redis.cluster import RedisCluster

    redis_client = RedisCluster(
        host='localhost',
        port=7000,
        decode_responses=False
    )

    storage = RedisStorage(redis_client)

Storage Operations
------------------

All storage backends implement the same interface:

Get
~~~

.. code-block:: python

    value = storage.get('key')
    # Returns: value if exists, None otherwise

Set
~~~

.. code-block:: python

    storage.set('key', 'value')
    
    # With TTL (time-to-live)
    storage.set('key', 'value', ttl=60)  # Expires in 60 seconds

Increment
~~~~~~~~~

.. code-block:: python

    # Atomic increment
    new_value = storage.increment('counter', amount=1)
    
    # With TTL for new keys
    new_value = storage.increment('counter', amount=1, ttl=60)

Delete
~~~~~~

.. code-block:: python

    deleted = storage.delete('key')
    # Returns: True if deleted, False if key didn't exist

Exists
~~~~~~

.. code-block:: python

    exists = storage.exists('key')
    # Returns: True if exists, False otherwise

Clear
~~~~~

.. code-block:: python

    # Clear all keys (use carefully!)
    storage.clear()

Performance Considerations
--------------------------

In-Memory
~~~~~~~~~

* **Speed**: ~1-10 microseconds per operation
* **Throughput**: Millions of operations per second
* **Latency**: Near-zero (no network)
* **Scalability**: Single instance only

Redis
~~~~~

* **Speed**: ~1-5 milliseconds per operation (local network)
* **Throughput**: 10,000-100,000+ ops/sec depending on setup
* **Latency**: Network-dependent (0.1-10ms typical)
* **Scalability**: Horizontally scalable with clustering

Optimizing Redis Performance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Use Connection Pooling**:

.. code-block:: python

    # Good: Reuse connections
    pool = ConnectionPool(max_connections=50)
    client = redis.Redis(connection_pool=pool)

2. **Pipeline Operations** (if doing batch updates):

.. code-block:: python

    pipe = redis_client.pipeline()
    pipe.set('key1', 'value1')
    pipe.set('key2', 'value2')
    pipe.execute()

3. **Deploy Redis Closer**:
   * Same datacenter/region
   * Same availability zone
   * Co-located with application servers

4. **Use Appropriate Redis Instance**:
   * Sufficient RAM for your data
   * Network-optimized (enhanced networking)
   * Persistent storage if needed

Distributed Systems
-------------------

When running multiple application servers, use Redis:

Architecture
~~~~~~~~~~~~

.. code-block:: text

    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │   Server 1  │     │   Server 2  │     │   Server 3  │
    │  (App + RL) │     │  (App + RL) │     │  (App + RL) │
    └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
           │                   │                   │
           └───────────────────┼───────────────────┘
                               │
                               ▼
                       ┌───────────────┐
                       │  Redis Server │
                       │ (Shared State)│
                       └───────────────┘

Implementation
~~~~~~~~~~~~~~

Each server connects to the same Redis:

.. code-block:: python

    # On all servers:
    from ratethrottle import create_limiter, RateThrottleRule

    # Same Redis URL on all servers
    limiter = create_limiter(
        storage='redis',
        redis_url='redis://redis-server:6379/0'
    )

    # Same rules on all servers
    rule = RateThrottleRule(
        name="api_limit",
        limit=1000,
        window=60
    )
    limiter.add_rule(rule)

**Result**: All servers share the same rate limit. A client hitting Server 1 and Server 2 will have their requests counted together.

High Availability
-----------------

Redis Sentinel Setup
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from redis.sentinel import Sentinel
    from ratethrottle import RateThrottleCore, RedisStorage

    # Configure Sentinel
    sentinel = Sentinel([
        ('sentinel-1', 26379),
        ('sentinel-2', 26379),
        ('sentinel-3', 26379)
    ])

    # Get master (with automatic failover)
    redis_client = sentinel.master_for(
        'mymaster',
        socket_timeout=5
    )

    storage = RedisStorage(redis_client)
    limiter = RateThrottleCore(storage=storage)

Redis Persistence
~~~~~~~~~~~~~~~~~

Configure Redis for persistence:

.. code-block:: bash

    # redis.conf
    save 900 1      # Save after 900s if 1 key changed
    save 300 10     # Save after 300s if 10 keys changed
    save 60 10000   # Save after 60s if 10000 keys changed

    appendonly yes  # Enable AOF persistence
    appendfsync everysec  # Fsync every second

Custom Storage Backend
----------------------

You can implement custom storage backends:

.. code-block:: python

    from ratethrottle.storage_backend import StorageBackend
    from typing import Any, Optional

    class CustomStorage(StorageBackend):
        def get(self, key: str) -> Optional[Any]:
            # Your implementation
            pass

        def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
            # Your implementation
            pass

        def increment(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
            # Your implementation
            pass

        def delete(self, key: str) -> bool:
            # Your implementation
            pass

        def exists(self, key: str) -> bool:
            # Your implementation
            pass

        def clear(self) -> int:
            # Your implementation
            pass

Use your custom storage:

.. code-block:: python

    storage = CustomStorage()
    limiter = RateThrottleCore(storage=storage)

Monitoring Storage
------------------

Redis Monitoring
~~~~~~~~~~~~~~~~

.. code-block:: python

    # Check Redis connection
    try:
        redis_client.ping()
        print("Redis connected")
    except Exception as e:
        print(f"Redis error: {e}")

    # Get Redis info
    info = redis_client.info()
    print(f"Used memory: {info['used_memory_human']}")
    print(f"Connected clients: {info['connected_clients']}")

Storage Metrics
~~~~~~~~~~~~~~~

.. code-block:: python

    # Get metrics from RateThrottle
    metrics = limiter.get_metrics()
    
    # Storage type
    status = limiter.get_status()
    print(f"Storage: {status['storage_type']}")

Best Practices
--------------

1. **Use Redis in Production**
   - Always use Redis for production deployments
   - In-memory is only for development/testing

2. **Configure Connection Pooling**
   - Set max_connections based on your concurrency needs
   - Typical: 10-50 connections per application instance

3. **Set Appropriate Timeouts**
   - socket_timeout: 5 seconds
   - socket_connect_timeout: 5 seconds
   - Adjust based on network conditions

4. **Enable Persistence**
   - Use AOF for durability
   - Configure save points for snapshots
   - Test recovery procedures

5. **Monitor Redis Health**
   - Track memory usage
   - Monitor connection count
   - Set up alerts for failures

6. **Handle Connection Failures**
   - Use retry_on_timeout=True
   - Implement circuit breakers
   - Have fallback strategies

Next Steps
----------

* Configure advanced :doc:`configuration` options
* Set up :doc:`../frameworks/flask` or other framework integration
* Implement :doc:`../advanced/distributed` patterns
