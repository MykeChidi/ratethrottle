Django Integration
==================

RateThrottle provides Django middleware and decorators for seamless integration.

Installation
------------

.. code-block:: bash

    pip install ratethrottle[django]

Quick Start
-----------

Add to ``MIDDLEWARE`` in ``settings.py``:

.. code-block:: python

    MIDDLEWARE = [
        # ... other middleware
        'ratethrottle.middleware.DjangoRateLimitMiddleware',
    ]

    # Configure rate limiting
    RATELIMIT_STORAGE = 'redis://localhost:6379/0'
    RATELIMIT_ENABLE = True

Usage
-----

Using the Decorator
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from django.http import JsonResponse
    from ratethrottle import django_ratelimit

    @django_ratelimit(limit=100, window=60)
    def my_view(request):
        return JsonResponse({'data': 'value'})

    @django_ratelimit(limit=50, window=60, scope='user')
    def protected_view(request):
        return JsonResponse({'data': 'protected'})

Configuration
-------------

Settings
~~~~~~~~

Add to your Django ``settings.py``:

.. code-block:: python

    # Rate limiting settings
    RATELIMIT_ENABLE = True
    RATELIMIT_STORAGE = 'redis://localhost:6379/0'
    RATELIMIT_DEFAULT_LIMIT = 100
    RATELIMIT_DEFAULT_WINDOW = 60
    RATELIMIT_STRATEGY = 'sliding_window'

Complete Example
----------------

.. code-block:: python

    # views.py
    from django.http import JsonResponse
    from ratethrottle import django_ratelimit

    @django_ratelimit(limit=100, window=60)
    def api_view(request):
        return JsonResponse({
            'message': 'API endpoint',
            'data': []
        })

    @django_ratelimit(limit=1000, window=3600, scope='user')
    def user_view(request):
        return JsonResponse({
            'user': request.user.username,
            'data': 'user-specific'
        })

Next Steps
----------

* See :doc:`starlette` for ASGI integration
* Configure :doc:`../advanced/ddos_protection`