Analytics and Reporting
========================

RateThrottle provides comprehensive analytics and reporting capabilities.

Overview
--------

Track and analyze:

* Request patterns and trends
* Violations and blocked requests
* Top violators
* Rule performance
* Temporal patterns

Quick Start
-----------

.. code-block:: python

    from ratethrottle import RateThrottleAnalytics

    analytics = RateThrottleAnalytics(max_history=10000)

    # Record requests
    analytics.record_request('192.168.1.1', 'api_limit', allowed=True)
    analytics.record_request('192.168.1.100', 'api_limit', allowed=False)

    # Get insights
    top_violators = analytics.get_top_violators(10)
    timeline = analytics.get_violation_timeline(hours=24)

Configuration
-------------

.. code-block:: python

    analytics = RateThrottleAnalytics(
        max_history=10000,       # Max records to keep
        enable_metadata=True,    # Store request metadata
        sanitize_data=True       # Sanitize sensitive data
    )

Recording Data
--------------

Record Requests
~~~~~~~~~~~~~~~

.. code-block:: python

    analytics.record_request(
        identifier='192.168.1.1',
        rule_name='api_limit',
        allowed=True,
        metadata={'endpoint': '/api/data', 'method': 'GET'}
    )

Record Violations
~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import RateThrottleViolation

    violation = RateThrottleViolation(
        identifier='192.168.1.100',
        rule_name='api_limit',
        timestamp='2026-01-15T10:30:00',
        requests_made=105,
        limit=100,
        blocked_until='2026-01-15T10:35:00',
        retry_after=300,
        scope='ip',
        metadata={'endpoint': '/api/data'}
    )

    analytics.record_violation(violation)

Analyzing Data
--------------

Top Violators
~~~~~~~~~~~~~

.. code-block:: python

    violators = analytics.get_top_violators(limit=10)
    for violator in violators:
        print(f"{violator['identifier']}: {violator['count']} violations")

Violation Timeline
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    timeline = analytics.get_violation_timeline(hours=24)
    for hour, count in timeline.items():
        print(f"{hour}: {count} violations")

Rule Statistics
~~~~~~~~~~~~~~~

.. code-block:: python

    stats = analytics.get_rule_statistics()
    print(f"Total requests: {stats['total_requests']}")
    print(f"Violations: {stats['violations']}")
    print(f"Block rate: {stats['block_rate']}%")

Exporting Data
--------------

Export to JSON
~~~~~~~~~~~~~~

.. code-block:: python

    analytics.export_report('report.json', format='json')

Export to CSV
~~~~~~~~~~~~~

.. code-block:: python

    analytics.export_csv('report.csv', format='csv')

Best Practices
--------------

1. **Set Appropriate History Limits**
   - Balance detail vs memory usage
   - 10,000-50,000 for most applications

2. **Enable Data Sanitization**
   - Protect user privacy
   - Comply with data protection regulations

3. **Regular Exports**
   - Export reports periodically
   - Archive for long-term analysis

4. **Monitor Trends**
   - Track block rates over time
   - Identify patterns and adjust limits

Next Steps
----------

* Use the :doc:`cli` for reporting
* Set up :doc:`distributed` analytics
