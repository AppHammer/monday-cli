"""Retry logic for Monday CLI."""

import logging
from collections.abc import Callable
from typing import TypeVar

import httpx
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from monday_cli.constants import (
    DEFAULT_RETRY_BACKOFF_FACTOR,
    DEFAULT_RETRY_MAX_ATTEMPTS,
    DEFAULT_RETRY_MAX_WAIT,
    DEFAULT_RETRY_MIN_WAIT,
)
from monday_cli.utils.error_handler import NetworkError, RateLimitError

logger = logging.getLogger("monday_cli.retry")

T = TypeVar("T", bound=Callable[..., object])


class _WaitRateLimitOrExponential(wait_base):
    """Wait strategy that honours ``RateLimitError.retry_after``.

    For ``RateLimitError`` exceptions that carry a ``retry_after`` value we
    sleep exactly that many seconds (plus a small buffer) so the next attempt
    arrives after Monday's reset window has elapsed.  For all other retriable
    exceptions (network errors, timeouts) we fall back to standard exponential
    backoff so those retries stay fast.
    """

    def __init__(self, multiplier: float, min_wait: float, max_wait: float) -> None:
        self._exp = wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait)
        self._retry_after_buffer = 2.0  # extra seconds on top of Retry-After

    def __call__(self, retry_state: RetryCallState) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exc, RateLimitError) and exc.retry_after:
            wait = float(exc.retry_after) + self._retry_after_buffer
            logger.warning("Rate limit hit; honouring Retry-After, sleeping %.0fs", wait)
            return wait
        return self._exp(retry_state)


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
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=_WaitRateLimitOrExponential(
            multiplier=backoff_factor,
            min_wait=DEFAULT_RETRY_MIN_WAIT,
            max_wait=DEFAULT_RETRY_MAX_WAIT,
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
