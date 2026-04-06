Monitoring and Alerting
=======================

RateThrottle includes built-in monitoring and alerting support for production deployments.
The monitor collects runtime metrics from the rate limiter, DDoS protection, and analytics subsystems.
The alert dispatcher evaluates those metrics against configured thresholds and sends notifications through Slack, webhooks, email, or PagerDuty.

Overview
--------

* `RateThrottleMonitor` collects periodic snapshots and optionally exports JSON metrics to disk.
* `AlertDispatcher` evaluates snapshot values and suppresses repeat alerts with cooldown tracking.

Monitoring Quick Start
----------------------

.. code-block:: python

    from ratethrottle.monitoring import RateThrottleMonitor

    monitor = RateThrottleMonitor(
        {
            'enabled': True,
            'interval': 60,
            'log_metrics': True,
            'export_json': True,
            'export_path': 'metrics/metrics.json',
        },
        limiter=limiter,
        ddos=ddos_protection,
        analytics=analytics,
    )

    monitor.start()

    # Collect a snapshot immediately
    snapshot = monitor.snapshot_now()
    print(snapshot)

Key Monitoring Options
----------------------

* ``enabled``: Enable or disable the monitor.
* ``interval``: Seconds between periodic metric snapshots.
* ``log_metrics``: Emit metrics to the configured logger.
* ``export_json``: Write snapshots to the specified ``export_path``.
* ``export_path``: File path where JSON snapshot files are written.

Alerting Quick Start
--------------------

.. code-block:: python

    from ratethrottle.alerting import AlertDispatcher

    dispatcher = AlertDispatcher(
        {
            'enabled': True,
            'cooldown_seconds': 300,
            'thresholds': {
                'block_rate_warning': 5.0,
                'block_rate_critical': 20.0,
                'violations_per_minute_warning': 50.0,
                'violations_per_minute_critical': 200.0,
                'ddos_score_warning': 0.5,
                'ddos_score_critical': 0.8,
            },
            'slack': {
                'enabled': True,
                'channel': '#alerts',
                'username': 'RateThrottle',
            },
            'webhook': {
                'enabled': True,
                'url': 'https://example.com/alert',
                'timeout': 10,
            },
        }
    )

    dispatcher.send(
        'warning',
        'block_rate_exceeded',
        value=12.5,
        threshold=10.0,
        details={'rule': 'api_limit'},
    )

How Alerting Works
------------------

1. ``AlertDispatcher.check_and_alert(snapshot)`` is called with the latest monitoring snapshot.
2. The dispatcher evaluates:
   * ``block_rate`` against warning and critical thresholds.
   * ``violations_per_minute`` based on analytics delta.
   * ``ddos_score`` from DDoS detection statistics.
3. If a threshold is exceeded, an alert event is raised and routed to enabled channels.
4. Cooldown state prevents duplicate alerts for the same event/severity pair.

Configuration Reference
-----------------------

Monitoring config example:

.. code-block:: python

    {
        'enabled': True,
        'interval': 60,
        'log_metrics': True,
        'export_json': False,
        'export_path': 'metrics/metrics.json',
    }

Alerting config example:

.. code-block:: python

    {
        'enabled': True,
        'cooldown_seconds': 300,
        'thresholds': {
            'block_rate_warning': 5.0,
            'block_rate_critical': 20.0,
            'violations_per_minute_warning': 50.0,
            'violations_per_minute_critical': 200.0,
            'ddos_score_warning': 0.5,
            'ddos_score_critical': 0.8,
        },
        'slack': {
            'enabled': True,
            'channel': '#alerts',
            'username': 'RateThrottle',
            'webhook_url': '',
        },
        'webhook': {
            'enabled': False,
            'url': '',
            'headers': {},
            'timeout': 10,
        },
        'email': {
            'enabled': False,
            'smtp_host': 'localhost',
            'smtp_port': 587,
            'use_tls': True,
            'from_address': 'alerts@example.com',
            'to_addresses': ['ops@example.com'],
        },
        'pagerduty': {
            'enabled': False,
            'routing_key': '',
        },
    }

Integration Example
-------------------

.. code-block:: python

    snapshot = monitor.snapshot_now()
    dispatcher.check_and_alert(snapshot)

    # Use the latest metrics to power dashboards or alerting workflows
    if snapshot['limiter']['block_rate'] > 10.0:
        print('High block rate detected')

Best Practices
--------------

* Keep monitoring enabled in production to capture live metrics.
* Use ``export_json`` to persist snapshots for downstream tooling.
* Configure alert thresholds conservatively and adjust using real traffic data.
* Enable at least one notification channel so critical events are surfaced quickly.
* Use shared storage for ``AlertDispatcher`` in distributed deployments to ensure cooldown state is consistent.

Troubleshooting
---------------

* ``monitoring.interval must be positive`` indicates an invalid interval configuration.
* ``Webhook url not configured`` means the webhook channel is enabled but no URL is provided.
* ``PagerDuty routing_key not configured`` means PagerDuty is enabled without a valid API key.
