"""
Custom exceptions for RateThrottle
"""


class RateThrottleException(Exception):
    """Base exception for all RateThrottle errors"""

    pass


class ConfigurationError(RateThrottleException):
    """Raised when there's a configuration error"""

    pass


class StorageError(RateThrottleException):
    """Raised when there's a storage backend error"""

    pass


class RateLimitExceeded(RateThrottleException):
    """Raised when rate limit is exceeded"""

    def __init__(
        self,
        message: str,
        retry_after: int = 0,
        limit: int = 0,
        remaining: int = 0,
        reset_time: int = 0,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining
        self.reset_time = reset_time


class StrategyNotFoundError(RateThrottleException):
    """Raised when a rate limiting strategy is not found"""

    pass


class RuleNotFoundError(RateThrottleException):
    """Raised when a rate limiting rule is not found"""

    pass


class InvalidRuleError(RateThrottleException):
    """Raised when a rule configuration is invalid"""

    pass


class StorageUnavailableError(RateThrottleException):
    """Raised when storage backend is unavailable"""

    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimitDegradedError(RateThrottleException):
    """Raised when operating in degraded/fallback mode"""

    def __init__(self, message: str, mode: str = "unknown"):
        super().__init__(message)
        self.mode = mode


class InvalidIdentifierError(RateThrottleException):
    """Raised when identifier is invalid or missing"""

    pass


class RuleConfigurationError(RateThrottleException):
    """Raised when rule configuration is invalid"""

    pass
