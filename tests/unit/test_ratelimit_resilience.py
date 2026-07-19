"""[FR-0016] Unit tests for rate-limit resilience in the integration test harness.

The new ``run_cli`` retry loop and its supporting helpers (``_is_rate_limit_exit``,
``_parse_retry_after``, ``_max_retries``, ``_ratelimit_backoff``) are pure
functions that can be exercised without a real Monday.com API token.  These tests
confirm that:

- Rate-limit exits are correctly identified from the exit code + stderr.
- The Retry-After value is extracted when present and a fallback is used otherwise.
- The retry loop in ``run_cli`` fires the right number of times before giving up.
- ``expect_error=True`` calls are never transparently retried (they assert error paths).
- Real (non-rate-limit) failures are NOT retried and surface immediately.
- Env-var tuning for retries and backoff works correctly.
- ``_WaitRateLimitOrExponential`` uses Retry-After when present, exponential otherwise.
- B-1: anchored \\b429\\b / \\b503\\b patterns don't false-match digit substrings.
- B-2: ``run_cli_streams`` applies the same retry loop as ``run_cli``.
- Write-safety: mutations (``is_mutation=True``) are NOT retried on 5xx.
- S-1: double-retry layering is bounded (tenacity ≤3 × harness ≤7 = ≤21 calls).
- S-2: ``test_run_cli_gives_up_after_max_retries_surfaces_failure`` asserts exactly
  3 total invocations (1 initial + 2 retries when max_retries=2).
- S-3: ``retry_after=0`` is honoured, not treated as absent.
- N-1: ``_DEFAULT_TRANSIENT_BACKOFF`` is tunable via ``MONDAY_IT_TRANSIENT_BACKOFF``.
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
        # B-1: anchored \b429\b — digit substrings must NOT match
        (1, "board_id=18422673429 not found", False),  # 429 embedded in a larger number
        (1, "item 14290 created", False),  # starts with 429
        (1, "error_code=5429", False),  # ends with 429
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
        # B-1: anchored \b503\b — digit substrings must NOT match
        (1, "board_id=18422673503 not found", False),  # 503 embedded in a larger number
        (1, "item 50300 moved", False),  # starts with 503
        (1, "error_code=15030", False),  # contains 503 mid-string (no word boundary)
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


def test_max_retries_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "10")
    assert helpers._max_retries() == 10


def test_max_retries_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONDAY_IT_RATELIMIT_RETRIES", raising=False)
    assert helpers._max_retries() == helpers._DEFAULT_RATELIMIT_RETRIES


def test_max_retries_default_on_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "not-a-number")
    assert helpers._max_retries() == helpers._DEFAULT_RATELIMIT_RETRIES


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
    """Persistent rate-limiting beyond max_retries must surface as an AssertionError.

    S-2: assert exactly 3 total invocations when max_retries=2 (1 initial + 2 retries).
    This verifies the retry loop is bounded and does not over-spin.
    """
    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 60s", None)

    call_count = [0]

    def _counting_fake(*_args: Any) -> tuple[int, str, str, BaseException | None]:
        call_count[0] += 1
        return rate_limit

    monkeypatch.setattr(helpers, "_invoke_in_process", _counting_fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "2")
    monkeypatch.setattr(helpers.time, "sleep", lambda _s: None)

    with pytest.raises(AssertionError, match="exited 1"):
        helpers.run_cli("items", "get", "--item-id", "1")

    # S-2: exactly 3 invocations — 1 initial + 2 retries.
    assert (
        call_count[0] == 3
    ), f"Expected exactly 3 invocations (1 initial + 2 retries); got {call_count[0]}"


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


# ---------------------------------------------------------------------------
# _WaitRateLimitOrExponential (client-layer tenacity wait strategy)
# ---------------------------------------------------------------------------


def _make_retry_state(exc: BaseException | None, attempt_number: int = 1) -> Any:
    """Build a minimal fake ``RetryCallState`` carrying the given exception.

    ``_WaitRateLimitOrExponential.__call__`` reads ``retry_state.outcome`` to
    extract the exception, and delegates to ``wait_exponential`` which reads
    ``retry_state.attempt_number`` to compute the backoff.  We stub both.
    """
    from unittest.mock import MagicMock

    state = MagicMock()
    state.attempt_number = attempt_number
    if exc is None:
        state.outcome = None
    else:
        outcome = MagicMock()
        outcome.exception.return_value = exc
        state.outcome = outcome
    return state


def test_wait_uses_retry_after_when_rate_limit_error_carries_it() -> None:
    """When RateLimitError.retry_after is set, sleep = retry_after + 2s buffer."""
    from monday_cli.utils.error_handler import RateLimitError
    from monday_cli.utils.retry import _WaitRateLimitOrExponential

    wait = _WaitRateLimitOrExponential(multiplier=1.0, min_wait=1.0, max_wait=60.0)
    exc = RateLimitError(retry_after=45)
    state = _make_retry_state(exc)

    result = wait(state)

    # 45 s Retry-After + 2 s buffer
    assert result == 47.0


def test_wait_falls_back_to_exponential_when_rate_limit_has_no_retry_after() -> None:
    """When RateLimitError.retry_after is None/falsy, exponential backoff is used."""
    from monday_cli.utils.error_handler import RateLimitError
    from monday_cli.utils.retry import _WaitRateLimitOrExponential

    wait = _WaitRateLimitOrExponential(multiplier=1.0, min_wait=1.0, max_wait=60.0)
    exc = RateLimitError(retry_after=None)
    state = _make_retry_state(exc)

    # Exponential wait with attempt_number=1 returns min_wait (1s) for the first
    # attempt.  We only care that the result is a float and is NOT retry_after-based.
    result = wait(state)

    assert isinstance(result, float)
    # The exponential branch is used, so the result is min_wait (1s) or greater
    assert result >= 1.0


def test_wait_falls_back_to_exponential_for_non_rate_limit_exception() -> None:
    """For any exception that is not RateLimitError, exponential backoff is used."""
    from monday_cli.utils.retry import _WaitRateLimitOrExponential

    wait = _WaitRateLimitOrExponential(multiplier=1.0, min_wait=2.0, max_wait=60.0)
    exc = ConnectionError("network blip")
    state = _make_retry_state(exc)

    result = wait(state)

    assert isinstance(result, float)
    assert result >= 2.0


def test_wait_falls_back_to_exponential_when_outcome_is_none() -> None:
    """When retry_state.outcome is None (no exception recorded), exponential is used."""
    from monday_cli.utils.retry import _WaitRateLimitOrExponential

    wait = _WaitRateLimitOrExponential(multiplier=1.0, min_wait=3.0, max_wait=60.0)
    state = _make_retry_state(None)

    result = wait(state)

    assert isinstance(result, float)
    assert result >= 3.0


# ---------------------------------------------------------------------------
# B-1: anchored regex — digit substrings must not match
# (parametrized coverage is in test_is_rate_limit_exit / test_is_transient_server_error)
# ---------------------------------------------------------------------------


def test_rate_limit_pattern_does_not_match_embedded_429() -> None:
    """B-1: a board/item ID containing '429' must not trigger the rate-limit retry."""
    assert not helpers._is_rate_limit_exit(1, "Error: item 14290000 not found on board 18422673411")


def test_transient_pattern_does_not_match_embedded_503() -> None:
    """B-1: a board/item ID containing '503' must not trigger the transient retry."""
    assert not helpers._is_transient_server_error(1, "Error: board 18422675030 has no items")


# ---------------------------------------------------------------------------
# B-2: run_cli_streams applies the same retry loop as run_cli
# ---------------------------------------------------------------------------


def test_run_cli_streams_retries_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-2: run_cli_streams must retry on 429 exactly like run_cli."""
    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 10s", None)
    success = (0, '{"ok":true}', "", None)

    fake = _make_invoke_sequence([rate_limit, success])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    slept: list[float] = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    stdout, stderr, exit_code = helpers.run_cli_streams("items", "list", "--board-id", "123")

    assert exit_code == 0
    assert stdout == '{"ok":true}'
    assert len(slept) == 1  # slept once for the rate-limit retry


def test_run_cli_streams_retries_on_transient_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-2: run_cli_streams must retry on transient 5xx for read commands."""
    server_error = (1, "", "GraphQL errors: Internal server error", None)
    success = (0, '{"items":[]}', "", None)

    fake = _make_invoke_sequence([server_error, success])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    slept: list[float] = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    stdout, stderr, exit_code = helpers.run_cli_streams("items", "list", "--board-id", "123")

    assert exit_code == 0
    assert len(slept) == 1


def test_run_cli_streams_does_not_retry_when_expect_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-2: expect_error=True suppresses retry in run_cli_streams too."""
    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 10s", None)

    call_count = [0]

    def _fake(*_args: Any) -> tuple[int, str, str, BaseException | None]:
        call_count[0] += 1
        return rate_limit

    monkeypatch.setattr(helpers, "_invoke_in_process", _fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setattr(helpers.time, "sleep", lambda _s: None)

    stdout, stderr, exit_code = helpers.run_cli_streams(
        "items", "get", "--item-id", "1", expect_error=True
    )

    assert call_count[0] == 1
    assert exit_code == 1


# ---------------------------------------------------------------------------
# Write-safety: mutations (is_mutation=True) must NOT be retried on 5xx
# ---------------------------------------------------------------------------


def test_mutation_is_not_retried_on_transient_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write-safety: a 5xx on a mutation must surface immediately (never retried).

    A 500 on a write may have already committed server-side; retrying would
    risk double-applying the mutation (duplicate item, duplicate update, etc.).
    """
    server_error = (1, "", "GraphQL errors: Internal server error", None)

    call_count = [0]

    def _fake(*_args: Any) -> tuple[int, str, str, BaseException | None]:
        call_count[0] += 1
        return server_error

    monkeypatch.setattr(helpers, "_invoke_in_process", _fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    monkeypatch.setattr(helpers.time, "sleep", lambda _s: None)

    with pytest.raises(AssertionError):
        helpers.run_cli("items", "create", "--board-id", "123", "--name", "x", is_mutation=True)

    # Must NOT have been retried — only one invocation.
    assert call_count[0] == 1


def test_mutation_is_still_retried_on_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write-safety: 429 is still retried for mutations (request was rejected, not applied)."""
    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 5s", None)
    success = (0, '{"id":"99"}', "", None)

    fake = _make_invoke_sequence([rate_limit, success])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    slept: list[float] = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    result = helpers.run_cli(
        "items", "create", "--board-id", "123", "--name", "x", is_mutation=True
    )

    assert result == {"id": "99"}
    assert len(slept) == 1  # slept once for the 429 retry


def test_run_cli_streams_mutation_not_retried_on_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write-safety: run_cli_streams with is_mutation=True must not retry on 5xx."""
    server_error = (1, "", "GraphQL errors: Internal server error", None)

    call_count = [0]

    def _fake(*_args: Any) -> tuple[int, str, str, BaseException | None]:
        call_count[0] += 1
        return server_error

    monkeypatch.setattr(helpers, "_invoke_in_process", _fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    monkeypatch.setattr(helpers.time, "sleep", lambda _s: None)

    stdout, stderr, exit_code = helpers.run_cli_streams(
        "items",
        "create",
        "--board-id",
        "123",
        "--name",
        "x",
        expect_error=True,
        is_mutation=True,
    )

    assert call_count[0] == 1
    assert exit_code == 1


# ---------------------------------------------------------------------------
# S-1: double-retry layering — tenacity (≤3) × harness (≤7) = ≤21 calls
# ---------------------------------------------------------------------------


def test_s1_retry_layering_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """S-1: combined retries are bounded.

    Layering rationale:
    - tenacity (in MondayGraphQLClient) retries RateLimitError up to 3 times
      (DEFAULT_RETRY_MAX_ATTEMPTS).  This operates at the HTTP layer inside a
      single CLI invocation.
    - The harness (run_cli / run_cli_streams) retries a completed CLI invocation
      up to _max_retries() = 6 times (MONDAY_IT_RATELIMIT_RETRIES default).
      This operates at the process level when the CLI has already exhausted its
      own retries and exited non-zero.
    - Combined worst-case: 3 tenacity retries per invocation × (1 initial + 6
      harness retries) = 3 × 7 = 21 HTTP-level attempts per test assertion.

    This test verifies the harness layer alone is bounded at max_retries + 1.
    The tenacity layer is bounded by its own stop_after_attempt(3) and is
    tested in the client's own test suite.
    """
    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 60s", None)
    call_count = [0]

    def _counting(*_args: Any) -> tuple[int, str, str, BaseException | None]:
        call_count[0] += 1
        return rate_limit

    monkeypatch.setattr(helpers, "_invoke_in_process", _counting)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "6")
    monkeypatch.setattr(helpers.time, "sleep", lambda _s: None)

    with pytest.raises(AssertionError):
        helpers.run_cli("items", "list", "--board-id", "1")

    # Harness layer: 1 initial + 6 retries = 7 total invocations.
    assert call_count[0] == 7, f"Expected 7 harness-level invocations (1+6); got {call_count[0]}"


# ---------------------------------------------------------------------------
# S-3: retry_after=0 must be honoured, not treated as absent
# ---------------------------------------------------------------------------


def test_s3_retry_after_zero_is_honoured() -> None:
    """S-3: _parse_retry_after('... Retry after 0s') returns 0+buffer, not None."""
    result = helpers._parse_retry_after("Error: Rate limit exceeded. Retry after 0s")
    # Should be 0 + RETRY_AFTER_BUFFER, not None (which would trigger the default fallback)
    from monday_cli.constants import RETRY_AFTER_BUFFER

    assert result == RETRY_AFTER_BUFFER  # 0 + buffer


def test_s3_retry_after_zero_used_in_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """S-3: a Retry-After of 0 in stderr must produce a sleep of RETRY_AFTER_BUFFER, not
    the full default backoff."""
    from monday_cli.constants import RETRY_AFTER_BUFFER

    rate_limit = (1, "", "Error: Rate limit exceeded. Retry after 0s", None)
    success = (0, '{"ok":true}', "", None)

    fake = _make_invoke_sequence([rate_limit, success])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    slept: list[float] = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    helpers.run_cli("items", "get", "--item-id", "1")

    # Must sleep for exactly the buffer (0 + RETRY_AFTER_BUFFER), NOT the 65 s default.
    assert slept == [RETRY_AFTER_BUFFER]
    assert slept[0] != helpers._DEFAULT_RATELIMIT_BACKOFF


# ---------------------------------------------------------------------------
# S-3 (retry.py layer): _WaitRateLimitOrExponential honours retry_after=0
# ---------------------------------------------------------------------------


def test_s3_wait_strategy_honours_retry_after_zero() -> None:
    """S-3: _WaitRateLimitOrExponential must use retry_after=0 + buffer, not exponential.

    When RateLimitError.retry_after == 0, the old `if exc.retry_after:` check
    would treat it as False and fall back to exponential.  With `is not None`
    it is correctly honoured as an explicit 0.
    """
    from monday_cli.constants import RETRY_AFTER_BUFFER
    from monday_cli.utils.error_handler import RateLimitError
    from monday_cli.utils.retry import _WaitRateLimitOrExponential

    wait = _WaitRateLimitOrExponential(multiplier=2.0, min_wait=1.0, max_wait=60.0)

    # Build a minimal RetryCallState with retry_after=0
    exc = RateLimitError(retry_after=0)
    state = _make_retry_state(exc)

    result = wait(state)

    # Should be 0 + RETRY_AFTER_BUFFER, not the exponential wait (which would be ≥ 1.0)
    assert (
        result == RETRY_AFTER_BUFFER
    ), f"retry_after=0 should produce {RETRY_AFTER_BUFFER}s wait; got {result}"


# ---------------------------------------------------------------------------
# S-4: shared RETRY_AFTER_BUFFER constant keeps retry.py and helpers.py in sync
# ---------------------------------------------------------------------------


def test_s4_parse_retry_after_uses_shared_constant() -> None:
    """S-4: _parse_retry_after adds exactly RETRY_AFTER_BUFFER, not a hardcoded 2.0."""
    from monday_cli.constants import RETRY_AFTER_BUFFER

    result = helpers._parse_retry_after("Error: Rate limit exceeded. Retry after 10s")
    assert result == 10.0 + RETRY_AFTER_BUFFER


# ---------------------------------------------------------------------------
# N-1: _DEFAULT_TRANSIENT_BACKOFF is env-tunable
# ---------------------------------------------------------------------------


def test_n1_transient_backoff_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """N-1: MONDAY_IT_TRANSIENT_BACKOFF overrides the default transient backoff."""
    monkeypatch.setenv("MONDAY_IT_TRANSIENT_BACKOFF", "15.5")
    assert helpers._transient_backoff() == 15.5


def test_n1_transient_backoff_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """N-1: unset MONDAY_IT_TRANSIENT_BACKOFF falls back to _DEFAULT_TRANSIENT_BACKOFF."""
    monkeypatch.delenv("MONDAY_IT_TRANSIENT_BACKOFF", raising=False)
    assert helpers._transient_backoff() == helpers._DEFAULT_TRANSIENT_BACKOFF


def test_n1_transient_backoff_used_in_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """N-1: the env-tunable transient backoff is applied during a 5xx retry."""
    server_error = (1, "", "GraphQL errors: Internal server error", None)
    success = (0, '{"ok":true}', "", None)

    fake = _make_invoke_sequence([server_error, success])
    monkeypatch.setattr(helpers, "_invoke_in_process", fake)
    monkeypatch.delenv("MONDAY_CLI_BIN", raising=False)
    monkeypatch.setenv("MONDAY_IT_RATELIMIT_RETRIES", "3")
    monkeypatch.setenv("MONDAY_IT_TRANSIENT_BACKOFF", "7.0")
    slept: list[float] = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    helpers.run_cli("items", "list", "--board-id", "1")

    assert slept == [7.0]
