"""[FR-0016] Unit tests for rate-limit resilience in the integration test harness.

The new ``run_cli`` retry loop and its supporting helpers (``_is_rate_limit_exit``,
``_parse_retry_after``, ``_ratelimit_retries``, ``_ratelimit_backoff``) are pure
functions that can be exercised without a real Monday.com API token.  These tests
confirm that:

- Rate-limit exits are correctly identified from the exit code + stderr.
- The Retry-After value is extracted when present and a fallback is used otherwise.
- The retry loop in ``run_cli`` fires the right number of times before giving up.
- ``expect_error=True`` calls are never transparently retried (they assert error paths).
- Real (non-rate-limit) failures are NOT retried and surface immediately.
- Env-var tuning for retries and backoff works correctly.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration import helpers

# ---------------------------------------------------------------------------
# _is_rate_limit_exit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exit_code", "stderr", "expected"),
    [
        (1, "Error: Rate limit exceeded. Retry after 60s", True),
        (1, "Error: rate limit exceeded", True),
        (1, "Error: Too Many Requests", True),
        (1, "Error: Retry-After 30s", True),
        (1, "Error: 429 Too Many Requests", True),
        # Non-zero exit but NOT rate-limit stderr
        (1, "Error: Item not found", False),
        (1, "Error: Invalid API token", False),
        # Zero exit is never a rate-limit failure regardless of stderr
        (0, "Rate limit exceeded", False),
    ],
)
def test_is_rate_limit_exit(exit_code: int, stderr: str, expected: bool) -> None:
    assert helpers._is_rate_limit_exit(exit_code, stderr) == expected


# ---------------------------------------------------------------------------
# _is_transient_server_error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exit_code", "stderr", "expected"),
    [
        # Monday GraphQL "Internal server error" (exact phrase from production)
        (1, "GraphQL errors: Internal server error", True),
        # Case-insensitive match
        (1, "INTERNAL SERVER ERROR", True),
        # 503 Service Unavailable
        (1, "503 Service Unavailable", True),
        (1, "Service unavailable", True),
        (1, "temporarily unavailable", True),
        # Non-transient errors must NOT be retried
        (1, "Error: Item not found", False),
        (1, "Error: Invalid API token", False),
        (1, "GraphQL errors: Field 'foo' doesn't exist", False),
        # Zero exit is never a transient error regardless of stderr
        (0, "Internal server error", False),
    ],
)
def test_is_transient_server_error(exit_code: int, stderr: str, expected: bool) -> None:
    assert helpers._is_transient_server_error(exit_code, stderr) == expected


def test_run_cli_retries_on_transient_server_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient server error on the first attempt must be retried; success returned."""
    server_error = (1, "", "GraphQL errors: Internal server error", None)
    success = (0, '{"id":"1"}', "", None)

    fake = _make_invoke_sequence([server_error, success])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.setattr(helpers, "_invoke_binary", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    slept: list[float] = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    result = helpers.run_cli("items", "get", "--item-id", "1")

    assert result == {"id": "1"}
    # Must have slept once with the transient backoff
    assert len(slept) == 1
    assert slept[0] == helpers._DEFAULT_TRANSIENT_BACKOFF


# ---------------------------------------------------------------------------
# _parse_retry_after
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        # Canonical form from the CLI's RateLimitError message
        ("Error: Rate limit exceeded. Retry after 60s", 62.0),  # 60 + 2 buffer
        ("Rate limit exceeded. Retry after 30s", 32.0),
        # No parseable Retry-After -> None so caller falls back to default
        ("Error: Rate limit exceeded", None),
        ("", None),
    ],
)
def test_parse_retry_after(stderr: str, expected: float | None) -> None:
    result = helpers._parse_retry_after(stderr)
    assert result == expected


# ---------------------------------------------------------------------------
# env-tunable config
# ---------------------------------------------------------------------------


def test_ratelimit_retries_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "10")
    assert helpers._ratelimit_retries() == 10


def test_ratelimit_retries_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONDAY_IT_RATELIMIT_RETRIES", raising=False)
    assert helpers._ratelimit_retries() == helpers._DEFAULT_RATELIMIT_RETRIES


def test_ratelimit_retries_default_on_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "not-a-number")
    assert helpers._ratelimit_retries() == helpers._DEFAULT_RATELIMIT_RETRIES


def test_ratelimit_backoff_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_BACKOFF", "30.5")
    assert helpers._ratelimit_backoff() == 30.5


def test_ratelimit_backoff_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONDAY_IT_RATELIMIT_BACKOFF", raising=False)
    assert helpers._ratelimit_backoff() == helpers._DEFAULT_RATELIMIT_BACKOFF


# ---------------------------------------------------------------------------
# run_cli retry loop (FR-0016)
# ---------------------------------------------------------------------------


def _make_invoke_sequence(
    sequence: list[tuple[int, str, str, BaseException | None]],
) -> Any:
    """Return a fake ``_invoke_in_process`` that yields results from ``sequence``.

    The last entry is repeated indefinitely so callers can set ``max_retries``
    higher than the sequence length without an IndexError.
    """
    it = iter(sequence)
    last = sequence[-1]

    def _fake(*_args: Any) -> tuple[int, str, str, BaseException | None]:
        return next(it, last)

    return _fake


def test_run_cli_retries_on_rate_limit_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rate-limit exit on the first attempt must be retried; the second (success) returned."""
    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 60s", None)
    success = (0, '{"id":"1"}', "", None)

    fake = _make_invoke_sequence([rate_limit, success])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.setattr(helpers, "_invoke_binary", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    slept: list[float] = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    result = helpers.run_cli("items", "get", "--item-id", "1")

    assert result == {"id": "1"}
    # Must have slept once (the Retry-After-derived backoff)
    assert len(slept) == 1


def test_run_cli_gives_up_after_max_retries_surfaces_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistent rate-limiting beyond max_retries must surface as an AssertionError."""
    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 60s", None)

    fake = _make_invoke_sequence([rate_limit])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "2")
    monkeypatch.setattr(helpers.time, "sleep", lambda _s: None)

    with pytest.raises(AssertionError, match="exited 1"):
        helpers.run_cli("items", "get", "--item-id", "1")


def test_run_cli_does_not_retry_real_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-rate-limit failure must surface immediately with no retries."""
    real_error = (1, "", "Error: Item not found", None)

    call_count = [0]

    def _fake(*_args: Any) -> tuple[int, str, str, BaseException | None]:
        call_count[0] += 1
        return real_error

    monkeypatch.setattr(helpers, "_invoke_in_process", _fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setattr(helpers.time, "sleep", lambda _s: None)

    with pytest.raises(AssertionError, match="exited 1"):
        helpers.run_cli("items", "get", "--item-id", "1")

    # Only one invocation — never retried
    assert call_count[0] == 1


def test_run_cli_does_not_retry_when_expect_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """expect_error=True callers need the raw error output — no transparent retry."""
    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 60s", None)

    call_count = [0]

    def _fake(*_args: Any) -> tuple[int, str, str, BaseException | None]:
        call_count[0] += 1
        return rate_limit

    monkeypatch.setattr(helpers, "_invoke_in_process", _fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setattr(helpers.time, "sleep", lambda _s: None)

    # This must NOT raise — expect_error=True suppresses the assertion
    result = helpers.run_cli("items", "get", "--item-id", "1", expect_error=True)

    # Only one invocation — rate-limit retry must not fire for expect_error calls
    assert call_count[0] == 1
    assert result == ""  # stdout is empty for this fake


def test_run_cli_uses_retry_after_for_sleep_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sleep duration must be derived from the Retry-After value in stderr."""
    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 30s", None)
    success = (0, '{"ok":true}', "", None)

    fake = _make_invoke_sequence([rate_limit, success])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    slept: list[float] = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    helpers.run_cli("items", "get", "--item-id", "1")

    # 30 s Retry-After + 2 s buffer == 32 s
    assert slept == [32.0]


def test_run_cli_falls_back_to_default_backoff_when_no_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Retry-After is absent from stderr, the default backoff must be used."""
    rate_limit = (1, "", "Error: Rate limit exceeded", None)
    success = (0, '{"ok":true}', "", None)

    fake = _make_invoke_sequence([rate_limit, success])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    slept: list[float] = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    helpers.run_cli("items", "get", "--item-id", "1")

    assert slept == [helpers._DEFAULT_RATELIMIT_BACKOFF]
