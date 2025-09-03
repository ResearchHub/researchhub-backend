"""
Custom exception classes for paper ingestion module.
"""


class IngestionError(Exception):
    """Base exception for all ingestion-related errors."""

    pass


class AdapterError(IngestionError):
    """Base exception for adapter-specific errors."""

    pass


class FetchError(AdapterError):
    """Raised when fetching data from an external source fails."""

    def __init__(self, message: str, source: str = None, status_code: int = None):
        super().__init__(message)
        self.source = source
        self.status_code = status_code


class ParseError(AdapterError):
    """Raised when parsing response data fails."""

    def __init__(self, message: str, source: str = None, raw_data: str = None):
        super().__init__(message)
        self.source = source
        self.raw_data = raw_data


class ValidationError(AdapterError):
    """Raised when data validation fails."""

    def __init__(self, message: str, field: str = None, value=None):
        super().__init__(message)
        self.field = field
        self.value = value


class RateLimitError(IngestionError):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after


class CircuitBreakerError(IngestionError):
    """Raised when circuit breaker is open."""

    def __init__(self, message: str, service: str = None, reset_time: float = None):
        super().__init__(message)
        self.service = service
        self.reset_time = reset_time


class StorageError(IngestionError):
    """Raised when storing or retrieving data fails."""

    pass


class ConfigurationError(IngestionError):
    """Raised when configuration is invalid or missing."""

    pass


class AuthenticationError(AdapterError):
    """Raised when authentication with external service fails."""

    pass


class TimeoutError(AdapterError):
    """Raised when a request times out."""

    def __init__(self, message: str, timeout: float = None):
        super().__init__(message)
        self.timeout = timeout


class RetryExhaustedError(AdapterError):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, message: str, attempts: int = None):
        super().__init__(message)
        self.attempts = attempts
