"""Custom exceptions for Monday CLI."""

from typing import Any


class MondayCliError(Exception):
    """Base exception for Monday CLI."""

    pass


class MondayAPIError(MondayCliError):
    """API request failed."""

    def __init__(self, message: str, response: dict[str, Any] | None = None) -> None:
        """Initialize API error.

        Args:
            message: Error message
            response: Optional API response data
        """
        self.response = response
        super().__init__(message)


class AuthenticationError(MondayCliError):
    """Authentication failed - invalid token."""

    pass


class RateLimitError(MondayCliError):
    """Rate limit exceeded."""

    def __init__(self, retry_after: int | None = None) -> None:
        """Initialize rate limit error.

        Args:
            retry_after: Seconds until rate limit resets
        """
        self.retry_after = retry_after
        message = (
            f"Rate limit exceeded. Retry after {retry_after}s"
            if retry_after
            else "Rate limit exceeded"
        )
        super().__init__(message)


class ValidationError(MondayCliError):
    """Input validation failed."""

    pass


class NetworkError(MondayCliError):
    """Network connectivity issue."""

    pass


class ComplexityError(MondayCliError):
    """Query complexity too high."""

    pass
