FastAPI Integration
===================

RateThrottle integrates with FastAPI using dependency injection.

Installation
------------

.. code-block:: bash

    pip install ratethrottle[fastapi]

Quick Start
-----------

.. code-block:: python

    from fastapi import FastAPI, Depends, Request
    from ratethrottle import FastAPIRateLimiter

    app = FastAPI()
    limiter = FastAPIRateLimiter()

    # Create rate limit dependency
    rate_limit = limiter.limit(100, 60)  # 100 requests per 60 seconds

    @app.get("/api/data")
    async def get_data(request: Request, _=Depends(rate_limit)):
        return {"data": "value"}

Basic Usage
-----------

Dependency Injection Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FastAPI uses dependency injection to manage rate limits.

.. code-block:: python

    from fastapi import FastAPI, Depends, Request
    from ratethrottle import FastAPIRateLimiter

    app = FastAPI()
    limiter = FastAPIRateLimiter()

    # Define rate limits
    public_limit = limiter.limit(100, 60)      # 100/minute
    search_limit = limiter.limit(50, 60)       # 50/minute
    expensive_limit = limiter.limit(10, 60)    # 10/minute

    @app.get("/api/public")
    async def public_endpoint(request: Request, _=Depends(public_limit)):
        return {"message": "Public data"}

    @app.get("/api/search")
    async def search(q: str, request: Request, _=Depends(search_limit)):
        return {"results": [], "query": q}

    @app.post("/api/expensive")
    async def expensive_operation(request: Request, _=Depends(expensive_limit)):
        return {"result": "done"}

Alternative: Using dependencies Parameter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import FastAPI, Depends, Request
    from ratethrottle import FastAPIRateLimiter

    app = FastAPI()
    limiter = FastAPIRateLimiter()

    rate_limit = limiter.limit(100, 60)

    @app.get("/api/data", dependencies=[Depends(rate_limit)])
    async def get_data(request: Request):
        return {"data": "value"}

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

By IP Address (Default)
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import Request, Depends
    from ratethrottle import FastAPIRateLimiter

    app = FastAPI()
    limiter = FastAPIRateLimiter()

    # Default behavior - limits by IP
    rate_limit = limiter.limit(100, 60)

    @app.get("/api/data")
    async def get_data(request: Request, _=Depends(rate_limit)):
        return {"data": "value"}

By User ID
~~~~~~~~~~

.. code-block:: python

    from fastapi import Request, Depends, Header
    from ratethrottle import FastAPIRateLimiter

    app = FastAPI()

    def get_user_id(request: Request, user_id: str = Header(None)):
        if user_id:
            return f"user:{user_id}"
        return f"ip:{request.client.host}"

    limiter = FastAPIRateLimiter(key_func=get_user_id)

    rate_limit = limiter.limit(1000, 60)

    @app.get("/api/data")
    async def get_data(request: Request, _=Depends(rate_limit)):
        return {"data": "value"}

By API Key
~~~~~~~~~~

.. code-block:: python

    from fastapi import Request, Depends, Header

    def get_api_key_identifier(request: Request, x_api_key: str = Header(None)):
        return x_api_key or request.client.host

    limiter = FastAPIRateLimiter(key_func=get_api_key_identifier)

    rate_limit = limiter.limit(5000, 60)

    @app.get("/api/data")
    async def get_data(request: Request, _=Depends(rate_limit)):
        return {"data": "value"}

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
    def get_identifier(request: Request, x_api_key: str = Header(None)):
        if x_api_key:
            return f"key:{x_api_key}"
        return f"ip:{request.client.host}"

    limiter = FastAPIRateLimiter(
        storage=rate_limiter.storage,
        key_func=get_identifier
    )

    # Define rate limits
    public_limit = limiter.limit(100, 60)        # 100/minute
    search_limit = limiter.limit(50, 60)         # 50/minute  
    write_limit = limiter.limit(10, 60)          # 10/minute
    upload_limit = limiter.limit(5, 300)         # 5 per 5 minutes

    # Exception handler (optional - FastAPI already handles HTTPException)
    @app.exception_handler(429)
    async def rate_limit_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too many requests",
                "detail": exc.detail
            },
            headers=exc.headers or {}
        )

    # Public endpoint - strict limit
    @app.get("/api/public")
    async def public_data(request: Request, _=Depends(public_limit)):
        return {"data": "public"}

    # Search endpoint
    @app.get("/api/search")
    async def search(q: str, request: Request, _=Depends(search_limit)):
        return {"results": [], "query": q}

    # Write operation - very strict
    @app.post("/api/process")
    async def process_data(
        data: dict,
        request: Request,
        _write=Depends(write_limit)
    ):
        # Process data
        return {"status": "processing"}

    # File upload - extremely strict
    @app.post("/api/upload")
    async def upload_file(request: Request, _=Depends(upload_limit)):
        # Handle upload
        return {"status": "uploaded"}

    # Health check - no rate limit
    @app.get("/health")
    async def health(request: Request):
        return {"status": "ok"}

    if __name__ == "__main__":
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)

Next Steps
----------

* Explore :doc:`django` integration
* Configure :doc:`../advanced/ddos_protection`
* Set up :doc:`../advanced/analytics`