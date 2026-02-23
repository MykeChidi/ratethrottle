Quick Start
===========

Get started with RateThrottle in minutes! This guide will walk you through the basics.

Simple Rate Limiting
--------------------

The easiest way to get started is using the helper function:

.. code-block:: python

    from ratethrottle import create_limiter, RateThrottleRule

    # Create a limiter with in-memory storage
    limiter = create_limiter()

    # Define a rate limit rule
    rule = RateThrottleRule(
        name="api_limit",
        limit=100,        # 100 requests
        window=60,        # per 60 seconds
        strategy="token_bucket"
    )

    # Add the rule
    limiter.add_rule(rule)

    # Check if request is allowed
    status = limiter.check_rate_limit("192.168.1.1", "api_limit")

    if status.allowed:
        print(f"Request allowed! {status.remaining} requests remaining")
    else:
        print(f"Rate limit exceeded! Retry after {status.retry_after} seconds")

Flask Integration
-----------------

Flask applications can use the decorator-based approach:

.. code-block:: python

    from flask import Flask
    from ratethrottle import FlaskRateLimiter

    app = Flask(__name__)
    limiter = FlaskRateLimiter(app)

    @app.route('/api/data')
    @limiter.limit("100/minute")
    def get_data():
        return {'data': 'value'}

    @app.route('/api/expensive')
    @limiter.limit("10/minute")
    def expensive_operation():
        # Expensive operation here
        return {'result': 'done'}

    if __name__ == '__main__':
        app.run()

FastAPI Integration
-------------------

FastAPI uses dependency injection for rate limiting:

.. code-block:: python

    from fastapi import FastAPI, Depends
    from ratethrottle import FastAPIRateLimiter

    app = FastAPI()
    limiter = FastAPIRateLimiter()

    @app.get("/api/data")
    @limiter.limit("100/minute")
    async def get_data():
        return {"data": "value"}

    @app.get("/api/expensive")
    @limiter.limit("10/minute")
    async def expensive_operation():
        return {"result": "done"}

Using Redis for Distributed Systems
------------------------------------

For applications running on multiple servers, use Redis:

.. code-block:: python

    from ratethrottle import create_limiter, RateThrottleRule

    # Create limiter with Redis backend
    limiter = create_limiter(
        storage='redis',
        redis_url='redis://localhost:6379/0'
    )

    # Add rules and use as normal
    rule = RateThrottleRule(
        name="api_limit",
        limit=1000,
        window=60
    )
    limiter.add_rule(rule)

    # Now all servers share the same rate limit state
    status = limiter.check_rate_limit("user123", "api_limit")

Using Different Strategies
---------------------------

RateThrottle supports multiple rate limiting algorithms:

.. code-block:: python

    from ratethrottle import RateThrottleCore, RateThrottleRule

    limiter = RateThrottleCore()

    # Token Bucket - allows bursts
    token_bucket_rule = RateThrottleRule(
        name="api_burst",
        limit=100,
        window=60,
        strategy="token_bucket",
        burst=150  # Allow up to 150 requests in burst
    )

    # Fixed Window - simple and fast
    fixed_window_rule = RateThrottleRule(
        name="api_fixed",
        limit=100,
        window=60,
        strategy="fixed_window"
    )

    # Sliding Window - smooth rate limiting
    sliding_window_rule = RateThrottleRule(
        name="api_sliding",
        limit=100,
        window=60,
        strategy="sliding_window"
    )

    # Leaky Bucket - constant rate
    leaky_bucket_rule = RateThrottleRule(
        name="api_leaky",
        limit=100,
        window=60,
        strategy="leaky_bucket"
    )

    # Add all rules
    for rule in [token_bucket_rule, fixed_window_rule, sliding_window_rule, leaky_bucket_rule]:
        limiter.add_rule(rule)

Whitelist and Blacklist
------------------------

Manage trusted and blocked clients:

.. code-block:: python

    from ratethrottle import RateThrottleCore

    limiter = RateThrottleCore()

    # Whitelist trusted IPs (unlimited access)
    limiter.add_to_whitelist("10.0.0.1")
    limiter.add_to_whitelist("10.0.0.2")

    # Blacklist malicious IPs (always blocked)
    limiter.add_to_blacklist("192.168.1.100")

    # Check lists
    print(f"Whitelisted: {limiter.is_whitelisted('10.0.0.1')}")  # True
    print(f"Blacklisted: {limiter.is_blacklisted('192.168.1.100')}")  # True

Monitoring and Metrics
-----------------------

Track rate limiting performance:

.. code-block:: python

    from ratethrottle import RateThrottleCore, RateThrottleRule

    limiter = RateThrottleCore()
    rule = RateThrottleRule(name="api", limit=100, window=60)
    limiter.add_rule(rule)

    # Simulate some requests
    for i in range(150):
        status = limiter.check_rate_limit(f"user_{i % 10}", "api")

    # Get metrics
    metrics = limiter.get_metrics()
    print(f"Total requests: {metrics['total_requests']}")
    print(f"Allowed: {metrics['allowed_requests']}")
    print(f"Blocked: {metrics['blocked_requests']}")
    print(f"Block rate: {metrics['block_rate']:.2f}%")
    print(f"Violations: {metrics['total_violations']}")

DDoS Protection
---------------

Enable automatic DDoS detection and mitigation:

.. code-block:: python

    from ratethrottle import DDoSProtection

    # Initialize DDoS protection
    ddos = DDoSProtection({
        'enabled': True,
        'threshold': 10000,      # requests per window
        'window': 60,            # seconds
        'auto_block': True,      # automatically block attackers
        'block_duration': 3600   # block for 1 hour
    })

    # Analyze traffic patterns
    pattern = ddos.analyze_traffic('192.168.1.100', '/api/data')
    
    if pattern.is_suspicious:
        print(f"Suspicious activity detected!")
        print(f"Score: {pattern.suspicious_score}")
        print(f"Request rate: {pattern.request_rate}/s")
        
        # Get list of blocked IPs
        blocked = ddos.get_blocked_ips()
        print(f"Currently blocked: {blocked}")

Command Line Interface
----------------------

RateThrottle includes a CLI for testing and management:

.. code-block:: bash

    # Test rate limits
    ratethrottle test --rule api_limit --requests 100

    # View metrics
    ratethrottle metrics

    # Manage whitelist/blacklist
    ratethrottle whitelist add 10.0.0.1
    ratethrottle blacklist add 192.168.1.100

    # Export analytics
    ratethrottle analytics export report.json

Configuration Files
-------------------

Use YAML configuration files for complex setups:

.. code-block:: yaml

    # config.yaml
    rules:
      - name: api_public
        limit: 100
        window: 60
        scope: ip
        strategy: token_bucket

      - name: api_authenticated
        limit: 1000
        window: 60
        scope: user
        strategy: sliding_window

    storage:
      type: redis
      url: redis://localhost:6379/0

    ddos:
      enabled: true
      threshold: 10000
      auto_block: true

Load configuration:

.. code-block:: python

    from ratethrottle import ConfigManager

    config = ConfigManager.load_from_file('config.yaml')
    limiter = config.create_limiter()

Next Steps
----------

Now that you've seen the basics, explore:

* :doc:`basic_usage` - Detailed usage patterns and examples
* :doc:`user_guide/strategies` - Learn about different rate limiting strategies
* :doc:`frameworks/flask` - Flask-specific integration guide
* :doc:`frameworks/fastapi` - FastAPI-specific integration guide
* :doc:`advanced/ddos_protection` - Advanced DDoS protection features
* :doc:`advanced/analytics` - Analytics and reporting capabilities
