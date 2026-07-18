"""In-process (or subprocess) CLI invocation helper for integration tests.

`run_cli()` is the single entry point every integration suite uses to talk to
the `monday` CLI. By default it drives the Typer `app` in-process via
`typer.testing.CliRunner` -- fast, and requires no build step. Setting the
`MONDAY_CLI_BIN` environment variable to a path (e.g. `dist/monday`) switches
it to exec the packaged binary instead, via subprocess, so CI can optionally
validate the standalone build exercises the same contract.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from typer.testing import CliRunner

from monday_cli.cli import app

_runner = CliRunner()


class CliOutputError(AssertionError):
    """Raised when a CLI invocation's output doesn't match the expected shape."""


def _extract_json(stdout: str) -> Any:
    """Pull the JSON payload out of a command's captured stdout.

    Most commands print JSON as their only output, so the fast path is a
    straight `json.loads`. A few commands (`docs put`/`append`, `groups
    create`, etc.) print a human "✓ ..." line via `typer.secho` BEFORE the
    JSON payload -- both land on stdout (nothing in this codebase passes
    `err=True` to secho), so as a fallback we scan for the line where the
    JSON object/array begins and parse from there.
    """
    stripped = stdout.strip()
    if not stripped:
        raise CliOutputError("CLI produced no output to parse as JSON")

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    lines = stdout.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() in ("{", "["):
            candidate = "\n".join(lines[idx:])
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    raise CliOutputError(f"Could not locate a JSON payload in CLI output:\n{stdout}")


def _invoke_in_process(args: tuple[str, ...]) -> tuple[int, str]:
    result = _runner.invoke(app, list(args))
    return result.exit_code, result.stdout


def _invoke_binary(binary: str, args: tuple[str, ...]) -> tuple[int, str]:
    completed = subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    return completed.returncode, completed.stdout


def run_cli(*args: str, raw: bool = False, expect_error: bool = False) -> Any:
    """Invoke the `monday` CLI and return its output.

    Args:
        *args: CLI arguments, e.g. `run_cli("items", "get", "--item-id", "123")`.
        raw: Return raw stdout text instead of parsed JSON. Required for
            `docs get`, which emits raw Markdown via `typer.echo`, not JSON.
        expect_error: Don't assert a zero exit code. Use this to exercise a
            command's error path, or for idempotent teardown of an artifact
            that may already be deleted.

    Returns:
        Parsed JSON (dict/list) by default, or raw stdout text if `raw=True`
        or if the command exited non-zero under `expect_error=True` (there is
        usually no JSON payload to parse on an error path).

    Raises:
        AssertionError: If `expect_error` is False and the CLI exits non-zero,
            or if JSON parsing is required but no JSON payload is found.
    """
    binary = os.environ.get("MONDAY_CLI_BIN")
    if binary:
        exit_code, stdout = _invoke_binary(binary, args)
    else:
        exit_code, stdout = _invoke_in_process(args)

    if not expect_error:
        assert (
            exit_code == 0
        ), f"monday {' '.join(args)} exited {exit_code}, expected 0.\nOutput:\n{stdout}"
    elif exit_code != 0:
        # Error paths in this CLI print human messages, not JSON -- nothing
        # to parse, so hand back the raw text regardless of `raw`.
        return stdout

    if raw:
        return stdout

    return _extract_json(stdout)
