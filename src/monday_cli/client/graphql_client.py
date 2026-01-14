"""GraphQL client for Monday.com API."""

import json
import logging
from typing import Any

import httpx

from monday_cli.constants import COMPLEXITY_WARNING_THRESHOLD, REQUEST_TIMEOUT, USER_AGENT
from monday_cli.utils.error_handler import (
    AuthenticationError,
    ComplexityError,
    MondayAPIError,
    NetworkError,
    RateLimitError,
)
from monday_cli.utils.rate_limit import MondayRateLimiter
from monday_cli.utils.retry import create_retry_decorator

logger = logging.getLogger("monday_cli.client")


class MondayGraphQLClient:
    """Client for interacting with Monday.com GraphQL API."""

    def __init__(
        self,
        api_token: str,
        api_url: str,
        rate_limiter: MondayRateLimiter | None = None,
        retry_max_attempts: int = 3,
        retry_backoff_factor: float = 2.0,
    ) -> None:
        """Initialize GraphQL client.

        Args:
            api_token: Monday.com API token
            api_url: Monday.com API URL
            rate_limiter: Optional rate limiter instance
            retry_max_attempts: Maximum retry attempts
            retry_backoff_factor: Retry backoff multiplier
        """
        self.api_url = api_url
        self.rate_limiter = rate_limiter or MondayRateLimiter()
        self.retry_decorator = create_retry_decorator(retry_max_attempts, retry_backoff_factor)

        # Set up headers
        self.headers = {
            "Authorization": api_token,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

        # Create httpx client
        self.client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers=self.headers,
            follow_redirects=True,
        )

        logger.debug("Initialized Monday GraphQL client")

    def __enter__(self) -> "MondayGraphQLClient":
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.close()

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()
        logger.debug("Closed Monday GraphQL client")

    def _make_request(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a GraphQL request.

        Args:
            query: GraphQL query or mutation
            variables: Optional query variables

        Returns:
            Response data

        Raises:
            AuthenticationError: If authentication fails
            RateLimitError: If rate limit is exceeded
            ComplexityError: If query complexity is too high
            MondayAPIError: If API returns an error
            NetworkError: If network request fails
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        logger.debug(f"Making GraphQL request: {query[:100]}...")
        if variables:
            logger.debug(f"Variables: {variables}")

        try:
            response = self.client.post(self.api_url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid API token")
            elif e.response.status_code == 429:
                retry_after = int(e.response.headers.get("Retry-After", 60))
                raise RateLimitError(retry_after)
            else:
                raise MondayAPIError(f"HTTP {e.response.status_code}: {str(e)}")
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as e:
            raise NetworkError(f"Network error: {str(e)}")

        try:
            response_data: dict[str, Any] = response.json()
        except json.JSONDecodeError as e:
            raise MondayAPIError(f"Invalid JSON response: {str(e)}")

        logger.debug(f"Received response with status {response.status_code}")

        # Check for complexity information
        if "data" in response_data and isinstance(response_data["data"], dict):
            complexity = response_data["data"].get("complexity")
            if complexity:
                before = complexity.get("before", 0)
                after = complexity.get("after", 0)
                logger.info(f"Complexity: before={before}, after={after}")

                if after < COMPLEXITY_WARNING_THRESHOLD:
                    reset_in = complexity.get("reset_in_x_seconds", "unknown")
                    logger.warning(f"Low complexity remaining: {after}. Resets in {reset_in}s")

        # Check for GraphQL errors
        if "errors" in response_data and response_data["errors"]:
            errors = response_data["errors"]
            error_messages = [err.get("message", str(err)) for err in errors]
            error_msg = "; ".join(error_messages)

            # Check for complexity errors
            if any("complexity" in msg.lower() for msg in error_messages):
                raise ComplexityError(f"Query complexity too high: {error_msg}")

            raise MondayAPIError(f"GraphQL errors: {error_msg}", response_data)

        return response_data

    @property
    def _rate_limited_request(self) -> Any:
        """Get rate-limited request method."""
        return self.rate_limiter(self.retry_decorator(self._make_request))

    def execute_query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL query with retry and rate limiting.

        Args:
            query: GraphQL query
            variables: Optional query variables

        Returns:
            Response data dictionary

        Raises:
            Various exceptions from _make_request
        """
        response = self._rate_limited_request(query, variables)
        return response.get("data", {})

    def execute_mutation(
        self, mutation: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL mutation with retry and rate limiting.

        Args:
            mutation: GraphQL mutation
            variables: Optional mutation variables

        Returns:
            Response data dictionary

        Raises:
            Various exceptions from _make_request
        """
        response = self._rate_limited_request(mutation, variables)
        return response.get("data", {})

    def get_complexity(self) -> dict[str, Any]:
        """Get current API complexity information.

        Returns:
            Complexity information
        """
        from monday_cli.client.queries import GET_COMPLEXITY

        response = self.execute_query(GET_COMPLEXITY)
        return response.get("complexity", {})
