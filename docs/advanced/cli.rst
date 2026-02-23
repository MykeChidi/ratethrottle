Command Line Interface
======================

RateThrottle includes a CLI for testing, monitoring, and management.

Installation
------------

The CLI is included with RateThrottle:

.. code-block:: bash

    pip install ratethrottle

Usage
-----

Basic Commands
~~~~~~~~~~~~~~

.. code-block:: bash

    # Show help
    ratethrottle --help

Testing Rate Limits
~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Test a rate limit
    ratethrottle test --rule api_limit --requests 100

    # Test with specific identifier
    ratethrottle test --rule api_limit --identifier user123 --requests 50

Viewing Metrics
~~~~~~~~~~~~~~~

.. code-block:: bash

    # Show current metrics
    ratethrottle metrics

    # Show metrics for specific rule
    ratethrottle metrics --rule api_limit

Managing Whitelist/Blacklist
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Add to whitelist
    ratethrottle --whitelist-add 10.0.0.1

    # Remove from whitelist
    ratethrottle --whitelist-remove 10.0.0.1

    # List whitelist
    ratethrottle --list-all

    # Add to blacklist
    ratethrottle --blacklist-add 192.168.1.100

Statistics
~~~~~~~~~~

.. code-block:: bash

    # Export analytics report
    ratethrottle stats --export report.json

    # Include raw data in report
    ratethrottle stats --raw-data

Configuration
~~~~~~~~~~~~~

.. code-block:: bash

    # Validate configuration file
    ratethrottle config --validate config.yaml

    # Show current configuration
    ratethrottle config --show

Next Steps
----------

* Configure :doc:`../user_guide/configuration`
* Set up :doc:`distributed` systems