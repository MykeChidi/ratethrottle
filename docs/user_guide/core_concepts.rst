Core Concepts
=============

Understanding the core concepts of RateThrottle will help you design effective rate limiting strategies for your applications.

Rate Limiting Basics
--------------------

What is Rate Limiting?
~~~~~~~~~~~~~~~~~~~~~~

Rate limiting controls the rate at which clients can access your API or service. It prevents:

* **API Abuse**: Prevents excessive usage by individual clients
* **DDoS Attacks**: Mitigates distributed denial of service attacks
* **Resource Exhaustion**: Protects backend services from overload
* **Cost Management**: Controls cloud/infrastructure costs
* **Fair Usage**: Ensures all users get fair access to resources

Key Components
--------------

Rules
~~~~~

A **rule** defines a rate limiting policy with these parameters:

* **name**: Unique identifier for the rule
* **limit**: Maximum number of requests allowed
* **window**: Time period in seconds
* **scope**: What to limit (ip, user, endpoint, global)
* **strategy**: Algorithm to use (token_bucket, sliding_window, etc.)
* **burst**: Maximum burst capacity (strategy-dependent)
* **block_duration**: How long to block violators

Example:

.. code-block:: python

    rule = RateThrottleRule(
        name="api_standard",
        limit=100,           # 100 requests
        window=60,           # per minute
        scope="ip",          # per IP address
        strategy="token_bucket",
        burst=120,          # allow bursts up to 120
        block_duration=300  # block for 5 minutes
    )

Storage Backends
~~~~~~~~~~~~~~~~

**Storage backends** persist rate limit state. RateThrottle supports:

1. **In-Memory Storage**
   - Fast and simple
   - Suitable for single-instance applications
   - Data lost on restart

2. **Redis Storage**
   - Distributed and persistent
   - Suitable for multi-instance applications
   - Survives application restarts
   - Supports clustering and high availability

Limiter Engine
~~~~~~~~~~~~~~

The **RateThrottleCore** engine:

* Manages rules and enforces limits
* Coordinates with storage backend
* Maintains whitelist/blacklist
* Tracks metrics and violations
* Executes violation callbacks

Scopes
------

Scopes determine what entity is being rate limited.

IP Scope
~~~~~~~~

Limits requests from the same IP address:

.. code-block:: python

    rule = RateThrottleRule(
        name="by_ip",
        limit=100,
        window=60,
        scope="ip"
    )

    # Different IPs are tracked separately
    status1 = limiter.check_rate_limit("192.168.1.1", "by_ip")
    status2 = limiter.check_rate_limit("192.168.1.2", "by_ip")

User Scope
~~~~~~~~~~

Limits requests from the same user (requires user identification):

.. code-block:: python

    rule = RateThrottleRule(
        name="by_user",
        limit=1000,
        window=3600,
        scope="user"
    )

    # Each user has their own limit
    status1 = limiter.check_rate_limit("user_123", "by_user")
    status2 = limiter.check_rate_limit("user_456", "by_user")

Endpoint Scope
~~~~~~~~~~~~~~

Limits requests to the same endpoint:

.. code-block:: python

    rule = RateThrottleRule(
        name="by_endpoint",
        limit=500,
        window=60,
        scope="endpoint"
    )

    # All clients share the endpoint limit
    status = limiter.check_rate_limit("/api/data", "by_endpoint")

Global Scope
~~~~~~~~~~~~

Limits all requests globally:

.. code-block:: python

    rule = RateThrottleRule(
        name="global",
        limit=10000,
        window=60,
        scope="global"
    )

    # Single limit for entire application
    status = limiter.check_rate_limit("global", "global")

Rate Limiting Status
--------------------

The ``RateThrottleStatus`` object provides complete information about a rate limit check:

Attributes
~~~~~~~~~~

.. code-block:: python

    status = limiter.check_rate_limit("client_id", "rule_name")

    # Boolean - whether request is allowed
    status.allowed         # True or False

    # Number of requests remaining in window
    status.remaining       # 95, 50, 0, etc.

    # Total limit for the rule
    status.limit           # 100

    # Unix timestamp when limit resets
    status.reset_time      # 1678901234

    # Seconds to wait before retry (if blocked)
    status.retry_after     # 45, 300, None

    # Name of applied rule
    status.rule_name       # "api_standard"

    # Whether client is currently blocked
    status.blocked         # True or False

Using Status Information
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    status = limiter.check_rate_limit("192.168.1.1", "api_limit")

    if status.allowed:
        # Process request
        response = process_request()
        
        # Add rate limit info to headers
        response.headers.update(status.to_headers())
        # X-RateLimit-Limit: 100
        # X-RateLimit-Remaining: 95
        # X-RateLimit-Reset: 1678901234
        
        return response
    else:
        # Return 429 Too Many Requests
        return {
            'error': 'Rate limit exceeded',
            'retry_after': status.retry_after,
            'limit': status.limit,
            'reset_time': status.reset_time
        }, 429

Violations
----------

A **violation** occurs when a client exceeds their rate limit.

Violation Object
~~~~~~~~~~~~~~~~

.. code-block:: python

    # Violations are automatically tracked
    violation = RateThrottleViolation(
        identifier="192.168.1.100",
        rule_name="api_limit",
        timestamp="2026-01-15T10:30:00",
        requests_made=105,
        limit=100,
        blocked_until="2026-01-15T10:35:00",
        retry_after=300,
        scope="ip",
        metadata={'endpoint': '/api/data', 'method': 'GET'}
    )

Violation Callbacks
~~~~~~~~~~~~~~~~~~~

Register callbacks to handle violations:

.. code-block:: python

    def log_violation(violation):
        logger.warning(
            f"Rate limit violation: {violation.identifier} "
            f"exceeded {violation.rule_name} "
            f"({violation.requests_made}/{violation.limit})"
        )

    def block_persistent_violators(violation):
        # Track violations per identifier
        violations_count = get_violation_count(violation.identifier)
        
        if violations_count > 5:
            # Add to blacklist after 5 violations
            limiter.add_to_blacklist(violation.identifier)
            alert_admin(f"Blacklisted {violation.identifier}")

    # Register callbacks
    limiter.register_violation_callback(log_violation)
    limiter.register_violation_callback(block_persistent_violators)

Whitelist and Blacklist
------------------------

Whitelist
~~~~~~~~~

**Whitelisted identifiers bypass all rate limits**:

.. code-block:: python

    # Add trusted IPs/users
    limiter.add_to_whitelist("10.0.0.1")
    limiter.add_to_whitelist("monitoring_service")
    limiter.add_to_whitelist("admin_user_123")

    # Check whitelist
    if limiter.is_whitelisted("10.0.0.1"):
        # No rate limits applied
        pass

Use cases:
* Internal services
* Monitoring tools
* Trusted partners
* Administrative accounts

Blacklist
~~~~~~~~~

**Blacklisted identifiers are always blocked**:

.. code-block:: python

    # Block malicious actors
    limiter.add_to_blacklist("192.168.1.100")
    limiter.add_to_blacklist("spammer_bot")
    limiter.add_to_blacklist("abusive_user")

    # Check blacklist
    if limiter.is_blacklisted("192.168.1.100"):
        # Always return 403 Forbidden
        pass

Use cases:
* Known attackers
* Banned users
* Spam bots
* Malicious IPs

Block Duration
--------------

When a client exceeds their limit, they can be temporarily blocked:

.. code-block:: python

    rule = RateThrottleRule(
        name="api_protected",
        limit=10,
        window=60,
        block_duration=300  # Block for 5 minutes (300 seconds)
    )

**Behavior**:

1. Client makes 11th request in window → violation triggered
2. Client is blocked for 300 seconds
3. During block period, all requests return ``allowed=False``
4. After 300 seconds, block expires and client can retry

**Setting block_duration=0** means no blocking after violation:

.. code-block:: python

    rule = RateThrottleRule(
        name="soft_limit",
        limit=100,
        window=60,
        block_duration=0  # No blocking, just deny excess requests
    )

Metrics and Monitoring
----------------------

Metrics provide insights into rate limiting effectiveness:

.. code-block:: python

    metrics = limiter.get_metrics()

    # Request statistics
    total_requests = metrics['total_requests']
    allowed_requests = metrics['allowed_requests']
    blocked_requests = metrics['blocked_requests']
    block_rate = metrics['block_rate']  # Percentage

    # Violation tracking
    total_violations = metrics['total_violations']
    recent_violations = metrics['recent_violations']  # Last 10

    # System state
    active_rules = metrics['active_rules']
    whitelisted_count = metrics['whitelisted_count']
    blacklisted_count = metrics['blacklisted_count']

Threading and Concurrency
-------------------------

RateThrottle is **thread-safe**:

* Uses ``threading.RLock`` for synchronization
* Safe for multi-threaded web servers (Gunicorn, uWSGI)
* Storage backends handle concurrent access properly
* Redis operations are atomic

.. code-block:: python

    import threading
    from ratethrottle import RateThrottleCore, RateThrottleRule

    limiter = RateThrottleCore()
    rule = RateThrottleRule(name="api", limit=100, window=60)
    limiter.add_rule(rule)

    def make_request(client_id):
        status = limiter.check_rate_limit(client_id, "api")
        if status.allowed:
            # Thread-safe
            process_request()

    # Multiple threads can safely use the same limiter
    threads = [
        threading.Thread(target=make_request, args=(f"client_{i}",))
        for i in range(100)
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()

Distributed Systems
-------------------

For applications running on multiple servers, use Redis storage:

.. code-block:: python

    from ratethrottle import create_limiter, RateThrottleRule

    # All servers connect to same Redis instance
    limiter = create_limiter(
        storage='redis',
        redis_url='redis://redis-host:6379/0'
    )

    # Rate limits are shared across all servers
    rule = RateThrottleRule(name="api", limit=1000, window=60)
    limiter.add_rule(rule)

**Benefits**:
* Consistent limits across all instances
* No per-instance multiplication of limits
* Centralized violation tracking
* Survives individual server restarts

Best Practices
--------------

1. **Choose Appropriate Limits**
   - Analyze your API's typical usage patterns
   - Set limits that prevent abuse but don't hinder legitimate use
   - Consider different limits for different user tiers

2. **Select the Right Scope**
   - Use ``ip`` for public APIs without authentication
   - Use ``user`` for authenticated endpoints
   - Use ``endpoint`` for expensive operations
   - Use ``global`` for overall system protection

3. **Configure Block Duration**
   - Longer blocks (1+ hour) for serious violations
   - Shorter blocks (5-15 min) for accidental overuse
   - Zero for informational limits

4. **Monitor and Adjust**
   - Track metrics regularly
   - Adjust limits based on block rates
   - Identify and whitelist legitimate high-volume users

5. **Handle Violations Appropriately**
   - Return proper HTTP status codes (429)
   - Include ``Retry-After`` headers
   - Provide clear error messages
   - Log violations for security analysis

Architecture Diagram
--------------------

.. code-block:: text

    ┌─────────────────────────────────────────────┐
    │          Client Request                      │
    └─────────────┬───────────────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────────────────────┐
    │    Whitelist/Blacklist Check                │
    │    (bypass or block immediately)            │
    └─────────────┬───────────────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────────────────────┐
    │    Get Rate Limit Rule                      │
    │    (by name)                                │
    └─────────────┬───────────────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────────────────────┐
    │    Apply Strategy                           │
    │    (token bucket, sliding window, etc.)     │
    └─────────────┬───────────────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────────────────────┐
    │    Check Storage Backend                    │
    │    (get current state)                      │
    └─────────────┬───────────────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────────────────────┐
    │    Calculate: Allowed or Blocked?           │
    └──────┬──────────────────────┬────────────────┘
           │                      │
     Allowed                  Blocked
           │                      │
           ▼                      ▼
    ┌──────────────┐    ┌──────────────────────┐
    │ Update State │    │ Record Violation     │
    │ Return Status│    │ Trigger Callbacks    │
    └──────────────┘    │ Set Block (if needed)│
                        │ Return Status        │
                        └──────────────────────┘

Next Steps
----------

* Learn about :doc:`strategies` in detail
* Configure :doc:`storage` backends
* Explore :doc:`configuration` options