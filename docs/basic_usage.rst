Basic Usage
===========

This guide covers the fundamental concepts and common usage patterns for RateThrottle.

Core Concepts
-------------

RateThrottle operates on three main components:

1. **Rules**: Define rate limiting policies (limit, window, strategy)
2. **Storage**: Persist rate limit state (in-memory or Redis)
3. **Limiter**: The core engine that enforces rules

Creating a Rate Limiter
-----------------------

Quick Creation
~~~~~~~~~~~~~~

The simplest way to create a limiter:

.. code-block:: python

    from ratethrottle import create_limiter

    # In-memory storage (single instance)
    limiter = create_limiter()

    # Redis storage (distributed)
    limiter = create_limiter('redis', 'redis://localhost:6379/0')

Manual Creation
~~~~~~~~~~~~~~~

For more control:

.. code-block:: python

    from ratethrottle import RateThrottleCore, InMemoryStorage

    # With in-memory storage
    storage = InMemoryStorage()
    limiter = RateThrottleCore(storage=storage)

    # With Redis storage
    from ratethrottle import RedisStorage
    import redis

    redis_client = redis.from_url('redis://localhost:6379/0')
    storage = RedisStorage(redis_client)
    limiter = RateThrottleCore(storage=storage)

Defining Rules
--------------

Basic Rule
~~~~~~~~~~

.. code-block:: python

    from ratethrottle import RateThrottleRule

    rule = RateThrottleRule(
        name="api_limit",
        limit=100,         # 100 requests
        window=60,         # per 60 seconds
    )

    limiter.add_rule(rule)

Rule with Strategy
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    rule = RateThrottleRule(
        name="api_burst",
        limit=100,
        window=60,
        strategy="token_bucket",  # token_bucket, leaky_bucket, fixed_window, sliding_window
        burst=150                 # allow bursts up to 150
    )

Rule with Scope
~~~~~~~~~~~~~~~

.. code-block:: python

    # Limit by IP address (default)
    ip_rule = RateThrottleRule(
        name="by_ip",
        limit=100,
        window=60,
        scope="ip"
    )

    # Limit by user ID
    user_rule = RateThrottleRule(
        name="by_user",
        limit=1000,
        window=60,
        scope="user"
    )

    # Limit by endpoint
    endpoint_rule = RateThrottleRule(
        name="by_endpoint",
        limit=500,
        window=60,
        scope="endpoint"
    )

    # Global limit (all requests)
    global_rule = RateThrottleRule(
        name="global",
        limit=10000,
        window=60,
        scope="global"
    )

Rule with Block Duration
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    rule = RateThrottleRule(
        name="api_protected",
        limit=10,
        window=60,
        block_duration=300  # Block for 5 minutes after exceeding limit
    )

Checking Rate Limits
--------------------

Basic Check
~~~~~~~~~~~

.. code-block:: python

    # Check if request is allowed
    status = limiter.check_rate_limit("192.168.1.1", "api_limit")

    if status.allowed:
        # Process request
        process_request()
    else:
        # Reject request
        return error_response(status.retry_after)

Using Status Object
~~~~~~~~~~~~~~~~~~~

The status object contains useful information:

.. code-block:: python

    status = limiter.check_rate_limit("192.168.1.1", "api_limit")

    print(f"Allowed: {status.allowed}")
    print(f"Remaining: {status.remaining}")
    print(f"Limit: {status.limit}")
    print(f"Reset time: {status.reset_time}")
    print(f"Retry after: {status.retry_after} seconds")
    print(f"Rule applied: {status.rule_name}")
    print(f"Blocked: {status.blocked}")

    # Convert to dict for JSON responses
    response_data = status.to_dict()

    # Convert to HTTP headers
    headers = status.to_headers()
    # Headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, Retry-After

Adding Metadata
~~~~~~~~~~~~~~~

Track additional context with requests:

.. code-block:: python

    metadata = {
        'user_id': 'user123',
        'endpoint': '/api/data',
        'method': 'GET'
    }

    status = limiter.check_rate_limit(
        identifier="192.168.1.1",
        rule_name="api_limit",
        metadata=metadata
    )

Managing Rules
--------------

Add Rules
~~~~~~~~~

.. code-block:: python

    rule1 = RateThrottleRule(name="rule1", limit=100, window=60)
    rule2 = RateThrottleRule(name="rule2", limit=1000, window=3600)

    limiter.add_rule(rule1)
    limiter.add_rule(rule2)

Remove Rules
~~~~~~~~~~~~

.. code-block:: python

    limiter.remove_rule("rule1")

List Rules
~~~~~~~~~~

.. code-block:: python

    rules = limiter.list_rules()
    for rule in rules:
        print(f"{rule.name}: {rule.limit}/{rule.window}s")

Get Specific Rule
~~~~~~~~~~~~~~~~~

.. code-block:: python

    rule = limiter.get_rule("api_limit")
    print(f"Strategy: {rule.strategy}")
    print(f"Scope: {rule.scope}")

Whitelist and Blacklist
------------------------

Whitelist Management
~~~~~~~~~~~~~~~~~~~~

Whitelisted identifiers bypass all rate limits:

.. code-block:: python

    # Add to whitelist
    limiter.add_to_whitelist("10.0.0.1")
    limiter.add_to_whitelist("trusted_user_123")

    # Check whitelist
    if limiter.is_whitelisted("10.0.0.1"):
        print("IP is whitelisted")

    # Remove from whitelist
    limiter.remove_from_whitelist("10.0.0.1")

Blacklist Management
~~~~~~~~~~~~~~~~~~~~

Blacklisted identifiers are always blocked:

.. code-block:: python

    # Add to blacklist
    limiter.add_to_blacklist("192.168.1.100")
    limiter.add_to_blacklist("bad_user_456")

    # Check blacklist
    if limiter.is_blacklisted("192.168.1.100"):
        print("IP is blacklisted")

    # Remove from blacklist
    limiter.remove_from_blacklist("192.168.1.100")

Violation Callbacks
-------------------

Register callbacks to be notified of violations:

.. code-block:: python

    def log_violation(violation):
        """Log rate limit violations"""
        print(f"Violation by {violation.identifier}")
        print(f"Rule: {violation.rule_name}")
        print(f"Time: {violation.timestamp}")
        print(f"Requests: {violation.requests_made}/{violation.limit}")

    def alert_admin(violation):
        """Send alert to administrators"""
        if violation.requests_made > violation.limit * 2:
            send_email_alert(violation)

    # Register callbacks
    limiter.register_violation_callback(log_violation)
    limiter.register_violation_callback(alert_admin)

Metrics and Monitoring
----------------------

Get Metrics
~~~~~~~~~~~

.. code-block:: python

    metrics = limiter.get_metrics()

    print(f"Total requests: {metrics['total_requests']}")
    print(f"Allowed requests: {metrics['allowed_requests']}")
    print(f"Blocked requests: {metrics['blocked_requests']}")
    print(f"Block rate: {metrics['block_rate']:.2f}%")
    print(f"Total violations: {metrics['total_violations']}")
    print(f"Active rules: {metrics['active_rules']}")
    print(f"Whitelisted count: {metrics['whitelisted_count']}")
    print(f"Blacklisted count: {metrics['blacklisted_count']}")

    # Recent violations
    for violation in metrics['recent_violations']:
        print(f"  {violation.identifier} - {violation.rule_name}")

Reset Metrics
~~~~~~~~~~~~~

.. code-block:: python

    limiter.reset_metrics()

System Status
~~~~~~~~~~~~~

.. code-block:: python

    status = limiter.get_status()

    print(f"Rules: {status['rules']}")
    print(f"Storage type: {status['storage_type']}")
    print(f"Available strategies: {status['strategies_available']}")

Error Handling
--------------

RateThrottle provides specific exceptions for different error conditions:

.. code-block:: python

    from ratethrottle.exceptions import (
        RateLimitExceeded,
        RuleNotFoundError,
        ConfigurationError,
        StorageError
    )

    try:
        status = limiter.check_rate_limit("user123", "api_limit")
    except RuleNotFoundError as e:
        print(f"Rule not found: {e}")
    except StorageError as e:
        print(f"Storage error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

Handling RateLimitExceeded
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    try:
        status = limiter.check_rate_limit("user123", "api_limit")
        if not status.allowed:
            raise RateLimitExceeded(
                message="Rate limit exceeded",
                retry_after=status.retry_after,
                limit=status.limit,
                remaining=status.remaining,
                reset_time=status.reset_time
            )
    except RateLimitExceeded as e:
        # Return appropriate HTTP response
        return {
            'error': str(e),
            'retry_after': e.retry_after,
            'limit': e.limit,
            'remaining': e.remaining
        }, 429

Using with Context Managers
----------------------------

Clean up resources properly:

.. code-block:: python

    from ratethrottle import create_limiter, RateThrottleRule
    import redis

    # For Redis connections
    redis_client = redis.from_url('redis://localhost:6379/0')
    try:
        limiter = create_limiter('redis', 'redis://localhost:6379/0')
        
        rule = RateThrottleRule(name="api", limit=100, window=60)
        limiter.add_rule(rule)
        
        # Use limiter
        status = limiter.check_rate_limit("user123", "api")
        
    finally:
        redis_client.close()

Parsing Rate Limit Strings
---------------------------

Use the helper function to parse rate limit strings:

.. code-block:: python

    from ratethrottle.helpers import parse_rate_limit

    # Parse common formats
    limit, window = parse_rate_limit("100/minute")    # (100, 60)
    limit, window = parse_rate_limit("5/second")      # (5, 1)
    limit, window = parse_rate_limit("1000/hour")     # (1000, 3600)
    limit, window = parse_rate_limit("10000/day")     # (10000, 86400)

    # Use in rule creation
    limit, window = parse_rate_limit("50/minute")
    rule = RateThrottleRule(
        name="api_limit",
        limit=limit,
        window=window
    )

Best Practices
--------------

1. **Choose the Right Strategy**
   - Use ``token_bucket`` for APIs that need burst support
   - Use ``sliding_window`` for smooth, consistent rate limiting
   - Use ``fixed_window`` for simple, high-performance scenarios
   - Use ``leaky_bucket`` for constant-rate processing

2. **Set Appropriate Limits**
   - Start conservative and adjust based on metrics
   - Consider different limits for authenticated vs anonymous users
   - Use shorter windows for sensitive endpoints

3. **Monitor Metrics**
   - Regularly check block rates and violations
   - Adjust limits based on actual usage patterns
   - Set up alerts for unusual activity

4. **Use Redis for Production**
   - Use in-memory storage only for development/testing
   - Redis ensures rate limits work across multiple servers
   - Configure Redis with appropriate persistence settings

5. **Handle Errors Gracefully**
   - Always catch and handle rate limit exceptions
   - Provide clear error messages to users
   - Include ``Retry-After`` headers in responses

Next Steps
----------

* Learn about :doc:`user_guide/strategies` in detail
* Set up :doc:`user_guide/storage` backends
* Explore :doc:`advanced/analytics` capabilities
* Integrate with your framework: :doc:`frameworks/flask`, :doc:`frameworks/fastapi`, :doc:`frameworks/django`
