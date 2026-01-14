"""Rate limiting for Monday CLI."""

import time
from collections import deque
from collections.abc import Callable
from typing import TypeVar

from monday_cli.constants import DEFAULT_RATE_LIMIT_CALLS, DEFAULT_RATE_LIMIT_PERIOD

T = TypeVar("T", bound=Callable[..., object])


class MondayRateLimiter:
    """Rate limiter for Monday.com API calls.

    Monday.com rate limits:
    - Complexity: 10M per minute per account
    - Individual query: 5M complexity limit

    This rate limiter provides a conservative call-based limit.
    """

    def __init__(
        self, calls: int = DEFAULT_RATE_LIMIT_CALLS, period: int = DEFAULT_RATE_LIMIT_PERIOD
    ) -> None:
        """Initialize rate limiter.

        Args:
            calls: Maximum number of calls per period
            period: Time period in seconds
        """
        self.calls = calls
        self.period = period
        self.call_times: deque[float] = deque()

    def __call__(self, func: T) -> T:
        """Decorate a function with rate limiting.

        Args:
            func: Function to rate limit

        Returns:
            Decorated function
        """

        def wrapper(*args: object, **kwargs: object) -> object:
            """Wrapper that implements rate limiting."""
            current_time = time.time()

            # Remove calls outside the time window
            while self.call_times and self.call_times[0] < current_time - self.period:
                self.call_times.popleft()

            # Check if we've hit the rate limit
            if len(self.call_times) >= self.calls:
                # Calculate how long to wait
                sleep_time = self.period - (current_time - self.call_times[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                # Clean up old calls after sleeping
                current_time = time.time()
                while self.call_times and self.call_times[0] < current_time - self.period:
                    self.call_times.popleft()

            # Record this call
            self.call_times.append(time.time())

            # Execute the function
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]
