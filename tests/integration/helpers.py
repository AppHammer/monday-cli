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
import subprocess
import time
import traceback
from collections.abc import Callable
from typing import Any

from typer.testing import CliRunner

from monday_cli.cli import app

# CliRunner already separates stdout and stderr by default in typer 0.27+ / click 8.4+;
# result.stderr is populated independently of result.output so tests can assert each stream.
_runner = CliRunner()


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


def run_cli(
    *args: str,
    raw: bool = False,
    expect_error: bool = False,
    capture_stderr: bool = False,
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
    binary = os.environ.get("MONDAY_CLI_BIN")
    if binary:
        exit_code, stdout, stderr, exception = _invoke_binary(binary, args)
    else:
        exit_code, stdout, stderr, exception = _invoke_in_process(args)

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


def run_cli_streams(*args: str, expect_error: bool = False) -> tuple[str, str, int]:
    """Invoke the CLI and return ``(stdout, stderr, exit_code)`` as raw strings.

    Convenience wrapper for tests that need full low-level access to both
    streams and the exit code, without any JSON parsing or assertion.  The
    clean-stdout contract can be verified by the caller via ``json.loads``.

    Args:
        *args: CLI arguments.
        expect_error: Suppress the exit-code assertion.  Always returns the
            raw streams regardless of exit code.

    Returns:
        ``(stdout_str, stderr_str, exit_code)``
    """
    binary = os.environ.get("MONDAY_CLI_BIN")
    if binary:
        exit_code, stdout, stderr, _ = _invoke_binary(binary, args)
    else:
        exit_code, stdout, stderr, _ = _invoke_in_process(args)
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
