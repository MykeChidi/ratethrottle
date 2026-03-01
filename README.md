# `RateThrottle`

[![Pypi](https://img.shields.io/pypi/v/ratethrottle.svg)](https://pypi.org/project/ratethrottle/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Advanced rate limiting and DDoS protection for Python web applications.**

RateThrottle is a comprehensive rate limiting library that provides enterprise-level features for protecting your APIs and web applications from abuse, with built-in DDoS protection, different storage backends, multiple strategies and protocols with seamless integration with popular Python web frameworks.

## ✨ Features

- 🚀 **Multiple Rate Limiting Strategies**
  - Sliding Window Log (default)
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
from fastapi import FastAPI
from ratethrottle import FastAPIRateLimiter

app = FastAPI()
limiter = FastAPIRateLimiter()

@app.get("/api/data")
@limiter.limit("100/minute")
async def get_data():
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

```python
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
```


## 📖 Documentation

### Rate Limiting Strategies

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

### Redis Backend (Distributed)

```python
from ratethrottle import create_limiter

# Using Redis for distributed rate limiting
limiter = create_limiter('redis', 'redis://localhost:6379/0')

# Now works across multiple servers!
```

### Configuration Files

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
  default_strategy: sliding_window
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

### GRPC Example
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
```

### GraphQL Example
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

### Websocket Example
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
### DDoS Protection

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

### Whitelist/Blacklist Management

```python
# Add to whitelist (bypass all limits)
limiter.add_to_whitelist('192.168.1.100')

# Add to blacklist (block all requests)
limiter.add_to_blacklist('192.168.1.200', duration=3600)  # Block for 1 hour

# Remove from blacklist
limiter.remove_from_blacklist('192.168.1.200')
```

### Violation Callbacks

```python
def handle_violation(violation):
    """Custom violation handler"""
    print(f"⚠️ Violation: {violation.identifier}")
    print(f"Rule: {violation.rule_name}")
    print(f"Requests: {violation.requests_made}/{violation.limit}")
    
    # Send alert, log to database, etc.

limiter.register_violation_callback(handle_violation)
```

### Metrics and Monitoring

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

## 🖥️ CLI Usage

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


## 📊 Performance

RateThrottle is designed for high performance:

- **In-memory storage**: 100,000+ requests/second
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
