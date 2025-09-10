"""
Custom exception classes for paper ingestion module.
"""


class IngestionError(Exception):
    """Base exception for all ingestion-related errors."""

    pass


class ClientError(IngestionError):
    """Base exception for client-specific errors."""

    pass


class FetchError(ClientError):
    """Raised when fetching data from an external source fails."""

    def __init__(self, message: str, source: str = None, status_code: int = None):
        super().__init__(message)
        self.source = source
        self.status_code = status_code


class TimeoutError(ClientError):
    """Raised when a request times out."""

    def __init__(self, message: str, timeout: float = None):
        super().__init__(message)
        self.timeout = timeout


class RetryExhaustedError(ClientError):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, message: str, attempts: int = None):
        super().__init__(message)
        self.attempts = attempts


class ValidationError(ClientError):
    """Raised when data validation fails."""

    def __init__(self, message: str, field: str = None, value=None):
        super().__init__(message)
        self.field = field
        self.value = value
