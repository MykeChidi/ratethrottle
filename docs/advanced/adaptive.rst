ML Adaptive - Reference
=======================

Installation
------------

.. code-block:: bash

    pip install ratethrottle

Basic Usage
-----------

.. code-block:: python

    from ratethrottle import AdaptiveRateLimiter
    
    # Create limiter
    limiter = AdaptiveRateLimiter(base_limit=100)
    
    # Check limit
    result = limiter.check_adaptive('user_123')
    
    if result['allowed']:
        # Process request
        process_request()
    else:
        # Reject request
        return_error(429, result['retry_after'])

Configuration Quick Reference
-----------------------------

.. code-block:: python

    AdaptiveRateLimiter(
        base_limit=100,              # Starting rate limit
        window=60,                   # Time window (seconds)
        learning_rate=0.1,           # 0.01=slow, 0.1=balanced, 0.3=fast
        anomaly_threshold=3.0,       # 2.0=strict, 3.0=balanced, 4.0=lenient
        trust_enabled=True,          # Enable trust scoring
        min_multiplier=0.5,          # Min: 50% of base
        max_multiplier=3.0,          # Max: 300% of base
        storage=None,                # Storage backend
        on_anomaly=None,             # Callback for anomalies
        on_trust_change=None         # Callback for trust changes
    )

Result Fields
-------------

.. code-block:: python

    result = limiter.check_adaptive('user_123')
    
    result['allowed']          # bool: Request allowed?
    result['adjusted_limit']   # int: Personalized limit
    result['remaining']        # int: Requests remaining
    result['trust_score']      # float: 0.0 to 1.0
    result['anomaly_score']    # float: Z-score (0=normal, 3+=anomalous)
    result['confidence']       # float: 0.0 to 1.0
    result['reason']           # str: 'allowed', 'rate_limit_exceeded', 'anomaly_detected'
    result['retry_after']      # int: Seconds to wait (if blocked)

Common Patterns
---------------

Pattern 1: Simple Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from flask import Flask, request, abort
    from ratethrottle import AdaptiveRateLimiter
    
    app = Flask(__name__)
    limiter = AdaptiveRateLimiter(base_limit=100)
    
    @app.route('/api/data')
    def get_data():
        result = limiter.check_adaptive(request.remote_addr)
        if not result['allowed']:
            abort(429)
        return {'data': 'protected'}

Pattern 2: User-Based Limiting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    @app.route('/api/resource')
    @login_required
    def get_resource():
        user_id = f"user_{current_user.id}"
        result = limiter.check_adaptive(user_id)
        
        if not result['allowed']:
            return {
                'error': 'Rate limit exceeded',
                'limit': result['adjusted_limit'],
                'trust': result['trust_score']
            }, 429
        
        return process_request()

Pattern 3: With Callbacks
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def on_anomaly(info):
        if info['anomaly_score'] > 5.0:
            alert_ops_team(info)
    
    limiter = AdaptiveRateLimiter(
        base_limit=100,
        on_anomaly=on_anomaly
    )

Pattern 4: Tiered Limits
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def get_limiter(user):
        if user.tier == 'enterprise':
            return AdaptiveRateLimiter(base_limit=1000)
        elif user.tier == 'pro':
            return AdaptiveRateLimiter(base_limit=500)
        else:
            return AdaptiveRateLimiter(base_limit=100)

Pattern 5: Model Persistence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import atexit
    
    limiter = AdaptiveRateLimiter(base_limit=100)
    
    # Load on startup
    try:
        limiter.load_model('model.pkl')
    except FileNotFoundError:
        pass
    
    # Save on shutdown
    atexit.register(lambda: limiter.export_model('model.pkl'))

Example Applications
--------------------

Example 1: Public API
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from flask import Flask, request, jsonify
    from ratethrottle import AdaptiveRateLimiter
    
    app = Flask(__name__)
    
    # Conservative limits for public API
    limiter = AdaptiveRateLimiter(
        base_limit=60,
        learning_rate=0.05,
        anomaly_threshold=2.5
    )
    
    @app.route('/api/v1/data')
    def public_api():
        ip = request.remote_addr
        result = limiter.check_adaptive(ip)
        
        if not result['allowed']:
            return jsonify({
                'error': 'Rate limit exceeded',
                'retry_after': result['retry_after']
            }), 429
        
        return jsonify({'data': 'public data'})
    
    if __name__ == '__main__':
        app.run()

Example 2: SaaS Application
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import FastAPI, Depends, HTTPException
    from ratethrottle import AdaptiveRateLimiter
    
    app = FastAPI()
    
    # Limiters per tier
    limiters = {
        'free': AdaptiveRateLimiter(base_limit=100),
        'pro': AdaptiveRateLimiter(base_limit=500),
        'enterprise': AdaptiveRateLimiter(base_limit=2000)
    }
    
    async def check_limit(user: User = Depends(get_current_user)):
        """Check adaptive rate limit"""
        limiter = limiters.get(user.tier, limiters['free'])
        result = limiter.check_adaptive(f'user_{user.id}')
        
        if not result['allowed']:
            raise HTTPException(
                status_code=429,
                detail={
                    'error': 'Rate limit exceeded',
                    'limit': result['adjusted_limit'],
                    'trust': result['trust_score']
                }
            )
    
    @app.get('/api/resource')
    async def get_resource(_=Depends(check_limit)):
        return {'resource': 'data'}

Example 3: E-commerce Checkout
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from django.http import JsonResponse
    from django.views.decorators.http import require_POST
    from ratethrottle import AdaptiveRateLimiter
    
    # Strict limiter for checkouts
    checkout_limiter = AdaptiveRateLimiter(
        base_limit=10,  # Only 10 checkouts per hour
        learning_rate=0.1,
        anomaly_threshold=2.0
    )
    
    @require_POST
    def checkout(request):
        """Process checkout with adaptive rate limiting"""
        session_id = request.session.session_key
        
        result = checkout_limiter.check_adaptive(session_id)
        
        if not result['allowed']:
            # Log potential fraud
            logger.warning(f"Checkout blocked: {session_id}")
            
            return JsonResponse({
                'error': 'Too many checkout attempts',
                'retry_after': result['retry_after']
            }, status=429)
        
        # Process checkout
        order = process_checkout(request)
        return JsonResponse({'order_id': order.id})

Example 4: API Gateway
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from flask import Flask, request, jsonify
    from ratethrottle import AdaptiveRateLimiter
    import requests
    
    app = Flask(__name__)
    
    # Fast-adapting limiter for internal services
    limiter = AdaptiveRateLimiter(
        base_limit=500,
        learning_rate=0.2,
        anomaly_threshold=4.0
    )
    
    @app.route('/gateway/<path:service_path>')
    def gateway(service_path):
        """API Gateway with adaptive rate limiting"""
        caller = request.headers.get('X-Service-Name', 'unknown')
        
        result = limiter.check_adaptive(f'service_{caller}')
        
        if not result['allowed']:
            # Alert ops team on internal rate limiting
            alert_ops(f"Service {caller} hitting rate limits")
            
            return jsonify({
                'error': 'Gateway rate limit exceeded',
                'service': caller,
                'retry_after': result['retry_after']
            }), 429
        
        # Proxy to service
        response = requests.get(f'http://internal/{service_path}')
        return response.json()

Example 5: WebSocket with Adaptive Limiting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import FastAPI, WebSocket
    from ratethrottle import AdaptiveRateLimiter
    
    app = FastAPI()
    
    # Adaptive limiter for WebSocket messages
    ws_limiter = AdaptiveRateLimiter(
        base_limit=100,  # 100 messages per minute
        learning_rate=0.1
    )
    
    @app.websocket("/ws/{client_id}")
    async def websocket_endpoint(websocket: WebSocket, client_id: str):
        await websocket.accept()
        
        try:
            while True:
                data = await websocket.receive_text()
                
                # Check adaptive rate limit per message
                result = ws_limiter.check_adaptive(client_id)
                
                if not result['allowed']:
                    await websocket.send_json({
                        'error': 'Rate limit exceeded',
                        'trust': result['trust_score'],
                        'retry_after': result['retry_after']
                    })
                    continue
                
                # Process message
                response = process_message(data)
                await websocket.send_text(response)
        
        except:
            await websocket.close()

Tips & Tricks
-------------

Tip 1: Start Conservative, Then Loosen
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Week 1: Strict
    limiter = AdaptiveRateLimiter(
        base_limit=60,
        anomaly_threshold=2.5
    )
    
    # Week 2: Monitor anomalies, adjust if needed
    # Week 3+: Increase if false positives high

Tip 2: Different Limiters for Different Endpoints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Read endpoints: Generous
    read_limiter = AdaptiveRateLimiter(base_limit=500)
    
    # Write endpoints: Moderate
    write_limiter = AdaptiveRateLimiter(base_limit=100)
    
    # Critical endpoints: Strict
    critical_limiter = AdaptiveRateLimiter(base_limit=10)

Tip 3: Combine with Traditional Limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Use adaptive as primary defense
    adaptive = AdaptiveRateLimiter(base_limit=100)
    
    # Use strict limits as safety net
    @app.route('/api/critical')
    @strict_limit("5/hour")  # Traditional limit
    def critical_endpoint():
        # Also check adaptive
        result = adaptive.check_adaptive(get_user_id())
        if not result['allowed']:
            abort(429)
        return process_critical_operation()

Tip 4: Manual Trust Adjustments
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Reward good behavior
    def reward_user(user_id):
        limiter.update_trust_score(user_id, +0.1)
    
    # Penalize bad behavior
    def penalize_user(user_id):
        limiter.update_trust_score(user_id, -0.2)
    
    # Use in your application logic
    @app.route('/report-spam', methods=['POST'])
    def report_spam():
        spammer_id = request.json['user_id']
        penalize_user(spammer_id)
        return {'status': 'reported'}

Cheat Sheet
-----------

.. list-table::
    :header-rows: 1
    :widths: 30 65

    * - Task 
      - Code
    * - Create limiter
      - ``limiter = AdaptiveRateLimiter(base_limit=100)``
    * - Check limit
      - ``result = limiter.check_adaptive('user_123')``
    * - Get profile
      - ``profile = limiter.get_user_profile('user_123')``
    * - Get stats
      - ``stats = limiter.get_statistics()``
    * - Save model
      - ``limiter.export_model('model.pkl')``
    * - Load model
      - ``limiter.load_model('model.pkl')``
    * - Adjust trust
      - ``limiter.update_trust_score('user_123', 0.1)``
    * - Reset User
      - ``limiter.reset_user('user_123')``

Summary
-------

* **Zero config:** Works great with defaults
* **Personalized limits** - Each user gets appropriate limit
* **Automatic:** Learns without manual tuning
* **Flexible:** Highly configurable when needed
* **Trust scoring** - Rewards good behavior
* **Automatic learning** - No manual tuning required
* **Anomaly detection** - Catches attacks automatically
* **Framework-agnostic:** Works with any Python web framework

**Get started in 5 minutes!** 🚀

Next Steps
----------

1. **Try it out:** Start with default configuration
2. **Monitor:** Watch anomaly detection and trust scores
3. **Tune:** Adjust learning_rate and thresholds
4. **Integrate:** Add callbacks for alerts
5. **Persist:** Save and load models
6. **Scale:** Use Redis for distributed systems
