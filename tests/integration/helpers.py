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
import traceback
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
