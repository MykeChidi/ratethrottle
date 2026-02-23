Rate Limiting Strategies
========================

RateThrottle implements four proven rate limiting algorithms, each suited for different use cases.

Overview
--------

Rate limiting strategies determine **how** requests are counted and when limits reset. The choice of strategy affects:

* How bursts are handled
* How smoothly limits are enforced
* Memory and computational overhead
* Behavior at window boundaries

Available Strategies
--------------------

.. list-table::
   :header-rows: 1
   :widths: 20 25 25 30

   * - Strategy
     - Best For
     - Allows Bursts
     - Complexity
   * - Token Bucket
     - APIs with variable load
     - Yes (configurable)
     - Medium
   * - Leaky Bucket
     - Constant-rate processing
     - No
     - Medium
   * - Fixed Window
     - Simple high-volume APIs
     - Yes (at boundaries)
     - Low
   * - Sliding Window
     - Smooth enforcement
     - Partially
     - High

Token Bucket Strategy
---------------------

How It Works
~~~~~~~~~~~~

Imagine a bucket that holds tokens. Tokens are added at a constant rate, and each request consumes one token. If no tokens are available, the request is blocked.

.. code-block:: python

    rule = RateThrottleRule(
        name="api_burst",
        limit=100,        # Refill rate: 100 tokens per window
        window=60,        # Window: 60 seconds (= ~1.67 tokens/sec)
        strategy="token_bucket",
        burst=150         # Bucket capacity: 150 tokens
    )

**Key Characteristics**:

* Tokens refill at rate: ``limit / window`` per second
* Maximum tokens: ``burst`` (defaults to ``limit``)
* Allows traffic bursts up to ``burst`` capacity
* Smooth long-term rate limiting

Example Behavior
~~~~~~~~~~~~~~~~

Given: ``limit=100``, ``window=60``, ``burst=150``

.. code-block:: text

    Time    | Tokens | Request | Result
    --------|--------|---------|--------
    0s      | 150    | 50      | ✓ (100 remaining)
    1s      | 101.67 | 50      | ✓ (51.67 remaining)
    2s      | 53.34  | 60      | ✗ Blocked (need 60, have 53.34)
    30s     | 103.34 | 100     | ✓ (3.34 remaining)
    60s     | 53.34  | 50      | ✓ (3.34 remaining)

Best For
~~~~~~~~

* APIs that allow occasional bursts
* Services with varying load patterns  
* User-facing APIs where responsiveness matters
* Scenarios where some burst is acceptable

Implementation
~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import RateThrottleCore, RateThrottleRule

    limiter = RateThrottleCore()

    # Standard configuration
    rule = RateThrottleRule(
        name="api_standard",
        limit=100,
        window=60,
        strategy="token_bucket",
        burst=120  # 20% burst capacity
    )
    limiter.add_rule(rule)

    # Strict configuration (no burst)
    strict_rule = RateThrottleRule(
        name="api_strict",
        limit=100,
        window=60,
        strategy="token_bucket",
        burst=100  # Same as limit = no burst
    )

Leaky Bucket Strategy
---------------------

How It Works
~~~~~~~~~~~~

Imagine a bucket with a hole at the bottom that leaks at a constant rate. Requests fill the bucket. If the bucket overflows, requests are rejected.

.. code-block:: python

    rule = RateThrottleRule(
        name="api_steady",
        limit=100,        # Leak rate: 100 requests per window
        window=60,        # Window: 60 seconds
        strategy="leaky_bucket"
    )

**Key Characteristics**:

* Processes requests at constant rate: ``limit / window`` per second
* Queue capacity: ``limit`` requests
* Enforces steady, predictable rate
* No bursts allowed

Example Behavior
~~~~~~~~~~~~~~~~

Given: ``limit=100``, ``window=60`` (leak rate = 1.67/sec)

.. code-block:: text

    Time    | Queue  | Request | Result
    --------|--------|---------|--------
    0s      | 0      | 10      | ✓ (queue: 10)
    1s      | 8.33   | 10      | ✓ (queue: 18.33)
    5s      | 10     | 95      | ✗ Blocked (overflow)
    10s     | 0      | 50      | ✓ (queue: 50)
    60s     | 0      | 10      | ✓ (queue: 10)

Best For
~~~~~~~~

* Background processing systems
* Message queues and workers
* Rate-sensitive third-party API calls
* Ensuring predictable backend load

Implementation
~~~~~~~~~~~~~~

.. code-block:: python

    # Constant-rate API calls
    api_rule = RateThrottleRule(
        name="external_api",
        limit=60,          # 60 requests
        window=60,         # per minute = 1 req/sec
        strategy="leaky_bucket"
    )

    # Database operations
    db_rule = RateThrottleRule(
        name="database",
        limit=1000,        # 1000 operations
        window=60,         # per minute
        strategy="leaky_bucket"
    )

Fixed Window Strategy
---------------------

How It Works
~~~~~~~~~~~~

Counts requests in fixed time windows. When a window ends, the counter resets to zero.

.. code-block:: python

    rule = RateThrottleRule(
        name="api_simple",
        limit=100,
        window=60,
        strategy="fixed_window"
    )

**Key Characteristics**:

* Simple counter per time window
* Resets at window boundaries
* Fast and memory-efficient
* Subject to boundary condition issues

Example Behavior
~~~~~~~~~~~~~~~~

Given: ``limit=100``, ``window=60``

.. code-block:: text

    Time      | Window      | Count | Request | Result
    ----------|-------------|-------|---------|--------
    00:00:00  | 00:00-00:59 | 0     | 60      | ✓ (60/100)
    00:00:30  | 00:00-00:59 | 60    | 40      | ✓ (100/100)
    00:00:45  | 00:00-00:59 | 100   | 10      | ✗ Blocked
    00:01:00  | 00:01-01:59 | 0     | 60      | ✓ (60/100) - Reset!
    00:01:01  | 00:01-01:59 | 60    | 60      | ✓ (120/100)

Boundary Condition Problem
~~~~~~~~~~~~~~~~~~~~~~~~~~~

A client can make up to ``2 * limit`` requests in ``window`` seconds:

.. code-block:: text

    Window 1: [00:00:00 - 00:00:59]
    - At 00:00:59: Make 100 requests ✓
    
    Window 2: [00:01:00 - 00:01:59]
    - At 00:01:00: Make 100 requests ✓
    
    Total: 200 requests in 2 seconds!

Best For
~~~~~~~~

* High-performance scenarios where speed is critical
* Internal APIs with trusted clients
* Cases where slight overage is acceptable
* Simple, straightforward rate limiting

Implementation
~~~~~~~~~~~~~~

.. code-block:: python

    # High-volume public API
    public_rule = RateThrottleRule(
        name="public_api",
        limit=10000,
        window=60,
        strategy="fixed_window"
    )

    # Per-user limit
    user_rule = RateThrottleRule(
        name="user_api",
        limit=1000,
        window=3600,  # 1 hour
        strategy="fixed_window",
        scope="user"
    )

Sliding Window Strategy
-----------------------

How It Works
~~~~~~~~~~~~

Uses a sliding time window that moves with each request. Provides smooth rate limiting without boundary issues.

.. code-block:: python

    rule = RateThrottleRule(
        name="api_smooth",
        limit=100,
        window=60,
        strategy="sliding_window"
    )

**Key Characteristics**:

* Tracks timestamps of individual requests
* Window slides with current time
* No boundary condition issues
* Higher memory usage

Example Behavior
~~~~~~~~~~~~~~~~

Given: ``limit=100``, ``window=60``

.. code-block:: text

    Current Time: 00:01:00
    Looking back 60 seconds: 00:00:00 - 00:01:00
    
    Requests in window:
    - 00:00:05: 20 requests
    - 00:00:30: 40 requests  
    - 00:00:55: 30 requests
    Total: 90 requests
    
    New request at 00:01:00: ✓ Allowed (90/100)
    
    Current Time: 00:01:30
    Looking back 60 seconds: 00:00:30 - 00:01:30
    
    Requests in window:
    - 00:00:30: 40 requests (still in window)
    - 00:00:55: 30 requests
    - 00:01:00: 1 request
    Total: 71 requests
    
    Note: Requests at 00:00:05 are now outside window

Best For
~~~~~~~~

* Premium APIs requiring fair enforcement
* Financial applications
* Rate limits with legal/SLA requirements
* Scenarios where accuracy is critical

Implementation
~~~~~~~~~~~~~~

.. code-block:: python

    # Precise rate limiting
    premium_rule = RateThrottleRule(
        name="premium_api",
        limit=5000,
        window=3600,
        strategy="sliding_window",
        scope="user"
    )

    # Payment endpoints
    payment_rule = RateThrottleRule(
        name="payment",
        limit=10,
        window=60,
        strategy="sliding_window"
    )

Strategy Comparison
-------------------

Performance
~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 25 25 25

   * - Strategy
     - Speed
     - Memory Usage
     - Accuracy
   * - Fixed Window
     - ★★★★★
     - ★★★★★
     - ★★★☆☆
   * - Token Bucket
     - ★★★★☆
     - ★★★★☆
     - ★★★★☆
   * - Leaky Bucket
     - ★★★★☆
     - ★★★★☆
     - ★★★★☆
   * - Sliding Window
     - ★★★☆☆
     - ★★★☆☆
     - ★★★★★

Burst Handling
~~~~~~~~~~~~~~

.. code-block:: python

    # Token Bucket: Full burst support
    limiter.check_rate_limit("client", "token_bucket_rule")
    # Can burst up to 'burst' parameter

    # Leaky Bucket: No bursts
    limiter.check_rate_limit("client", "leaky_bucket_rule")
    # Strictly enforces constant rate

    # Fixed Window: Bursts at boundaries
    limiter.check_rate_limit("client", "fixed_window_rule")
    # Can burst at window edges

    # Sliding Window: Limited bursts
    limiter.check_rate_limit("client", "sliding_window_rule")
    # Smooth enforcement prevents large bursts

Choosing a Strategy
--------------------

Decision Tree
~~~~~~~~~~~~~

.. code-block:: text

    Need burst support?
    ├─ Yes → Do you need precise control?
    │        ├─ Yes → Token Bucket
    │        └─ No  → Fixed Window (simpler)
    │
    └─ No  → Need perfect smoothness?
             ├─ Yes → Sliding Window
             └─ No  → Leaky Bucket

Use Case Matrix
~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Use Case
     - Recommended Strategy
   * - Public REST API
     - Token Bucket (allows bursts)
   * - Internal microservices
     - Fixed Window (fast, simple)
   * - Third-party API client
     - Leaky Bucket (respects their limits)
   * - Payment processing
     - Sliding Window (precise)
   * - Search/autocomplete
     - Token Bucket (responsive)
   * - File uploads
     - Leaky Bucket (constant rate)
   * - GraphQL API
     - Sliding Window (complex queries)
   * - WebSocket connections
     - Token Bucket (bursty traffic)

Combining Strategies
--------------------

You can use multiple strategies for different endpoints:

.. code-block:: python

    from ratethrottle import RateThrottleCore, RateThrottleRule

    limiter = RateThrottleCore()

    # Public endpoints: Allow bursts
    public_rule = RateThrottleRule(
        name="public",
        limit=100,
        window=60,
        strategy="token_bucket",
        burst=150
    )

    # Authenticated: Smooth limiting
    auth_rule = RateThrottleRule(
        name="authenticated",
        limit=1000,
        window=60,
        strategy="sliding_window"
    )

    # Expensive operations: Constant rate
    expensive_rule = RateThrottleRule(
        name="expensive",
        limit=10,
        window=60,
        strategy="leaky_bucket"
    )

    # Background jobs: Simple counting
    background_rule = RateThrottleRule(
        name="background",
        limit=10000,
        window=3600,
        strategy="fixed_window"
    )

    limiter.add_rule(public_rule)
    limiter.add_rule(auth_rule)
    limiter.add_rule(expensive_rule)
    limiter.add_rule(background_rule)

Advanced Configuration
----------------------

Token Bucket Fine-Tuning
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Generous burst for good UX
    rule = RateThrottleRule(
        name="user_facing",
        limit=100,
        window=60,
        strategy="token_bucket",
        burst=200  # 2x burst capacity
    )

    # Strict: minimal burst
    rule = RateThrottleRule(
        name="api_strict",
        limit=100,
        window=60,
        strategy="token_bucket",
        burst=105  # Only 5% burst
    )

    # No burst: same as limit
    rule = RateThrottleRule(
        name="no_burst",
        limit=100,
        window=60,
        strategy="token_bucket",
        burst=100
    )

Testing Strategies
------------------

You can test different strategies to find what works best:

.. code-block:: python

    import time
    from ratethrottle import RateThrottleCore, RateThrottleRule

    def test_strategy(strategy_name):
        limiter = RateThrottleCore()
        rule = RateThrottleRule(
            name="test",
            limit=10,
            window=60,
            strategy=strategy_name,
            burst=15 if strategy_name == "token_bucket" else None
        )
        limiter.add_rule(rule)
        
        # Make burst of requests
        allowed = 0
        for i in range(20):
            status = limiter.check_rate_limit("test_client", "test")
            if status.allowed:
                allowed += 1
        
        print(f"{strategy_name}: {allowed}/20 requests allowed in burst")
        
        # Wait and try again
        time.sleep(10)
        status = limiter.check_rate_limit("test_client", "test")
        print(f"  After 10s: {'Allowed' if status.allowed else 'Blocked'}")

    # Test all strategies
    for strategy in ["token_bucket", "leaky_bucket", "fixed_window", "sliding_window"]:
        test_strategy(strategy)

Next Steps
----------

* Configure :doc:`storage` backends for your strategy
* Learn about :doc:`configuration` options
* Explore :doc:`../advanced/analytics` to monitor strategy performance