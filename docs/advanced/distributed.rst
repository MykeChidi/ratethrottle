Distributed Deployments
=======================

Deploy RateThrottle across multiple servers with Redis.

Overview
--------

For applications running on multiple servers:

* Use Redis storage backend
* All servers share rate limit state
* Consistent limits across instances
* High availability with Redis Sentinel

Architecture
------------

.. code-block:: text

    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │   Server 1  │     │   Server 2  │     │   Server 3  │
    └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
           │                   │                   │
           └───────────────────┼───────────────────┘
                               │
                               ▼
                       ┌───────────────┐
                       │  Redis Server │
                       └───────────────┘

Setup
-----

Each Server
~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import create_limiter, RateThrottleRule

    # Same configuration on all servers
    limiter = create_limiter(
        storage='redis',
        redis_url='redis://redis-server:6379/0'
    )

    rule = RateThrottleRule(
        name="api_limit",
        limit=1000,
        window=60
    )
    limiter.add_rule(rule)

Result: Clients hitting different servers share the same 1000/min limit.

High Availability
-----------------

Using Redis Sentinel:

.. code-block:: python

    from redis.sentinel import Sentinel
    from ratethrottle import RateThrottleCore, RedisStorage

    sentinel = Sentinel([
        ('sentinel-1', 26379),
        ('sentinel-2', 26379),
        ('sentinel-3', 26379)
    ])

    redis_client = sentinel.master_for('mymaster')
    storage = RedisStorage(redis_client)
    limiter = RateThrottleCore(storage=storage)

Best Practices
--------------

1. **Use Connection Pooling**
   - Reuse Redis connections
   - Set max_connections appropriately

2. **Monitor Redis Health**
   - Track memory usage
   - Set up alerts

3. **Configure Persistence**
   - Enable AOF for durability
   - Set up regular backups

4. **Test Failover**
   - Verify Sentinel failover
   - Test recovery procedures

Next Steps
----------

* Configure :doc:`../user_guide/storage`
* Set up :doc:`ddos_protection`
* Monitor with :doc:`analytics`