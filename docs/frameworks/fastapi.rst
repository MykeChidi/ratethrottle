FastAPI Integration
===================

RateThrottle integrates seamlessly with FastAPI using dependency injection.

Installation
------------

.. code-block:: bash

    pip install ratethrottle[fastapi]

Quick Start
-----------

.. code-block:: python

    from fastapi import FastAPI
    from ratethrottle import FastAPIRateLimiter

    app = FastAPI()
    limiter = FastAPIRateLimiter()

    @app.get("/api/data")
    @limiter.limit("100/minute")
    async def get_data():
        return {"data": "value"}

Basic Usage
-----------

Decorator-based Limiting
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import FastAPI
    from ratethrottle import FastAPIRateLimiter

    app = FastAPI()
    limiter = FastAPIRateLimiter()

    @app.get("/api/public")
    @limiter.limit("100/minute")
    async def public_endpoint():
        return {"message": "Public data"}

    @app.get("/api/search")
    @limiter.limit("50/minute")
    async def search(q: str):
        return {"results": [], "query": q}

    @app.post("/api/expensive")
    @limiter.limit("10/minute")
    async def expensive_operation():
        return {"result": "done"}

Configuration
-------------

With Redis Storage
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import FastAPI
    from ratethrottle import FastAPIRateLimiter, create_limiter

    app = FastAPI()

    # Create limiter with Redis
    rate_limiter = create_limiter(
        storage='redis',
        redis_url='redis://localhost:6379/0'
    )

    limiter = FastAPIRateLimiter(storage=rate_limiter.storage)

Custom Key Functions
--------------------

By IP Address
~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import Request

    async def get_ip(request: Request):
        return request.client.host

    limiter = FastAPIRateLimiter(key_func=get_ip)

By User
~~~~~~~

.. code-block:: python

    from fastapi import Request, Depends
    from your_auth import get_current_user

    async def get_user_id(
        request: Request,
        user = Depends(get_current_user)
    ):
        if user:
            return f"user:{user.id}"
        return f"ip:{request.client.host}"

    limiter = FastAPIRateLimiter(key_func=get_user_id)

By API Key
~~~~~~~~~~

.. code-block:: python

    from fastapi import Header, Request

    async def get_api_key(
        request: Request,
        x_api_key: str = Header(None)
    ):
        return x_api_key or request.client.host

    limiter = FastAPIRateLimiter(key_func=get_api_key)

Error Handling
--------------

Custom Exception Handler
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from ratethrottle.exceptions import RateLimitExceeded

    app = FastAPI()

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "retry_after": exc.retry_after
            },
            headers={"Retry-After": str(exc.retry_after)}
        )

Response Headers
~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import Response

    @app.get("/api/data")
    @limiter.limit("100/minute")
    async def get_data(response: Response):
        # Headers automatically added:
        # X-RateLimit-Limit: 100
        # X-RateLimit-Remaining: 95
        # X-RateLimit-Reset: 1678901234
        return {"data": "value"}

Complete Example
----------------

.. code-block:: python

    from fastapi import FastAPI, Depends, HTTPException, Header, Request
    from fastapi.responses import JSONResponse
    from ratethrottle import FastAPIRateLimiter, create_limiter
    from ratethrottle.exceptions import RateLimitExceeded

    app = FastAPI(title="My API", version="1.0.0")

    # Create Redis-backed limiter
    rate_limiter = create_limiter(
        storage='redis',
        redis_url='redis://localhost:6379/0'
    )

    # Custom key function
    async def get_identifier(
        request: Request,
        x_api_key: str = Header(None)
    ):
        if x_api_key:
            return f"key:{x_api_key}"
        return f"ip:{request.client.host}"

    limiter = FastAPIRateLimiter(
        storage=rate_limiter.storage,
        key_func=get_identifier
    )

    # Exception handler
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too many requests",
                "retry_after": exc.retry_after
            },
            headers={"Retry-After": str(exc.retry_after)}
        )

    # Public endpoint - strict limit
    @app.get("/api/public")
    @limiter.limit("100/minute")
    async def public_data():
        return {"data": "public"}

    # Search endpoint
    @app.get("/api/search")
    @limiter.limit("50/minute")
    async def search(q: str):
        return {"results": [], "query": q}

    # Expensive operation
    @app.post("/api/process")
    @limiter.limit("10/minute")
    @limiter.limit("50/hour")
    async def process_data(data: dict):
        # Process data
        return {"status": "processing"}

    # Health check - no rate limit
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    if __name__ == "__main__":
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)

Next Steps
----------

* Explore :doc:`django` integration
* Configure :doc:`../advanced/ddos_protection`
* Set up :doc:`../advanced/analytics`