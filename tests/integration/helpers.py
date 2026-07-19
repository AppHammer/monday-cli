"""In-process (or subprocess) CLI invocation helper for integration tests.

`run_cli()` is the single entry point every integration suite uses to talk to
the `monday` CLI. By default it drives the Typer `app` in-process via
`typer.testing.CliRunner` -- fast, and requires no build step. Setting the
`MONDAY_CLI_BIN` environment variable to a path (e.g. `dist/monday`) switches
it to exec the packaged binary instead, via subprocess, so CI can optionally
validate the standalone build exercises the same contract.

FR-0008 harness upgrade: ``run_cli`` now captures stderr separately (via
``result.stderr`` for the in-process runner and ``completed.stderr`` for
the subprocess path). The strict-JSON mode is enforced by ``_extract_json``:
it requires the **entire** stdout to parse as JSON — the old line-scanning
fallback (which silently tolerated contamination) is removed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import traceback
from collections.abc import Callable
from typing import Any

from typer.testing import CliRunner

from monday_cli.cli import app
from monday_cli.constants import RETRY_AFTER_BUFFER

# CliRunner already separates stdout and stderr by default in typer 0.27+ / click 8.4+;
# result.stderr is populated independently of result.output so tests can assert each stream.
_runner = CliRunner()

# ---------------------------------------------------------------------------
# Rate-limit detection (FR-0016)
# ---------------------------------------------------------------------------
# When the CLI exits non-zero due to a 429 / rate-limit, the error message
# lands on stderr.  We detect that case by pattern-matching stderr so we can
# retry the entire invocation instead of counting it as a test failure.

_RATE_LIMIT_PATTERNS = re.compile(
    # \b429\b / \b503\b: word boundaries prevent false matches on board IDs or
    # item IDs that happen to contain these digit sequences (e.g. an item whose
    # name includes "1429" or "5030").  The textual alternatives (rate.?limit,
    # too many requests, retry.?after) are already phrase-only and need no
    # anchoring.
    r"rate.?limit|retry.?after|\b429\b|too many requests",
    re.IGNORECASE,
)

# Transient Monday.com server-side errors that are safe to retry at the
# harness level.  These are distinct from rate-limit (429) responses: they
# are internal server errors (5xx-class) returned as GraphQL error payloads
# that the CLI propagates as a non-zero exit.  A short fixed backoff (5 s)
# is sufficient because these errors usually clear within seconds.
# \b503\b: same word-boundary rationale as \b429\b above.
_TRANSIENT_SERVER_ERROR_PATTERNS = re.compile(
    r"internal server error|\b503\b|service unavailable|temporarily unavailable",
    re.IGNORECASE,
)
_DEFAULT_TRANSIENT_BACKOFF = 5.0  # seconds — enough for a Monday 500 to clear

# How many times run_cli will transparently retry a rate-limited invocation
# before giving up and surfacing the failure.  Tunable via env var so CI can
# increase headroom without touching code.
_DEFAULT_RATELIMIT_RETRIES = 6
_DEFAULT_RATELIMIT_BACKOFF = 65.0  # seconds — just over 1 full 60-s window


def _env_int(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back on any bad value."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    """Read a non-negative float from the environment, falling back on any bad value."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _max_retries() -> int:
    """Max transparent retries shared across all transient-failure categories.

    The same counter budget covers both rate-limit (429) and transient server
    error (5xx) retries, so the total number of extra attempts is bounded by
    this value regardless of which error type is encountered.  Controlled by
    ``MONDAY_IT_RATELIMIT_RETRIES``.
    """
    return _env_int("MONDAY_IT_RATELIMIT_RETRIES", _DEFAULT_RATELIMIT_RETRIES)


def _ratelimit_backoff() -> float:
    """Base backoff (seconds) between rate-limit retries.

    Controlled by ``MONDAY_IT_RATELIMIT_BACKOFF``.  We default to 65 s because
    Monday's 429 ``Retry-After`` is typically 60 s; a small buffer helps.
    """
    return _env_float("MONDAY_IT_RATELIMIT_BACKOFF", _DEFAULT_RATELIMIT_BACKOFF)


def _transient_backoff() -> float:
    """Backoff (seconds) between transient-server-error retries.

    Controlled by ``MONDAY_IT_TRANSIENT_BACKOFF`` so CI can extend the window
    without touching code, consistent with the other timing constants.
    """
    return _env_float("MONDAY_IT_TRANSIENT_BACKOFF", _DEFAULT_TRANSIENT_BACKOFF)


def _is_rate_limit_exit(exit_code: int, stderr: str) -> bool:
    """Return True when a CLI invocation failed due to throttling."""
    return exit_code != 0 and bool(_RATE_LIMIT_PATTERNS.search(stderr))


def _is_transient_server_error(exit_code: int, stderr: str) -> bool:
    """Return True when a CLI invocation failed due to a transient Monday server error."""
    return exit_code != 0 and bool(_TRANSIENT_SERVER_ERROR_PATTERNS.search(stderr))


def _parse_retry_after(stderr: str) -> float | None:
    """Extract the Retry-After value (seconds) from a rate-limit stderr message.

    Returns None when the value cannot be found; callers fall back to the
    configured default backoff.
    """
    match = re.search(r"retry.?after\s+(\d+)\s*s", stderr, re.IGNORECASE)
    if match:
        # RETRY_AFTER_BUFFER is shared with _WaitRateLimitOrExponential in
        # retry.py so both layers always add the same safety margin.
        return float(match.group(1)) + RETRY_AFTER_BUFFER
    return None


class CliOutputError(AssertionError):
    """Raised when a CLI invocation's output doesn't match the expected shape."""


def _extract_json(stdout: str) -> Any:
    """Require the full stdout to be a single valid JSON document.

    FR-0008 contract: stdout must contain ONLY the JSON payload — no leading
    or trailing prose.  Any contamination (a ``secho`` that missed ``err=True``,
    a stray ``print``) causes this to raise ``CliOutputError`` immediately so
    the regression guard surfaces the violation instead of silently parsing
    around it.

    The old line-scanning fallback (``for idx, line in enumerate(lines)``) that
    tolerated contamination has been removed.
    """
    stripped = stdout.strip()
    if not stripped:
        raise CliOutputError("CLI produced no output to parse as JSON")

    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise CliOutputError(
            f"stdout is not clean JSON (FR-0008 contract violation).\n"
            f"Parse error: {exc}\n"
            f"stdout was:\n{stdout}"
        ) from exc


def _invoke_in_process(
    args: tuple[str, ...],
) -> tuple[int, str, str, BaseException | None]:
    result = _runner.invoke(app, list(args))
    stderr = result.stderr if hasattr(result, "stderr") else ""
    return result.exit_code, result.stdout, stderr, result.exception


def _invoke_binary(
    binary: str, args: tuple[str, ...]
) -> tuple[int, str, str, BaseException | None]:
    completed = subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    return completed.returncode, completed.stdout, completed.stderr, None


def _format_exception(exc: BaseException) -> str:
    """Render a CliRunner-captured exception (with traceback, if any) for a failure message."""
    if exc.__traceback__ is not None:
        formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return f"\n{formatted}"
    return f" {exc!r}"


def _invoke_with_retry(
    args: tuple[str, ...],
    expect_error: bool,
    is_mutation: bool = False,
) -> tuple[int, str, str, BaseException | None]:
    """Shared retry loop for both ``run_cli`` and ``run_cli_streams``.

    FR-0016: transparently retry the entire CLI invocation when Monday
    throttles us (429).  A throttled invocation is NOT a test failure — it is
    a transient infrastructure condition.  We retry up to
    ``_max_retries()`` times, sleeping for the Retry-After value that the
    CLI already extracted from the response header (visible in stderr) before
    falling through to the normal assertion path on the final attempt.

    Centralising the loop here means both ``run_cli`` (B-2 fix) and
    ``run_cli_streams`` share identical retry semantics; previously only
    ``run_cli`` had retry logic, leaving ``run_cli_streams`` callers exposed to
    flakiness caused by 429s.

    When ``expect_error=True`` the caller explicitly wants a non-zero exit, so
    we do NOT transparently retry — that would hide a real failure from the
    caller who is asserting against the error output.

    Write-safety (reviewer opinion b): 429 is ALWAYS safe to retry for any
    call — a 429 means the request was rejected before it was applied.
    5xx / transient-server errors are NOT retried for mutations (``is_mutation=True``)
    because a 500 on a write may have committed server-side; retrying would
    double-apply the mutation (e.g. creating a duplicate item or update).
    Callers that invoke write commands (create / update / delete / append /
    move) must pass ``is_mutation=True`` to opt out of 5xx retry.
    Read-only / idempotent commands (list / get) may leave ``is_mutation``
    at its default (False) to benefit from 5xx retry.

    Returns:
        ``(exit_code, stdout, stderr, exception)`` from the final attempt.
    """
    max_retries = _max_retries()
    default_backoff = _ratelimit_backoff()
    binary = os.environ.get("MONDAY_CLI_BIN")
    attempt = 0
    while True:
        if binary:
            exit_code, stdout, stderr, exception = _invoke_binary(binary, args)
        else:
            exit_code, stdout, stderr, exception = _invoke_in_process(args)

        if not expect_error and attempt < max_retries:
            if _is_rate_limit_exit(exit_code, stderr):
                # 429 = request was rejected, never applied → safe for all calls.
                backoff = _parse_retry_after(stderr) or default_backoff
                attempt += 1
                time.sleep(backoff)
                continue
            if not is_mutation and _is_transient_server_error(exit_code, stderr):
                # 5xx retry only for reads/idempotent calls.  Mutations opt out
                # (is_mutation=True) because a 500 may mean the write already
                # committed; retrying would risk double-applying the change.
                attempt += 1
                time.sleep(_transient_backoff())
                continue

        break

    return exit_code, stdout, stderr, exception


def run_cli(
    *args: str,
    raw: bool = False,
    expect_error: bool = False,
    capture_stderr: bool = False,
    is_mutation: bool = False,
) -> Any:
    """Invoke the `monday` CLI and return its output.

    Args:
        *args: CLI arguments, e.g. ``run_cli("items", "get", "--item-id", "123")``.
        raw: Return raw stdout text instead of parsed JSON.  Use for commands
            that emit non-JSON to stdout by design (e.g. ``docs get --raw``).
        expect_error: Don't assert a zero exit code.  Use this to exercise a
            command's error path, or for idempotent teardown of an artifact
            that may already be deleted.
        capture_stderr: When True, return a ``(result, stderr)`` tuple so the
            caller can also assert what appeared on stderr.  When False (the
            default), only the stdout result is returned — existing callers are
            unaffected.
        is_mutation: When True, disables the transient-5xx retry so write
            commands (create / update / delete / append / move) are never
            silently retried on a 500/503 that may have already committed
            server-side.  The 429 retry is unaffected (always safe).
            Defaults to False (read-only / idempotent behaviour).

    Returns:
        By default: parsed JSON (dict/list), raw stdout str (if ``raw=True``),
        or raw stdout str (if ``expect_error=True`` and exit was non-zero).
        When ``capture_stderr=True``: a ``(result, stderr_str)`` tuple where
        ``result`` follows the same rules above and ``stderr_str`` is the full
        captured stderr text.

    Raises:
        AssertionError: If ``expect_error`` is False and the CLI exits non-zero,
            or if JSON parsing is required but stdout is not clean JSON.
    """
    exit_code, stdout, stderr, exception = _invoke_with_retry(args, expect_error, is_mutation)

    if not expect_error:
        exception_detail = f"\nException:{_format_exception(exception)}" if exception else ""
        assert exit_code == 0, (
            f"monday {' '.join(args)} exited {exit_code}, expected 0.\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
            f"{exception_detail}"
        )
    elif exit_code != 0:
        # Error paths in this CLI print human messages to stderr, not JSON on
        # stdout -- hand back the raw stdout (empty or JSON) and stderr is
        # accessible via capture_stderr=True.
        result: Any = stdout
        if capture_stderr:
            return result, stderr
        return result

    if raw:
        result = stdout
    else:
        result = _extract_json(stdout)

    if capture_stderr:
        return result, stderr
    return result


def run_cli_streams(
    *args: str,
    expect_error: bool = False,
    is_mutation: bool = False,
) -> tuple[str, str, int]:
    """Invoke the CLI and return ``(stdout, stderr, exit_code)`` as raw strings.

    Convenience wrapper for tests that need full low-level access to both
    streams and the exit code, without any JSON parsing or assertion.  The
    clean-stdout contract can be verified by the caller via ``json.loads``.

    FR-0016 (B-2 fix): applies the same transparent 429/503 retry loop as
    ``run_cli`` via the shared ``_invoke_with_retry`` helper.  Previously this
    function bypassed the retry loop, leaving all callers (``test_stdout_
    contract_fr0008.py`` and others) exposed to flakiness when Monday.com
    throttles a test run.

    Args:
        *args: CLI arguments.
        expect_error: Suppress the exit-code assertion.  Always returns the
            raw streams regardless of exit code.
        is_mutation: When True, disables the transient-5xx retry for write
            commands.  Same semantics as ``run_cli``'s ``is_mutation`` flag.
            Defaults to False.

    Returns:
        ``(stdout_str, stderr_str, exit_code)``
    """
    exit_code, stdout, stderr, _ = _invoke_with_retry(args, expect_error, is_mutation)
    return stdout, stderr, exit_code


# --- Bounded read-after-mutate poll (FR-0013 #69) ---------------------------
#
# Monday.com's board `items_page` is eventually consistent: an item that was
# just created / updated / moved / deleted can briefly lag behind on a
# subsequent `items list` (or `items get`) read. Every read-after-mutate
# assertion in the integration suite must therefore be a BOUNDED POLL, not a
# single shot. This one helper supersedes the three near-identical private
# copies that previously lived in test_items.py (`_run_cli_until`),
# test_items_move.py (`_run_cli_until`) and test_items_status.py
# (`_list_until_present`) — consolidating them so every read-after-mutate path
# shares one CI-tuned implementation (FR-0013 AC-4).

_DEFAULT_POLL_ATTEMPTS = 6
_DEFAULT_POLL_DELAY = 1.5


def poll_attempts() -> int:
    """How many times a bounded poll should read before giving up.

    Resolved from ``MONDAY_IT_POLL_ATTEMPTS`` so CI (where the shared board is
    under more contention/consistency lag) can raise it without touching code,
    while local runs stay snappy on the default.
    """
    return _env_int("MONDAY_IT_POLL_ATTEMPTS", _DEFAULT_POLL_ATTEMPTS)


def poll_delay() -> float:
    """Seconds to back off between bounded-poll attempts.

    Resolved from ``MONDAY_IT_POLL_DELAY`` (see :func:`poll_attempts`).
    """
    return _env_float("MONDAY_IT_POLL_DELAY", _DEFAULT_POLL_DELAY)


def run_cli_until(
    predicate: Callable[[Any], bool],
    *args: str,
    attempts: int | None = None,
    delay: float | None = None,
    **kwargs: Any,
) -> Any:
    """Invoke ``run_cli(*args, **kwargs)`` repeatedly until ``predicate`` holds.

    A freshly created/updated/moved/deleted artifact can briefly lag behind on
    the board's `items_page` read (eventual consistency), so a read right after
    a mutation needs a bounded poll rather than a single shot.

    Args:
        predicate: Called with each ``run_cli`` result; polling stops and the
            result is returned as soon as it returns truthy.
        *args: Forwarded to :func:`run_cli`.
        attempts: Max reads before giving up. Defaults to :func:`poll_attempts`
            (env-tunable via ``MONDAY_IT_POLL_ATTEMPTS``).
        delay: Backoff between attempts. Defaults to :func:`poll_delay`
            (env-tunable via ``MONDAY_IT_POLL_DELAY``).
        **kwargs: Forwarded to :func:`run_cli` (e.g. ``raw=True``).

    Returns:
        The last ``run_cli`` result — the first one that satisfied
        ``predicate``, or (on give-up) the final attempt's result, so the
        caller's own assertions can produce a meaningful failure message.
    """
    attempts = poll_attempts() if attempts is None else attempts
    delay = poll_delay() if delay is None else delay

    result: Any = None
    for attempt in range(attempts):
        result = run_cli(*args, **kwargs)
        if predicate(result):
            return result
        if attempt < attempts - 1:
            time.sleep(delay)
    return result


def run_cli_until_item_present(
    item_id: str,
    *args: str,
    attempts: int | None = None,
    delay: float | None = None,
    **kwargs: Any,
) -> Any:
    """Poll a filtered ``items list`` until ``item_id`` appears among its items.

    Thin convenience over :func:`run_cli_until` for the most common
    read-after-mutate case (supersedes the old ``_list_until_present``): run
    ``items list ...`` a few times until the just-created/updated item shows up.
    """
    return run_cli_until(
        lambda data: isinstance(data, dict)
        and str(item_id) in [str(i["id"]) for i in data.get("items", [])],
        *args,
        attempts=attempts,
        delay=delay,
        **kwargs,
    )
