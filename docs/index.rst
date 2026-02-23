.. RateThrottle documentation master file

RateThrottle Documentation
==========================

**RateThrottle** is an advanced rate limiting and DDoS protection library for Python web applications. It provides enterprise-level features including multiple rate limiting strategies, DDoS protection, analytics, and seamless integration with popular web frameworks.

.. image:: https://img.shields.io/pypi/v/ratethrottle.svg
   :target: https://pypi.org/project/ratethrottle/
   :alt: PyPI version

.. image:: https://img.shields.io/github/license/MykeChidi/ratethrottle.svg
   :target: https://github.com/MykeChidi/ratethrottle/blob/main/LICENSE
   :alt: License

Key Features
------------

* **Multiple Rate Limiting Strategies**: Token bucket, leaky bucket, fixed window, and sliding window algorithms
* **DDoS Protection**: Advanced traffic analysis and automatic attack mitigation
* **Multi-Framework Support**: Flask, FastAPI, Django, Starlette, and WSGI applications
* **Flexible Storage**: In-memory and Redis backends for distributed systems
* **Analytics & Monitoring**: Comprehensive metrics, violation tracking, and reporting
* **Production Ready**: Thread-safe, type-annotated, and thoroughly tested
* **Easy Integration**: Simple decorators and middleware for quick setup

Quick Example
-------------

.. code-block:: python

    from ratethrottle import RateThrottleCore, RateThrottleRule

   # Create limiter
   limiter = RateThrottleCore()

   # Add rule
   rule = RateThrottleRule(
      name='api_limit',
      limit=100,
      window=60,
      strategy='sliding_window'
   )
   limiter.add_rule(rule)

   # Check rate limit
   status = limiter.check_rate_limit('192.168.1.100', 'api_limit')

   if status.allowed:
      # Process request
      print(f"Request allowed! {status.remaining} requests remaining")
   else:
      # Reject request
      print(f"Request blocked! Retry after {status.retry_after} seconds")

Why RateThrottle?
-----------------

**Comprehensive Protection**
    Protect your APIs from abuse, scraping, and DDoS attacks with advanced detection algorithms.

**Framework Agnostic**
    Works seamlessly with Flask, FastAPI, Django, Starlette, and any WSGI application.

**Production Ready**
    Built with enterprise requirements in mind - thread-safe, distributed-ready, and highly performant.

**Developer Friendly**
    Simple, intuitive API with extensive documentation and examples.

Getting Started
---------------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   quickstart
   basic_usage

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   user_guide/core_concepts
   user_guide/strategies
   user_guide/storage
   user_guide/configuration

.. toctree::
   :maxdepth: 2
   :caption: Framework Integration

   frameworks/flask
   frameworks/fastapi
   frameworks/django
   frameworks/starlette

.. toctree::
   :maxdepth: 2
   :caption: Advanced Features

   advanced/ddos_protection
   advanced/analytics
   advanced/cli
   advanced/distributed


Support & Community
-------------------

* **Documentation**: https://ratethrottle.readthedocs.io
* **Source Code**: https://github.com/MykeChidi/ratethrottle
* **Issue Tracker**: https://github.com/MykeChidi/ratethrottle/issues
* **PyPI**: https://pypi.org/project/ratethrottle/

License
-------

RateThrottle is released under the MIT License.

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`