ML Adaptive Limiting
====================

Overview
--------

ML Adaptive Rate Limiting is a revolutionary feature that automatically learns user behavior and adjusts rate limits dynamically.

**Key Features:**
* Pattern learning with Exponential Moving Average
* Z-score based anomaly detection
* Trust scoring (0.0 to 1.0)
* Automatic limit adjustment (0.5x to 3x base)
* Model persistence
* Violation callbacks

Installation
------------

.. code-block:: bash

    # Basic installation (no extra dependencies needed!)
    pip install ratethrottle

**Note:** The ``AdaptiveRateLimiter`` class uses only statistical methods and has no heavy ML dependencies!

Quick Start
-----------

Basic Usage
~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import AdaptiveRateLimiter
    
    # Create adaptive limiter
    limiter = AdaptiveRateLimiter(
        base_limit=100,          # Starting rate limit
        learning_rate=0.1,       # How fast to adapt (0.0-1.0)
        anomaly_threshold=3.0    # Z-score threshold for anomalies
    )
    
    # Check rate limit (learns automatically!)
    result = limiter.check_adaptive('user_123')
    
    if result['allowed']:
        # Process request
        print(f"✅ Allowed")
        print(f"   Adjusted limit: {result['adjusted_limit']}")
        print(f"   Trust score: {result['trust_score']:.2f}")
        print(f"   Anomaly score: {result['anomaly_score']:.2f}")
    else:
        # Reject request
        print(f"❌ Blocked: {result['reason']}")
        print(f"   Retry after: {result['retry_after']}s")

How It Works
------------

1. Pattern Learning
~~~~~~~~~~~~~~~~~~~

**Learns normal behavior using Exponential Moving Average (EMA):**

.. code-block:: text

    mean_rate = (1 - learning_rate) × old_mean + learning_rate × current_rate

**Example:**

.. code-block:: python

    # User makes steady requests
    # Request 1: 100 req/min → mean = 100
    # Request 2: 105 req/min → mean = 100.5
    # Request 3: 98 req/min  → mean = 100.35
    # ...
    # Gradually learns the user's normal pattern

2. Anomaly Detection
~~~~~~~~~~~~~~~~~~~~

**Uses Z-score to detect unusual patterns:**

.. code-block:: text

    z_score = |current_rate - mean_rate| / std_rate

**Interpretation:**
 - Z-score < 2: Normal behavior
 - Z-score 2-3: Slightly unusual
 - Z-score > 3: Anomalous (default threshold)

**Example:**

.. code-block:: python

    # User normally does 100 req/min (std: 10)
    # Current: 250 req/min
    # Z-score = |250 - 100| / 10 = 15.0 (highly anomalous!)

3. Trust Scoring
~~~~~~~~~~~~~~~~

**Multi-factor trust score (0.0 to 1.0):**

.. code-block:: python

    trust = (
        age_score * 0.3 +           # Account age (ramps over 30 days)
        consistency_score * 0.4 +   # Low variance = consistent = trusted
        violation_score * 0.3 +     # Penalties for violations
        good_behavior_bonus         # Bonus for clean record
    )

**Trust Levels:**
 - 0.0-0.3: Untrusted (new or problematic)
 - 0.3-0.6: Neutral (average user)
 - 0.6-0.8: Trusted (good behavior)
 - 0.8-1.0: Highly trusted (excellent behavior)

4. Limit Adjustment
~~~~~~~~~~~~~~~~~~~

**Dynamic limit calculation:**

.. code-block:: python

    adjusted_limit = base_limit * trust_multiplier * anomaly_multiplier * age_multiplier

**Multipliers:**
 - Trust: 0.5x to 2.0x (based on trust score)
 - Anomaly: 0.3x if anomalous, 1.0x if normal
 - Age: 0.5x to 1.0x (ramps over 30 days)

**Example:**

.. code-block:: python

    # Base: 100 req/min
    # Trust: 0.9 (highly trusted) → 1.95x multiplier
    # Anomaly: Normal → 1.0x multiplier
    # Age: 45 days → 1.0x multiplier
    # Adjusted: 100 × 1.95 × 1.0 × 1.0 = 195 req/min

Configuration
-------------

Basic Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    limiter = AdaptiveRateLimiter(
        base_limit=100,              # Base rate limit
        window=60,                   # Time window (seconds)
        learning_rate=0.1,           # Adaptation speed (0.0-1.0)
        anomaly_threshold=3.0,       # Z-score threshold
        trust_enabled=True,          # Enable trust scoring
        min_multiplier=0.5,          # Minimum: 50% of base
        max_multiplier=3.0           # Maximum: 300% of base
    )

Advanced Configuration
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import RedisStorage
    
    limiter = AdaptiveRateLimiter(
        base_limit=100,
        learning_rate=0.1,
        
        # Storage backend
        storage=RedisStorage('redis://localhost:6379/0'),
        
        # Callbacks
        on_anomaly=lambda info: alert_ops_team(info),
        on_trust_change=lambda user, score: log_trust(user, score)
    )

Configuration Guidelines
~~~~~~~~~~~~~~~~~~~~~~~~

**Learning Rate:**
 - 0.01-0.05: Very slow (conservative, stable)
 - 0.1: Default (balanced)
 - 0.3-0.5: Fast (responsive, volatile)

**Anomaly Threshold:**
 - 2.0: Very strict (5% false positive rate)
 - 3.0: Default (0.3% false positive rate)
 - 4.0: Lenient (0.01% false positive rate)

**Multipliers:**
 - Conservative: min=0.7, max=1.5
 - Balanced: min=0.5, max=3.0 (default)
 - Aggressive: min=0.3, max=5.0

Use Cases
---------

1. Public API Protection
~~~~~~~~~~~~~~~~~~~~~~~~

**Scenario:** Protect public API from scrapers and abuse

.. code-block:: python

    limiter = AdaptiveRateLimiter(
        base_limit=60,           # 1 req/second baseline
        learning_rate=0.05,      # Slow learning (be cautious)
        anomaly_threshold=2.5    # Strict detection
    )
    
    @app.route('/api/data')
    def get_data():
        result = limiter.check_adaptive(get_client_ip(request))
        
        if not result['allowed']:
            return {'error': 'Rate limit exceeded'}, 429
        
        return {'data': 'protected'}

**Outcomes:**
 - New users: 30-40 req/min (cautious)
 - Good users: 90-120 req/min (generous)
 - Scrapers: Detected and limited to 5-10 req/min

2. SaaS Application
~~~~~~~~~~~~~~~~~~~

**Scenario:** Different user tiers with adaptive limits

.. code-block:: python

    def get_base_limit(user):
        """Get base limit by tier"""
        if user.tier == 'enterprise':
            return 1000
        elif user.tier == 'pro':
            return 500
        else:  # free
            return 100
    
    @app.route('/api/resource')
    @login_required
    def get_resource():
        user = get_current_user()
        
        limiter = AdaptiveRateLimiter(
            base_limit=get_base_limit(user)
        )
        
        result = limiter.check_adaptive(f'user_{user.id}')
        
        if result['allowed']:
            return process_request()
        else:
            return {
                'error': 'Rate limit exceeded',
                'limit': result['adjusted_limit'],
                'retry_after': result['retry_after']
            }, 429

**Outcomes:**
 - Each tier gets personalized limits
 - Good behavior rewarded with 1.5-2x higher limits
 - Abuse detected and throttled automatically

3. E-commerce Checkout
~~~~~~~~~~~~~~~~~~~~~~

**Scenario:** Prevent fraud while allowing legitimate purchases

.. code-block:: python

    checkout_limiter = AdaptiveRateLimiter(
        base_limit=10,           # Only 10 checkouts/hour
        learning_rate=0.1,
        anomaly_threshold=2.0    # Very strict
    )
    
    @app.route('/checkout', methods=['POST'])
    def checkout():
        session_id = request.session.get('id')
        
        result = checkout_limiter.check_adaptive(session_id)
        
        if not result['allowed']:
            logger.warning(f"Checkout blocked: {session_id}")
            return {'error': 'Too many checkout attempts'}, 429
        
        # Process checkout
        return process_checkout()

**Outcomes:**
 - Trusted customers get higher limits
 - Unusual patterns (many failed payments) detected
 - Fraud attempts automatically blocked

4. Internal API Gateway
~~~~~~~~~~~~~~~~~~~~~~~

**Scenario:** Protect backend services from internal abuse

.. code-block:: python

    gateway_limiter = AdaptiveRateLimiter(
        base_limit=500,
        learning_rate=0.2,       # Fast adaptation (internal trust)
        anomaly_threshold=4.0    # Lenient (avoid false positives)
    )
    
    @app.route('/internal/service/<service_name>')
    @require_internal_auth
    def internal_api(service_name):
        caller = request.headers.get('X-Service-Name')
        
        result = gateway_limiter.check_adaptive(f'service_{caller}')
        
        if result['allowed']:
            return proxy_to_service(service_name)
        else:
            # Alert on internal rate limiting
            alert_ops(f"Service {caller} hitting rate limits")
            return {'error': 'Rate limited'}, 429

**Outcomes:**
 - Microservices get personalized limits
 - Unusual patterns detected (e.g., infinite loops)
 - Self-healing under load

Monitoring & Insights
---------------------

Get User Profile
~~~~~~~~~~~~~~~~

.. code-block:: python

    profile = limiter.get_user_profile('user_123')
    
    print(f"Identifier: {profile['identifier']}")
    print(f"Age: {profile['age_days']:.1f} days")
    print(f"Total requests: {profile['request_count']}")
    print(f"Average rate: {profile['mean_rate']:.1f} req/min")
    print(f"Trust score: {profile['trust_score']:.2f}")
    print(f"Violations: {profile['violation_count']}")
    print(f"Current limit: {profile['current_limit']}")

Get Statistics
~~~~~~~~~~~~~~

.. code-block:: python

    stats = limiter.get_statistics()
    
    print(f"Total requests: {stats['total_requests']}")
    print(f"Anomalies detected: {stats['anomalies_detected']}")
    print(f"Limits adjusted: {stats['limits_adjusted']}")
    print(f"Users tracked: {stats['users_tracked']}")

Callbacks
~~~~~~~~~

**Anomaly Detection:**

.. code-block:: python

    def on_anomaly(info):
        """Called when anomaly detected"""
        logger.warning(
            f"Anomaly detected for {info['identifier']}: "
            f"score={info['anomaly_score']:.2f}, "
            f"rate={info['current_rate']:.0f} (expected: {info['expected_rate']:.0f})"
        )
        
        # Send alert if severe
        if info['anomaly_score'] > 5.0:
            send_alert(f"Severe anomaly: {info['identifier']}")
    
    limiter = AdaptiveRateLimiter(on_anomaly=on_anomaly)

**Trust Changes:**

.. code-block:: python

    def on_trust_change(identifier, new_trust):
        """Called when trust score changes significantly"""
        logger.info(f"Trust updated for {identifier}: {new_trust:.2f}")
        
        # Reward highly trusted users
        if new_trust > 0.9:
            send_reward_email(identifier)
    
    limiter = AdaptiveRateLimiter(on_trust_change=on_trust_change)

Model Persistence
-----------------

Save Model
~~~~~~~~~~

.. code-block:: python

    # After learning from production traffic
    limiter.export_model('adaptive_model.json')

Load Model
~~~~~~~~~~

.. code-block:: python

    # Start with learned behavior
    limiter = AdaptiveRateLimiter(base_limit=100)
    limiter.load_model('adaptive_model.json')
    
    # Model includes all user profiles and learned patterns

Use Case: Graceful Restarts
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import atexit
    
    limiter = AdaptiveRateLimiter(base_limit=100)
    
    # Load existing model on startup
    try:
        limiter.load_model('adaptive_model.json')
        logger.info("Loaded existing model")
    except FileNotFoundError:
        logger.info("Starting with fresh model")
    
    # Save on shutdown
    def save_model():
        limiter.export_model('adaptive_model.json')
        logger.info("Model saved")
    
    atexit.register(save_model)

Integration Examples
--------------------

Flask
~~~~~

.. code-block:: python

    from flask import Flask, request, jsonify
    from ratethrottle import AdaptiveRateLimiter
    
    app = Flask(__name__)
    limiter = AdaptiveRateLimiter(base_limit=100)
    
    @app.before_request
    def check_rate_limit():
        """Check rate limit before each request"""
        identifier = request.headers.get('X-User-ID') or request.remote_addr
        
        result = limiter.check_adaptive(identifier)
        
        if not result['allowed']:
            return jsonify({
                'error': 'Rate limit exceeded',
                'limit': result['adjusted_limit'],
                'retry_after': result['retry_after'],
                'trust_score': result['trust_score']
            }), 429

FastAPI
~~~~~~~

.. code-block:: python

    from fastapi import FastAPI, Request, HTTPException
    from ratethrottle import AdaptiveRateLimiter
    
    app = FastAPI()
    limiter = AdaptiveRateLimiter(base_limit=100)
    
    @app.middleware("http")
    async def adaptive_rate_limit(request: Request, call_next):
        """Apply adaptive rate limiting"""
        # Extract user identifier
        user_id = request.headers.get('X-User-ID', request.client.host)
        
        # Check limit
        result = limiter.check_adaptive(user_id)
        
        if not result['allowed']:
            raise HTTPException(
                status_code=429,
                detail={
                    'error': 'Rate limit exceeded',
                    'limit': result['adjusted_limit'],
                    'trust_score': result['trust_score']
                }
            )
        
        # Add rate limit headers
        response = await call_next(request)
        response.headers['X-RateLimit-Limit'] = str(result['adjusted_limit'])
        response.headers['X-RateLimit-Remaining'] = str(result['remaining'])
        
        return response

Django
~~~~~~

.. code-block:: python

    from django.core.cache import cache
    from django.http import JsonResponse
    from ratethrottle import AdaptiveRateLimiter
    
    # Global limiter
    limiter = AdaptiveRateLimiter(base_limit=100)
    
    def adaptive_rate_limit(view_func):
        """Decorator for adaptive rate limiting"""
        def wrapper(request, *args, **kwargs):
            # Get user identifier
            if request.user.is_authenticated:
                identifier = f'user_{request.user.id}'
            else:
                identifier = request.META.get('REMOTE_ADDR')
            
            # Check limit
            result = limiter.check_adaptive(identifier)
            
            if not result['allowed']:
                return JsonResponse({
                    'error': 'Rate limit exceeded',
                    'limit': result['adjusted_limit'],
                    'retry_after': result['retry_after']
                }, status=429)
            
            return view_func(request, *args, **kwargs)
        
        return wrapper
    
    # Use on views
    @adaptive_rate_limit
    def api_view(request):
        return JsonResponse({'data': 'protected'})

Best Practices
--------------

1. Start Conservative
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Start with strict limits
    limiter = AdaptiveRateLimiter(
        base_limit=60,           # Conservative
        learning_rate=0.05,      # Slow learning
        anomaly_threshold=2.5    # Strict detection
    )
    
    # Monitor for a week, then adjust

2. Use Appropriate Identifiers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # For authenticated APIs
    identifier = f'user_{user.id}'
    
    # For public APIs
    identifier = get_client_ip(request)
    
    # For internal services
    identifier = f'service_{service_name}'
    
    # For anonymous sessions
    identifier = request.session.get('id')

3. Monitor and Alert
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def on_anomaly(info):
        """Alert on severe anomalies"""
        if info['anomaly_score'] > 5.0:
            send_alert(
                f"Severe anomaly: {info['identifier']} "
                f"(score: {info['anomaly_score']:.1f})"
            )
    
    limiter = AdaptiveRateLimiter(on_anomaly=on_anomaly)

4. Combine with Traditional Limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Use adaptive for most endpoints
    adaptive = AdaptiveRateLimiter(base_limit=100)
    
    # Use strict limits for critical endpoints
    from ratethrottle import FlaskRateLimiter
    strict = FlaskRateLimiter(app)
    
    @app.route('/api/data')
    def get_data():
        # Adaptive limiting
        result = adaptive.check_adaptive(get_user_id())
        if not result['allowed']:
            abort(429)
        return {'data': 'value'}
    
    @app.route('/api/admin/delete')
    @strict.limit("5/hour")
    def delete_resource():
        # Strict limiting for critical operations
        return {'status': 'deleted'}

5. Persist Models
~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Save periodically
    def save_model_periodically():
        while True:
            time.sleep(3600)  # Every hour
            limiter.export_model('adaptive_model.json')
    
    threading.Thread(target=save_model_periodically, daemon=True).start()
    
    # Load on startup
    limiter.load_model('adaptive_model.json')

See :doc:`../advanced/adaptive` for more examples
