"""Retry logic for Monday CLI."""

import logging
from collections.abc import Callable
from typing import TypeVar

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from monday_cli.constants import (
    DEFAULT_RETRY_BACKOFF_FACTOR,
    DEFAULT_RETRY_MAX_ATTEMPTS,
    DEFAULT_RETRY_MAX_WAIT,
    DEFAULT_RETRY_MIN_WAIT,
)
from monday_cli.utils.error_handler import NetworkError, RateLimitError

logger = logging.getLogger("monday_cli.retry")

T = TypeVar("T", bound=Callable[..., object])


def create_retry_decorator(
    max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
    backoff_factor: float = DEFAULT_RETRY_BACKOFF_FACTOR,
) -> Callable[[T], T]:
    """Create a retry decorator for API calls.

    Args:
        max_attempts: Maximum number of retry attempts
        backoff_factor: Exponential backoff multiplier

    Returns:
        Retry decorator
    """
    return retry(  # type: ignore[return-value]
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(
            multiplier=backoff_factor,
            min=DEFAULT_RETRY_MIN_WAIT,
            max=DEFAULT_RETRY_MAX_WAIT,
        ),
        retry=retry_if_exception_type(
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.ConnectError,
                NetworkError,
                RateLimitError,
            )
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
