# Contributing to RateThrottle

Thank you for your interest in contributing to RateThrottle! This document provides guidelines and instructions for contributing.

## Code of Conduct

We are committed to providing a welcoming and inspiring community for all. Please read and follow our Code of Conduct.

## How to Contribute

### Reporting Bugs

Before creating bug reports, please check the issue list as you might find out that you don't need to create one. When you are creating a bug report, please include as many details as possible:

* Use a clear and descriptive title
* Describe the exact steps to reproduce the problem
* Provide specific examples to demonstrate the steps
* Describe the behavior you observed and what behavior you expected
* Include Python version, RateThrottle version, and OS information

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, please include:

* Use a clear and descriptive title
* Provide a step-by-step description of the suggested enhancement
* Provide specific examples to demonstrate the enhancement
* Describe the current behavior and explain the behavior you expected

### Pull Requests

1. Fork the repo and create your branch from `main`
2. If you've added code that should be tested, add tests
3. If you've changed APIs, update the documentation
4. Ensure the test suite passes
5. Make sure your code lints
6. Issue that pull request!

## Development Setup

### Prerequisites

* Python 3.10 or higher
* Git

### Setting Up Development Environment

```bash
# Clone your fork
git clone https://github.com/MykeChidi/ratethrottle.git
cd ratethrottle

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest tests

# Run with coverage
pytest tests --cov=ratethrottle --cov-report=html

# Run specific test file
pytest tests/test_file.py

# Run with verbose output
pytest tests -v

# Run specific test
pytest tests/test_core.py::TestRateThrottleCore::test_add_rule
```

### Code Style

We use the following tools to maintain code quality:

* **Black** for code formatting
* **isort** for import sorting
* **flake8** for linting
* **mypy** for type checking

```bash
# Format code
black ratethrottle 

# Sort imports
isort ratethrottle

# Run linting
flake8 ratethrottle

# Run type checking
mypy ratethrottle
```


## Coding Guidelines

### Python Style

* Follow PEP 8 style guide
* Use type hints for function signatures
* Write docstrings for all public functions/classes
* Keep functions focused and single-purpose
* Maximum line length: 100 characters

### Docstring Format

We use Google-style docstrings:

```python
def function_name(param1: str, param2: int) -> bool:
    """
    Brief description of function
    
    Longer description if needed, explaining behavior,
    edge cases, etc.
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Description of return value
    
    Raises:
        ValueError: When param1 is invalid
    
    Examples:
        >>> function_name("test", 42)
        True
    """
    pass
```

### Testing Guidelines

* Write tests for all new features
* Aim for >90% code coverage
* Use descriptive test names
* Follow AAA pattern: Arrange, Act, Assert
* Use pytest fixtures for setup
* Mock external dependencies

Example test:

```python
def test_rate_limit_allows_within_limit(self, limiter, basic_rule):
    """Test that requests within limit are allowed"""
    # Arrange
    limiter.add_rule(basic_rule)
    identifier = "192.168.1.100"
    
    # Act
    status = limiter.check_rate_limit(identifier, "test_rule")
    
    # Assert
    assert status.allowed
    assert status.remaining == 9
```

### Error Handling

* Use custom exceptions from `exceptions.py`
* Provide clear error messages
* Log errors appropriately
* Handle edge cases gracefully

```python
from ratethrottle.exceptions import ConfigurationError

def validate_config(config):
    """Validate configuration"""
    if not config.get('limit'):
        raise ConfigurationError(
            "Rate limit configuration must include 'limit' parameter"
        )
```

### Logging

* Use the logging module
* Use appropriate log levels
* Include context in log messages
* Don't log sensitive information

```python
import logging

logger = logging.getLogger(__name__)

logger.debug("Processing request for %s", identifier)
logger.info("Rate limit rule added: %s", rule.name)
logger.warning("Suspicious activity detected: %s", pattern)
logger.error("Failed to connect to Redis: %s", error)
```

## Documentation

* Update README.md for user-facing changes
* Update docstrings for code changes
* Add examples for new features
* Update CHANGELOG.md

## Commit Messages

* Use clear and meaningful commit messages
* Start with a verb in present tense
* Reference issues when applicable

Examples:
* `Add Redis connection pooling support`
* `Fix race condition in token bucket strategy`
* `Update documentation for DDoS protection`
* `Refactor storage backend interface (#42)`

## Questions?

Feel free to:
* Open an issue for bugs or feature requests
* Start a discussion for questions
* Reach out to maintainers

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
