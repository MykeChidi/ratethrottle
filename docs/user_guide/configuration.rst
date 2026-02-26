Configuration
=============

RateThrottle can be configured through code, YAML files, or environment variables.

Configuration Methods
---------------------

1. **Programmatic** - Define rules and settings in code
2. **YAML Files** - Load configuration from YAML
3. **Environment Variables** - Override settings via environment

Programmatic Configuration
---------------------------

Basic Setup
~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import RateThrottleCore, RateThrottleRule

    limiter = RateThrottleCore()

    # Add rules
    limiter.add_rule(RateThrottleRule(
        name="api_public",
        limit=100,
        window=60,
        strategy="token_bucket"
    ))

    limiter.add_rule(RateThrottleRule(
        name="api_auth",
        limit=1000,
        window=60,
        strategy="sliding_window",
        scope="user"
    ))

With Storage
~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import create_limiter

    limiter = create_limiter(
        storage='redis',
        redis_url='redis://localhost:6379/0',
        max_connections=50
    )

YAML Configuration
------------------

Configuration File Format
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

    # config.yaml
    storage:
      type: redis
      url: redis://localhost:6379/0
      options:
        max_connections: 50
        socket_timeout: 5
        retry_on_timeout: true

    rules:
      - name: api_public
        limit: 100
        window: 60
        scope: ip
        strategy: token_bucket
        burst: 120
        block_duration: 300

      - name: api_authenticated
        limit: 1000
        window: 60
        scope: user
        strategy: sliding_window
        block_duration: 600

      - name: api_expensive
        limit: 10
        window: 60
        scope: endpoint
        strategy: leaky_bucket
        block_duration: 900

    ddos:
      enabled: true
      threshold: 10000
      window: 60
      auto_block: true
      block_duration: 3600

Loading Configuration
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import ConfigManager, create_limiter

    # Load from file
    config = ConfigManager('config.yaml')
    
    # Create limiter 
    limiter = create_limiter()
    
    # Access config values
    rules = config.get_rules()
    ddos_config = config.get('ddos')

Environment Variables
---------------------

Override settings with environment variables:

.. code-block:: bash

    export RATETHROTTLE_STORAGE_TYPE=redis
    export RATETHROTTLE_REDIS_URL=redis://localhost:6379/0
    export RATETHROTTLE_DEFAULT_LIMIT=100
    export RATETHROTTLE_DEFAULT_WINDOW=60

Usage:

.. code-block:: python

    import os
    from ratethrottle import create_limiter

    limiter = create_limiter(
        storage=os.getenv('RATETHROTTLE_STORAGE_TYPE', 'memory'),
        redis_url=os.getenv('RATETHROTTLE_REDIS_URL')
    )

Configuration Options
---------------------

Rule Configuration
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    RateThrottleRule(
        name="rule_name",          # Required: Unique identifier
        limit=100,                 # Required: Max requests
        window=60,                 # Required: Time window (seconds)
        scope="ip",                # Optional: ip, user, endpoint, global
        strategy="token_bucket",   # Optional: Strategy algorithm
        burst=120,                 # Optional: Burst capacity
        block_duration=300         # Optional: Block time (seconds)
    )

Storage Configuration
~~~~~~~~~~~~~~~~~~~~~

In-Memory:

.. code-block:: python

    from ratethrottle import InMemoryStorage
    
    storage = InMemoryStorage()

Redis:

.. code-block:: python

    import redis
    from ratethrottle import RedisStorage
    
    client = redis.from_url(
        'redis://localhost:6379/0',
        max_connections=50,
        socket_timeout=5,
        retry_on_timeout=True
    )
    storage = RedisStorage(client)

DDoS Configuration
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import DDoSProtection

    ddos = DDoSProtection({
        'enabled': True,
        'threshold': 10000,              # requests per window
        'window': 60,                    # seconds
        'auto_block': True,
        'block_duration': 3600,          # 1 hour
        'suspicious_threshold': 0.5,     # 0.0 to 1.0
        'max_unique_endpoints': 50,
        'burst_threshold': 100,
        'burst_window': 10
    })

Analytics Configuration
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import RateThrottleAnalytics

    analytics = RateThrottleAnalytics(
        max_history=10000,
        enable_metadata=True,
        sanitize_data=True
    )

Best Practices
--------------

1. **Use YAML for Production**
   - Easier to update without code changes
   - Can be version controlled separately
   - Supports environment-specific configs

2. **Separate Configs by Environment**

.. code-block:: text

    config/
    ├── development.yaml
    ├── staging.yaml
    └── production.yaml

3. **Use Environment Variables for Secrets**

.. code-block:: yaml

    storage:
        type: redis
        url: ${REDIS_URL}  # From environment

4. **Document Your Rules**

.. code-block:: yaml

    rules:
        # Public API: Conservative limit for unauthenticated users
        - name: api_public
        limit: 100
        window: 60

5. **Version Your Config Files**
   - Track changes in git
   - Use descriptive commit messages
   - Review before deploying

Example Complete Configuration
-------------------------------

.. code-block:: yaml

    # production.yaml
    storage:
      type: redis
      url: redis://prod-redis:6379/0
      options:
        max_connections: 100
        socket_timeout: 5
        socket_connect_timeout: 5
        retry_on_timeout: true
        health_check_interval: 30

    rules:
      # Public endpoints
      - name: public_api
        limit: 100
        window: 60
        scope: ip
        strategy: token_bucket
        burst: 120
        block_duration: 300

      # Authenticated users
      - name: authenticated_api
        limit: 1000
        window: 60
        scope: user
        strategy: sliding_window
        block_duration: 600

      # Search endpoints
      - name: search
        limit: 50
        window: 60
        scope: ip
        strategy: token_bucket
        burst: 60
        block_duration: 300

      # Write operations
      - name: write_api
        limit: 20
        window: 60
        scope: user
        strategy: leaky_bucket
        block_duration: 900

      # File uploads
      - name: upload
        limit: 5
        window: 300
        scope: user
        strategy: fixed_window
        block_duration: 1800

    ddos:
      enabled: true
      threshold: 50000
      window: 60
      auto_block: true
      block_duration: 7200
      suspicious_threshold: 0.6
      max_unique_endpoints: 100
      burst_threshold: 500
      burst_window: 10


Loading This Configuration:

.. code-block:: python

    from ratethrottle import ConfigManager, create_limiter

    config = ConfigManager('production.yaml')
    limiter = create_limiter()

    rules = config.get_rules()
    
    for rule in rules:
        limiter.add_rule(rule)

Next Steps
----------

* Integrate with :doc:`../frameworks/flask`
* Set up :doc:`../advanced/ddos_protection`
* Configure :doc:`../advanced/analytics`
