Flask Integration
=================

RateThrottle provides seamless integration with Flask through decorators and middleware.

Installation
------------

.. code-block:: bash

    pip install ratethrottle[flask]

Quick Start
-----------

.. code-block:: python

    from flask import Flask
    from ratethrottle import FlaskRateLimiter

    app = Flask(__name__)
    limiter = FlaskRateLimiter(app)

    @app.route('/api/data')
    @limiter.limit("100/minute")
    def get_data():
        return {'data': 'value'}

    if __name__ == '__main__':
        app.run()

Basic Usage
-----------

Decorator-based Limiting
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from flask import Flask
    from ratethrottle import FlaskRateLimiter

    app = Flask(__name__)
    limiter = FlaskRateLimiter(app)

    @app.route('/api/public')
    @limiter.limit("100/minute")
    def public_endpoint():
        return {'message': 'Public data'}

    @app.route('/api/search')
    @limiter.limit("50/minute")
    def search():
        return {'results': []}

    @app.route('/api/expensive')
    @limiter.limit("10/minute")
    def expensive_operation():
        return {'result': 'done'}

Multiple Limits
~~~~~~~~~~~~~~~

Apply multiple rate limits to a single endpoint:

.. code-block:: python

    @app.route('/api/data')
    @limiter.limit("100/minute")  # Per-minute limit
    @limiter.limit("1000/hour")   # Per-hour limit
    def get_data():
        return {'data': 'value'}

Custom Key Functions
--------------------

Use custom functions to determine rate limit keys:

By IP Address
~~~~~~~~~~~~~

.. code-block:: python

    def get_ip():
        return request.remote_addr

    limiter = FlaskRateLimiter(app, key_func=get_ip)

By User
~~~~~~~

.. code-block:: python

    from flask_login import current_user

    def get_user_id():
        if current_user.is_authenticated:
            return f"user:{current_user.id}"
        return f"ip:{request.remote_addr}"

    limiter = FlaskRateLimiter(app, key_func=get_user_id)

By API Key
~~~~~~~~~~

.. code-block:: python

    def get_api_key():
        return request.headers.get('X-API-Key', request.remote_addr)

    limiter = FlaskRateLimiter(app, key_func=get_api_key)

Configuration
-------------

Flask Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    app.config['RATELIMIT_STORAGE_URL'] = 'redis://localhost:6379/0'
    app.config['RATELIMIT_STRATEGY'] = 'sliding_window'
    app.config['RATELIMIT_HEADERS_ENABLED'] = True

    limiter = FlaskRateLimiter(app)

With Redis Storage
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from flask import Flask
    from ratethrottle import FlaskRateLimiter, create_limiter

    app = Flask(__name__)

    # Create limiter with Redis
    rate_limiter = create_limiter(
        storage='redis',
        redis_url='redis://localhost:6379/0'
    )

    limiter = FlaskRateLimiter(app, storage=rate_limiter.storage)

Error Handling
--------------

Custom Error Handler
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from flask import jsonify
    from ratethrottle.exceptions import RateLimitExceeded

    @app.errorhandler(429)
    def rate_limit_handler(e):
        return jsonify({
            'error': 'Rate limit exceeded',
            'message': str(e),
            'retry_after': e.retry_after if hasattr(e, 'retry_after') else None
        }), 429

Response Headers
~~~~~~~~~~~~~~~~

Rate limit headers are automatically added:

.. code-block:: http

    HTTP/1.1 200 OK
    X-RateLimit-Limit: 100
    X-RateLimit-Remaining: 95
    X-RateLimit-Reset: 1678901234

Advanced Usage
--------------

Conditional Rate Limiting
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def should_rate_limit():
        # Don't rate limit admins
        if current_user.is_authenticated and current_user.is_admin:
            return False
        return True

    @app.route('/api/data')
    @limiter.limit("100/minute", condition=should_rate_limit)
    def get_data():
        return {'data': 'value'}

Exempting Routes
~~~~~~~~~~~~~~~~

.. code-block:: python

    @app.route('/api/health')
    @limiter.exempt
    def health_check():
        return {'status': 'ok'}

Per-User Limits
~~~~~~~~~~~~~~~

.. code-block:: python

    from flask_login import current_user

    @app.route('/api/user/data')
    @limiter.limit("1000/hour", key_func=lambda: current_user.id)
    def user_data():
        return {'data': 'user-specific'}

Complete Example
----------------

.. code-block:: python

    from flask import Flask, jsonify, request
    from flask_login import LoginManager, current_user
    from ratethrottle import FlaskRateLimiter, create_limiter

    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'your-secret-key'

    # Initialize rate limiter with Redis
    rate_limiter = create_limiter(
        storage='redis',
        redis_url='redis://localhost:6379/0'
    )

    def get_user_identifier():
        """Use user ID for authenticated users, IP for guests"""
        if current_user.is_authenticated:
            return f"user:{current_user.id}"
        return f"ip:{request.remote_addr}"

    limiter = FlaskRateLimiter(
        app,
        storage=rate_limiter.storage,
        key_func=get_user_identifier
    )

    # Public endpoints - strict limits
    @app.route('/api/public')
    @limiter.limit("100/minute")
    def public_data():
        return jsonify({'data': 'public'})

    # Authenticated endpoints - higher limits
    @app.route('/api/protected')
    @limiter.limit("1000/minute")
    def protected_data():
        return jsonify({'data': 'protected'})

    # Expensive operations - very strict
    @app.route('/api/report', methods=['POST'])
    @limiter.limit("10/minute")
    @limiter.limit("50/hour")
    def generate_report():
        # Generate report
        return jsonify({'status': 'processing'})

    # Custom error handler
    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({
            'error': 'Rate limit exceeded',
            'retry_after': getattr(e, 'retry_after', 60)
        }), 429

    if __name__ == '__main__':
        app.run(debug=True)

Testing
-------

Testing with Flask Test Client
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import unittest
    from your_app import app

    class TestRateLimiting(unittest.TestCase):
        def setUp(self):
            self.client = app.test_client()

        def test_rate_limit(self):
            # Make requests up to limit
            for i in range(100):
                response = self.client.get('/api/data')
                self.assertEqual(response.status_code, 200)

            # Next request should be rate limited
            response = self.client.get('/api/data')
            self.assertEqual(response.status_code, 429)

Best Practices
--------------

1. **Use Redis in Production**
   - In-memory storage doesn't work with multiple workers
   - Redis ensures consistent limits across all workers

2. **Set Appropriate Limits**
   - More restrictive for public endpoints
   - Higher limits for authenticated users
   - Very strict for expensive operations

3. **Add Custom Error Handlers**
   - Provide clear error messages
   - Include retry_after information
   - Log rate limit violations

4. **Use Custom Key Functions**
   - Identify users properly (user ID vs IP)
   - Consider API keys for third-party integrations
   - Handle proxies correctly

5. **Test Your Limits**
   - Write integration tests
   - Test boundary conditions
   - Verify error responses

Next Steps
----------

* Learn about :doc:`fastapi` integration
* Configure :doc:`../advanced/ddos_protection`
* Set up :doc:`../advanced/analytics`
