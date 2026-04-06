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

RateThrottle supports configuration overrides through environment variables. These variables take precedence over YAML file settings and default values. Environment variables are particularly useful for:

* **Deployment-specific settings** (e.g., Redis connection details)
* **Secrets management** (e.g., API keys, passwords)
* **Containerized environments** (e.g., Docker, Kubernetes)
* **CI/CD pipelines**

Variable Naming Convention
~~~~~~~~~~~~~~~~~~~~~~~~~~

All environment variables use the ``RT_`` prefix to avoid conflicts with other applications.

Setting Environment Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Linux/macOS:**

.. code-block:: bash

    export RT_STORAGE_TYPE=redis
    export RT_REDIS_HOST=localhost
    export RT_REDIS_PORT=6379

**Windows (PowerShell):**

.. code-block:: powershell

    $env:RT_STORAGE_TYPE = "redis"
    $env:RT_REDIS_HOST = "localhost"
    $env:RT_REDIS_PORT = "6379"

**Windows (Command Prompt):**

.. code-block:: batch

    set RT_STORAGE_TYPE=redis
    set RT_REDIS_HOST=localhost
    set RT_REDIS_PORT=6379

**Docker:**

.. code-block:: yaml

    services:
      app:
        environment:
          - RT_STORAGE_TYPE=redis
          - RT_REDIS_HOST=redis
          - RT_REDIS_PORT=6379

**Kubernetes:**

.. code-block:: yaml

    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: ratethrottle-config
    data:
      RT_STORAGE_TYPE: "redis"
      RT_REDIS_HOST: "redis-service"
      RT_REDIS_PORT: "6379"

Supported Environment Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Storage Configuration
^^^^^^^^^^^^^^^^^^^^^

.. list-table:: Storage Environment Variables
   :header-rows: 1
   :widths: 25 15 60

   * - Variable
     - Type
     - Description
   * - ``RT_STORAGE_TYPE``
     - string
     - Storage backend type: ``memory`` or ``redis``
   * - ``RT_REDIS_HOST``
     - string
     - Redis server hostname (default: ``localhost``)
   * - ``RT_REDIS_PORT``
     - int
     - Redis server port (default: ``6379``)
   * - ``RT_REDIS_DB``
     - int
     - Redis database number (default: ``0``)
   * - ``RT_REDIS_PASSWORD``
     - string
     - Redis authentication password
   * - ``RT_REDIS_KEY_PREFIX``
     - string
     - Prefix for Redis keys (default: ``ratethrottle:``)

Global Configuration
^^^^^^^^^^^^^^^^^^^^

.. list-table:: Global Environment Variables
   :header-rows: 1
   :widths: 25 15 60

   * - Variable
     - Type
     - Description
   * - ``RT_ENABLED``
     - bool
     - Enable/disable rate throttling globally (default: ``true``)
   * - ``RT_LOG_LEVEL``
     - string
     - Logging level: ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``
   * - ``RT_HEADERS_ENABLED``
     - bool
     - Include rate limit headers in responses (default: ``true``)

DDoS Protection
^^^^^^^^^^^^^^^

.. list-table:: DDoS Protection Environment Variables
   :header-rows: 1
   :widths: 25 15 60

   * - Variable
     - Type
     - Description
   * - ``RT_DDOS_ENABLED``
     - bool
     - Enable DDoS protection (default: ``true``)
   * - ``RT_DDOS_THRESHOLD``
     - int
     - DDoS detection threshold (requests per window)
   * - ``RT_DDOS_BLOCK_DURATION``
     - int
     - DDoS block duration in seconds

Adaptive Rate Limiting
^^^^^^^^^^^^^^^^^^^^^^

.. list-table:: Adaptive Rate Limiting Environment Variables
   :header-rows: 1
   :widths: 25 15 60

   * - Variable
     - Type
     - Description
   * - ``RT_ADAPTIVE_ENABLED``
     - bool
     - Enable adaptive rate limiting (default: ``false``)

Monitoring
^^^^^^^^^^

.. list-table:: Monitoring Environment Variables
   :header-rows: 1
   :widths: 25 15 60

   * - Variable
     - Type
     - Description
   * - ``RT_MONITORING_ENABLED``
     - bool
     - Enable monitoring and metrics collection (default: ``true``)
   * - ``RT_MONITORING_INTERVAL``
     - int
     - Monitoring update interval in seconds (default: ``60``)

Alerting
^^^^^^^^

.. list-table:: Alerting Environment Variables
   :header-rows: 1
   :widths: 25 15 60

   * - Variable
     - Type
     - Description
   * - ``RT_ALERTING_ENABLED``
     - bool
     - Enable alerting system (default: ``false``)
   * - ``RT_SLACK_WEBHOOK_URL``
     - string
     - Slack webhook URL for notifications
   * - ``RT_WEBHOOK_URL``
     - string
     - Generic webhook URL for notifications
   * - ``RT_EMAIL_PASSWORD``
     - string
     - SMTP password for email alerts
   * - ``RT_PAGERDUTY_KEY``
     - string
     - PagerDuty routing key for incidents

Boolean Values
^^^^^^^^^^^^^^

Boolean environment variables accept the following values (case-insensitive):

* **True**: ``1``, ``true``, ``yes``, ``on``
* **False**: ``0``, ``false``, ``no``, ``off``

Examples
~~~~~~~~

**Basic Redis Configuration:**

.. code-block:: bash

    export RT_STORAGE_TYPE=redis
    export RT_REDIS_HOST=redis.example.com
    export RT_REDIS_PORT=6380
    export RT_REDIS_PASSWORD=secret123

**Production Settings:**

.. code-block:: bash

    export RT_LOG_LEVEL=WARNING
    export RT_DDOS_ENABLED=true
    export RT_DDOS_THRESHOLD=50000
    export RT_MONITORING_ENABLED=true
    export RT_ALERTING_ENABLED=true
    export RT_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

**Development Override:**

.. code-block:: bash

    export RT_ENABLED=false  # Disable throttling in development

**Docker Compose:**

.. code-block:: yaml

    version: '3.8'
    services:
      ratethrottle-app:
        environment:
          - RT_STORAGE_TYPE=redis
          - RT_REDIS_HOST=redis
          - RT_DDOS_ENABLED=true
          - RT_MONITORING_ENABLED=true

Priority Order
~~~~~~~~~~~~~~

Configuration values are applied in this order (later sources override earlier ones):

1. **Default values** (hardcoded in code)
2. **YAML file** (if specified)
3. **Environment variables** (highest priority)

This allows environment variables to override any setting from YAML files, which is useful for deployment-specific configurations.

Validation
~~~~~~~~~~

Environment variable values are validated when the configuration is loaded. Invalid values (e.g., non-numeric strings for integer variables) will log a warning and be ignored, falling back to the previous configuration source.

.. note::
   Environment variables are only read once during configuration initialization. Changes to environment variables require restarting the application to take effect.

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
        strategy: sliding_counter
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
