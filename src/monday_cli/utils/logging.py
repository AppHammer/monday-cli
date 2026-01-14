"""Logging configuration for Monday CLI."""

import logging

from rich.logging import RichHandler


def setup_logging(verbose: bool = False, debug: bool = False) -> logging.Logger:
    """Configure logging with rich output.

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

    # Configure root logger
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
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
