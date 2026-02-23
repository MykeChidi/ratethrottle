Installation
============

RateThrottle requires Python 3.10 or higher.

Basic Installation
------------------

Install RateThrottle using pip:

.. code-block:: bash

    pip install ratethrottle

This installs the core package with in-memory storage support.

Installation with Optional Dependencies
----------------------------------------

RateThrottle offers optional dependencies for specific features:

Redis Storage
~~~~~~~~~~~~~

For distributed rate limiting with Redis:

.. code-block:: bash

    pip install ratethrottle[redis]

Flask Integration
~~~~~~~~~~~~~~~~~

For Flask framework support:

.. code-block:: bash

    pip install ratethrottle[flask]

FastAPI Integration
~~~~~~~~~~~~~~~~~~~

For FastAPI and Starlette support:

.. code-block:: bash

    pip install ratethrottle[fastapi]

Django Integration
~~~~~~~~~~~~~~~~~~

For Django framework support:

.. code-block:: bash

    pip install ratethrottle[django]

All Frameworks
~~~~~~~~~~~~~~

To install support for all frameworks and Redis:

.. code-block:: bash

    pip install ratethrottle[frameworks]

Development Installation
------------------------

For development with testing and documentation tools:

.. code-block:: bash

    pip install ratethrottle[dev]

This includes:

* pytest and testing utilities
* black, flake8, mypy for code quality
* pre-commit hooks
* Type stubs for dependencies

Installing from Source
----------------------

To install the latest development version from GitHub:

.. code-block:: bash

    git clone https://github.com/MykeChidi/ratethrottle.git
    cd ratethrottle
    pip install -e .

For development with all dependencies:

.. code-block:: bash

    pip install -e ".[dev,frameworks]"

Verifying Installation
----------------------

Verify your installation:

.. code-block:: python

    import ratethrottle
    print(ratethrottle.__version__)

System Requirements
-------------------

**Python Version**
    Python 3.10, 3.11, or 3.12

**Operating Systems**
    Linux, macOS, Windows

**Optional Dependencies**
    * Redis 5.0+ (for Redis storage backend)
    * Framework-specific versions as specified in optional dependencies

Next Steps
----------

* Read the :doc:`quickstart` guide to get started quickly
* Explore :doc:`basic_usage` for detailed examples
* Check :doc:`user_guide/configuration` for configuration options
