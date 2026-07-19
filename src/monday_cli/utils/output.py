"""Output formatting utilities for Monday CLI.

Stdout/stderr contract (FR-0008, v0.6.2+):
  - ``print_json`` is the ONLY writer to stdout.  In default (JSON) mode every
    command emits a single JSON document on stdout and nothing else.
  - All progress, tips, warnings, confirmations, and error prose go to stderr
    via ``secho_err`` (or the lower-level ``eprint``).
  - The ``--table`` flag is a human-convenience layer and is exempt from this
    contract; its Rich output and summary lines go to stdout as before.

A drift-guard test (tests/unit/test_stdout_contract.py) enforces this
invariant: any command module that accidentally calls ``typer.secho`` /
``typer.echo`` / ``print`` without routing to stderr will fail the guard.
"""

import json
from typing import Any

import typer

# ---------------------------------------------------------------------------
# Stdout writer (JSON data only)
# ---------------------------------------------------------------------------


def format_json(data: Any, indent: int = 2) -> str:
    """Format data as JSON string.

    Args:
        data: Data to format
        indent: Number of spaces for indentation

    Returns:
        Formatted JSON string
    """
    return json.dumps(data, indent=indent, ensure_ascii=False)


def print_json(data: Any, indent: int = 2) -> None:
    """Print data as formatted JSON to stdout.

    This is the ONLY function that writes to stdout in default (JSON) mode.
    All human/diagnostic text must use ``secho_err`` or ``eprint`` instead.

    Args:
        data: Data to print
        indent: Number of spaces for indentation
    """
    print(format_json(data, indent=indent))


# ---------------------------------------------------------------------------
# Stderr writers (diagnostics, progress, tips, warnings, errors)
# ---------------------------------------------------------------------------


def secho_err(message: str, fg: str | None = None, bold: bool = False) -> None:
    """Write a diagnostic/human message to stderr.

    Drop-in companion to ``typer.secho`` that forces ``err=True`` so the
    message never contaminates stdout.  Colour semantics are preserved:
      - Green  (``typer.colors.GREEN``) — success confirmation (✓ …)
      - Yellow (``typer.colors.YELLOW``) — warnings, not-found notices
      - Red    (``typer.colors.RED``)    — error messages
      - Blue   (``typer.colors.BLUE``)  — tips / examples / progress

    Args:
        message: Text to print to stderr.
        fg: Optional foreground colour (e.g. ``typer.colors.RED``).
        bold: Whether to use bold text.
    """
    typer.secho(message, fg=fg, bold=bold, err=True)


def eprint(message: str) -> None:
    """Write a plain (uncoloured) message to stderr.

    Lightweight alternative to ``secho_err`` when colour is not needed.

    Args:
        message: Text to print to stderr.
    """
    typer.echo(message, err=True)
