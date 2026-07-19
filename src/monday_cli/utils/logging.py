"""Logging configuration for Monday CLI."""

import logging

from rich.console import Console
from rich.logging import RichHandler


def setup_logging(verbose: bool = False, debug: bool = False) -> logging.Logger:
    """Configure logging with rich output.

    All log output is directed to stderr so that stdout remains clean JSON
    (FR-0008 contract).  Without this, tenacity's before_sleep_log WARNING
    messages can leak onto stdout and break the JSON parser in integration tests.

    Args:
        verbose: Enable INFO level logging
        debug: Enable DEBUG level logging

    Returns:
        Configured logger instance
    """
    # Determine log level
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING

    # Route ALL log output to stderr.  The RichHandler uses a Console for
    # rendering; by default Console targets stdout, which would contaminate the
    # clean-JSON stdout contract required by FR-0008.  Passing stderr=True
    # ensures every WARNING / ERROR / DEBUG line lands on stderr.
    stderr_console = Console(stderr=True)

    # Configure root logger
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=stderr_console,
                rich_tracebacks=True,
                show_time=True,
                show_path=debug,
                markup=True,
                tracebacks_show_locals=debug,
            )
        ],
        force=True,
    )

    # Get logger for this application
    logger = logging.getLogger("monday_cli")
    logger.setLevel(level)

    # Suppress httpx logging unless debug mode
    if not debug:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name (defaults to 'monday_cli')

    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f"monday_cli.{name}")
    return logging.getLogger("monday_cli")
