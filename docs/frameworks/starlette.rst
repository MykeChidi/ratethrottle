Starlette Integration
=====================

RateThrottle works with Starlette and any ASGI application.

Installation
------------

.. code-block:: bash

    pip install ratethrottle[fastapi]  # Includes Starlette support

Quick Start
-----------

.. code-block:: python

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from ratethrottle.middleware import StarletteRateLimitMiddleware

    app = Starlette()

    # Add middleware
    app.add_middleware(
        StarletteRateLimitMiddleware,
        rate_limit="100/minute"
    )

    @app.route('/')
    async def homepage(request):
        return JSONResponse({'message': 'Hello'})

Complete Example
----------------

.. code-block:: python

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from ratethrottle.middleware import StarletteRateLimitMiddleware
    from ratethrottle import create_limiter

    # Create rate limiter
    limiter = create_limiter(
        storage='redis',
        redis_url='redis://localhost:6379/0'
    )

    async def homepage(request):
        return JSONResponse({'message': 'Hello'})

    async def api_endpoint(request):
        return JSONResponse({'data': []})

    routes = [
        Route('/', homepage),
        Route('/api/data', api_endpoint),
    ]

    middleware = [
        Middleware(
            StarletteRateLimitMiddleware,
            limiter=limiter,
            rate_limit="100/minute"
        )
    ]

    app = Starlette(routes=routes, middleware=middleware)

Next Steps
----------

* Return to :doc:`flask` for Flask integration
* Configure :doc:`../advanced/analytics`