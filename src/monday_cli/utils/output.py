"""Output formatting utilities for Monday CLI."""

import json
from typing import Any


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
    """Print data as formatted JSON.

    Args:
        data: Data to print
        indent: Number of spaces for indentation
    """
    print(format_json(data, indent=indent))
