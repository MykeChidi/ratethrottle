<div align="center">
  <img src="./docs/logo.png" alt="Logo" width="200"/>
  <h1> Ratethrottle </h1>
</div>

[![Pypi](https://img.shields.io/pypi/v/ratethrottle.svg)](https://pypi.org/project/ratethrottle/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Advanced rate limiting and DDoS protection for Python web applications.**

RateThrottle is a comprehensive rate limiting library that provides enterprise-level features for protecting your APIs and web applications from abuse, with built-in DDoS protection, different storage backends, multiple strategies and protocols, ML adaptive ratelimiting and seamless integration with popular Python web frameworks.

## ✨ Features

- 🚀 **Multiple Rate Limiting Strategies**
  - Sliding Window Counter (default)
  - Sliding Window Log 
  - Token Bucket
  - Leaky Bucket
  - Fixed Window
  
- 🚀 **Different protocol support**
  - REST
  - GRPC
  - GraphQL
  - Websocket

- 🛡️ **Advanced DDoS Protection**
  - Traffic pattern analysis
  - Automatic suspicious activity detection
  - Auto-blocking capabilities
  
- 💾 **Flexible Storage Backends**
  - In-memory (single instance)
  - Redis (distributed/multi-server)
  - Easy to extend with custom backends
  
- 🔧 **Framework Integration**
  - Flask
  - FastAPI
  - Django
  - Starlette
  - Generic WSGI/ASGI support
  
- 📊 **Monitoring & Analytics**
  - Real-time metrics
  - Violation tracking
  - CLI dashboard
  
- ⚙️ **Configuration Management**
  - YAML configuration files
  - Programmatic configuration
  - Hot-reloading support

- 🤖 **ML Adaptive Limiting**
  - Pattern learning with Exponential Moving Average
  - Z-score based anomaly detection
  - Trust scoring system
  - Automatic limit adjustment

## 🚀 Quick Start

### Installation

```bash
# Basic installation
pip install ratethrottle

# With Redis support
pip install ratethrottle[redis]

# With Flask support
pip install ratethrottle[flask]

# With FastAPI support
pip install ratethrottle[fastapi]

# With Django support
pip install ratethrottle[django]

# With all frameworks
pip install ratethrottle[frameworks]

# With grpc support
pip install ratethrottle[grpc]

# With graphQL support
pip install ratethrottle[graphql]

# With websocket support
pip install ratethrottle[websocket]

# With all protocols
pip install ratethrottle[protocols]
```

### Flask Example

```python
from flask import Flask
from ratethrottle import FlaskRateLimiter

app = Flask(__name__)
limiter = FlaskRateLimiter(app)

@app.route('/api/data')
@limiter.limit("100/minute")
def get_data():
    return {'data': 'value'}

@app.route('/api/auth')
@limiter.limit("5/minute")
def login():
    return {'token': 'abc123'}

if __name__ == '__main__':
    app.run()
```

### FastAPI Example

```python
from fastapi import FastAPI, Depends
from ratethrottle import FastAPIRateLimiter

app = FastAPI()
limiter = FastAPIRateLimiter()

rate_limit = limiter.limit(100, 60)

@app.get("/api/data")
async def get_data(request, _=Depends(ratelimit)):
    return {"data": "value"}
```

### Django Example

```python
from django.http import JsonResponse
from ratethrottle import django_ratelimit

@django_ratelimit(limit=100, window=60, key='ip')
def api_view(request):
    return JsonResponse({'data': 'value'})
```

### Standalone Usage

**Basic limiting**

```python
from ratethrottle import RateThrottleCore, RateThrottleRule

# Create limiter
limiter = RateThrottleCore()

# Add rule
rule = RateThrottleRule(
    name='api_limit',
    limit=100,
    window=60,
    strategy='sliding_counter'
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
```

**Adaptive limiting**

```python
from ratethrottle import AdaptiveRateLimiter

limiter = AdaptiveRateLimiter(
      base_limit=100,
      learning_rate=0.1,
      anomaly_threshold=3.0
)

result = limiter.check_adaptive('user_123')
if result['allowed']:
    print(f"Limit: {result['adjusted_limit']}")
    print(f"Trust: {result['trust_score']:.2f}")
else:
    print(f"Request blocked! Reason{result['reason']}")
    print(f"Retry after {result['retry_after']}")
```

## 📖 Documentation

<details><summary>Rate Limiting Strategies</summary>

#### 1. Token Bucket
Best for: APIs with burst allowances
```python
rule = RateThrottleRule(
    name='api_burst',
    limit=100,
    window=60,
    strategy='token_bucket',
    burst=150  # Allow up to 150 tokens in bucket
)
```

#### 2. Leaky Bucket
Best for: Smooth, constant rate processing
```python
rule = RateThrottleRule(
    name='api_steady',
    limit=100,
    window=60,
    strategy='leaky_bucket'
)
```

#### 3. Fixed Window
Best for: Simple, efficient rate limiting
```python
rule = RateThrottleRule(
    name='api_window',
    limit=100,
    window=60,
    strategy='fixed_window'
)
```

#### 4. Sliding Window Log
Best for: Precise rate limiting without edge cases
```python
rule = RateThrottleRule(
    name='api_precise',
    limit=100,
    window=60,
    strategy='sliding_window'
)
```

#### 4. Sliding Window Counter
Best for: Accurate limiting with efficient memory usage
```python
rule = RateThrottleRule(
    name='api_default',
    limit=100,
    window=60,
    strategy='sliding_counter'
)
```

</details>

<details><summary>Redis Backend (Distributed)</summary>

```python
from ratethrottle import create_limiter

# Using Redis for distributed rate limiting
limiter = create_limiter('redis', 'redis://localhost:6379/0')

# Now works across multiple servers!
```

</details>

<details><summary>Configuration Files</summary>

Create `ratethrottle.yaml`:

```yaml
# Storage backend
storage:
  type: redis
  redis:
    host: localhost
    port: 6379
    db: 0

# Global settings
global:
  enabled: true
  default_strategy: sliding_counter
  headers_enabled: true

# Rate limiting rules
rules:
  - name: api_default
    limit: 1000
    window: 3600
    strategy: token_bucket
    
  - name: auth_strict
    limit: 5
    window: 60
    strategy: sliding_window
    block_duration: 900

# DDoS Protection
ddos_protection:
  enabled: true
  threshold: 10000
  auto_block: true
  block_duration: 3600
```

Load configuration:

```python
from ratethrottle import ConfigManager, RateThrottleCore

config = ConfigManager('ratethrottle.yaml')
limiter = RateThrottleCore()

for rule in config.get_rules():
    limiter.add_rule(rule)
```

</details>

<details><summary>GRPC Example</summary>

```python
from concurrent import futures
import grpc
from ratethrottle import GRPCRateLimitInterceptor, GRPCLimits
        
 # Create interceptor
interceptor = GRPCRateLimitInterceptor(
     GRPCLimits(
        requests_per_minute=100,
        concurrent_requests=10
            )
)

# Create server with rate limiting
server = grpc.server(
    futures.ThreadPoolExecutor(max_workers=10),
    interceptors=[interceptor]
)
```

</details>

<details><summary>GraphQL Example</summary>

```python
from ratethrottle import GraphQLRateLimiter, GraphQLLimits

limiter = GraphQLRateLimiter(
    GraphQLLimits(
        queries_per_minute=100,
        max_complexity=1000
    )
)

# Check if query is allowed
error = limiter.check_rate_limit(
    document_ast=parsed_query,
    context=request_context
)
    
if error:
    raise error # GraphQLError
```

</details>

<details><summary>Websocket Example</summary>

```python
from ratethrottle import WebSocketRateLimiter, WebSocketLimits

limiter = WebSocketRateLimiter(
    WebSocketLimits(
        connections_per_minute=10,
        messages_per_minute=100
    )
)

# Check if connection allowed
if await limiter.check_connection("client_id"):
    # Accept connection
    await limiter.register_connection("client_id", websocket)

```

</details>

<details><summary>Monitoring and Alerting</summary>

```python
from ratethrottle.monitoring import RateThrottleMonitor
from ratethrottle.alerting import AlertDispatcher

monitor = RateThrottleMonitor(
    {
        'enabled': True,
        'interval': 60,
        'log_metrics': True,
        'export_json': True,
        'export_path': 'metrics/metrics.json',
    },
    limiter=limiter,
    ddos=ddos,
    analytics=analytics,
)

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
            'enabled': False,
            'url': '',
            'timeout': 10,
        },
    }
)

monitor.start()

snapshot = monitor.snapshot_now()
dispatcher.check_and_alert(snapshot)
```

</details>

<details><summary>DDoS Protection</summary>

```python
from ratethrottle import DDoSProtection

ddos = DDoSProtection({
    'enabled': True,
    'threshold': 10000,
    'window': 60,
    'auto_block': True,
    'block_duration': 3600
})

# Analyze traffic pattern
pattern = ddos.analyze_traffic(
    identifier='192.168.1.100',
    endpoint='/api/data'
)

if pattern.is_suspicious:
    print(f"⚠️ Suspicious activity detected!")
    print(f"Request rate: {pattern.request_rate:.2f} req/s")
    print(f"Suspicion score: {pattern.suspicious_score:.2f}")
```

</details>

<details><summary>Whitelist/Blacklist Management</summary>

```python
# Add to whitelist (bypass all limits)
limiter.add_to_whitelist('192.168.1.100')

# Add to blacklist (block all requests)
limiter.add_to_blacklist('192.168.1.200', duration=3600)  # Block for 1 hour

# Remove from blacklist
limiter.remove_from_blacklist('192.168.1.200')
```

</details>

<details><summary>Violation Callbacks</summary>

```python
def handle_violation(violation):
    """Custom violation handler"""
    print(f"⚠️ Violation: {violation.identifier}")
    print(f"Rule: {violation.rule_name}")
    print(f"Requests: {violation.requests_made}/{violation.limit}")
    
    # Send alert, log to database, etc.

limiter.register_violation_callback(handle_violation)
```

</details>

<details><summary>Metrics</summary>

```python
# Get metrics
metrics = limiter.get_metrics()

print(f"Total requests: {metrics['total_requests']}")
print(f"Blocked requests: {metrics['blocked_requests']}")
print(f"Block rate: {metrics['block_rate']:.2f}%")
print(f"Recent violations: {len(metrics['recent_violations'])}")

# Reset metrics
limiter.reset_metrics()
```

</details>

<details><summary>🖥️ CLI Usage</summary>

RateThrottle includes a powerful CLI for monitoring and management:

```bash
# Start interactive monitoring dashboard
ratethrottle monitor --config ratethrottle.yaml

# Test rate limiting configuration
ratethrottle test --rule api_default --identifier 192.168.1.100 --requests 150

# Manage whitelist/blacklist
ratethrottle manage --blacklist-add 192.168.1.50 --duration 3600
ratethrottle manage --whitelist-add 10.0.0.5

# View configuration
ratethrottle config --show

# Validate configuration
ratethrottle config --validate

# Export statistics
ratethrottle stats --export report.json
```
</details>


## 📊 Performance

RateThrottle is designed for high performance:

- **In-memory storage**: 10,000+ requests/second
- **Redis storage**: 50,000+ requests/second (network dependent)
- **Minimal overhead**: < 1ms per request check
- **Thread-safe**: Safe for concurrent use
- **Memory efficient**: Automatic cleanup of expired data


## 📝 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/MykeChidi/ratethrottle/blob/main/LICENSE) file for details.


## 📮 Support

- 🐛 Issues: [GitHub Issues](https://github.com/MykeChidi/ratethrottle/issues)
- 📖 Documentation: [Full Documentation](https://ratethrotttle/readthedocs.io)

---
