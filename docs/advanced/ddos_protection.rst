DDoS Protection
===============

RateThrottle includes advanced DDoS detection and mitigation capabilities.

Overview
--------

The DDoS protection layer analyzes traffic patterns and automatically blocks suspicious activity:

* High request rate detection
* Scanning behavior detection
* Burst pattern analysis
* Bot behavior identification
* Automatic blocking with configurable thresholds

Quick Start
-----------

.. code-block:: python

    from ratethrottle import DDoSProtection

    ddos = DDoSProtection({
        'enabled': True,
        'threshold': 10000,      # requests per window
        'window': 60,            # seconds
        'auto_block': True,
        'block_duration': 3600   # 1 hour
    })

    # Analyze traffic
    pattern = ddos.analyze_traffic('192.168.1.100', '/api/data')
    
    if pattern.is_suspicious:
        print(f"Attack detected! Score: {pattern.suspicious_score}")
        
Configuration
-------------

Complete configuration options:

.. code-block:: python

    ddos = DDoSProtection({
        'enabled': True,
        'threshold': 10000,              # Max requests per window
        'window': 60,                    # Time window (seconds)
        'auto_block': True,              # Auto-block attackers
        'block_duration': 3600,          # Block duration (seconds)
        'suspicious_threshold': 0.5,     # Suspicion score threshold (0.0-1.0)
        'max_unique_endpoints': 50,      # Max unique endpoints before flagging
        'burst_threshold': 100,          # Burst detection threshold
        'burst_window': 10,              # Burst detection window
        'min_interval_threshold': 0.1,   # Min time between requests (bot detection)
        'whitelist_on_good_behavior': True,
        'good_behavior_threshold': 1000
    })

Detection Methods
-----------------

High Request Rate
~~~~~~~~~~~~~~~~~

Detects when request rate exceeds normal thresholds:

.. code-block:: python

    # Triggers when > 10,000 requests in 60 seconds
    if pattern.request_rate > (ddos.config['threshold'] / ddos.config['window']):
        print("High request rate detected")

Scanning Behavior
~~~~~~~~~~~~~~~~~

Detects clients accessing many unique endpoints:

.. code-block:: python

    # Flags clients accessing > 50 unique endpoints
    if pattern.unique_endpoints > ddos.config['max_unique_endpoints']:
        print("Scanning behavior detected")

Bot Behavior
~~~~~~~~~~~~

Identifies automated clients by uniform request intervals:

.. code-block:: python

    # Flags requests with < 0.1s interval
    if pattern.metadata.get('min_interval', 1.0) < 0.1:
        print("Bot behavior detected")

Usage Examples
--------------

Basic Protection
~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import DDoSProtection

    ddos = DDoSProtection({'enabled': True})

    # In your request handler
    def handle_request(client_ip, endpoint):
        pattern = ddos.analyze_traffic(client_ip, endpoint)
        
        if pattern.is_suspicious:
            # Block the request
            return error_response(403, "Suspicious activity detected")
        
        # Continue processing
        return process_request()

With Auto-Blocking
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    ddos = DDoSProtection({
        'enabled': True,
        'auto_block': True,
        'block_duration': 3600
    })

    def handle_request(client_ip, endpoint):
        # Check if blocked
        if ddos.is_blocked(client_ip):
            return error_response(403, "Temporarily blocked")
        
        # Analyze traffic
        pattern = ddos.analyze_traffic(client_ip, endpoint)
        
        if pattern.is_suspicious and ddos.config['auto_block']:
            # Automatically blocked by DDoS protection
            return error_response(403, "Blocked due to suspicious activity")
        
        return process_request()

Monitoring
----------

Get Statistics
~~~~~~~~~~~~~~

.. code-block:: python

    stats = ddos.get_statistics()
    
    print(f"Total analyzed: {stats['total_analyzed']}")
    print(f"Suspicious: {stats['suspicious_count']}")
    print(f"Blocked IPs: {len(stats['blocked_ips'])}")
    print(f"Recent patterns: {stats['recent_patterns']}")

Blocked IPs
~~~~~~~~~~~~~~~

.. code-block:: python

    blocked = ddos.block_ip('192.168.1.100')

    print(f"Blocked: {blocked}")

Unblock IP
~~~~~~~~~~

.. code-block:: python

    ddos.unblock('192.168.1.100')

Integration with Rate Limiting
-------------------------------

Combine DDoS protection with rate limiting:

.. code-block:: python

    from ratethrottle import RateThrottleCore, RateThrottleRule, DDoSProtection

    limiter = RateThrottleCore()
    ddos = DDoSProtection({'enabled': True})

    rule = RateThrottleRule(name="api", limit=100, window=60)
    limiter.add_rule(rule)

    def handle_request(client_ip, endpoint):
        # First check DDoS
        if ddos.is_blocked(client_ip):
            return error_response(403)
        
        pattern = ddos.analyze_traffic(client_ip, endpoint)
        if pattern.is_suspicious:
            return error_response(403)
        
        # Then check rate limit
        status = limiter.check_rate_limit(client_ip, "api")
        if not status.allowed:
            return error_response(429)
        
        return process_request()

Best Practices
--------------

1. **Set Appropriate Thresholds**
   - Start conservative, adjust based on traffic
   - Consider legitimate high-volume users
   - Different thresholds for different endpoints

2. **Monitor False Positives**
   - Track blocked legitimate users
   - Adjust `suspicious_threshold` if needed
   - Use whitelist for known good actors

3. **Combine with Rate Limiting**
   - DDoS protection for attacks
   - Rate limiting for normal abuse
   - Different strategies for different threats

4. **Log Suspicious Activity**
   - Track all suspicious patterns
   - Export for security analysis
   - Set up alerts for admins

5. **Test Your Configuration**
   - Simulate attacks in staging
   - Verify blocking behavior
   - Ensure legitimate traffic isn't blocked

Next Steps
----------

* Configure :doc:`analytics` for monitoring
* Set up :doc:`cli` for management
* Learn about :doc:`distributed` deployments