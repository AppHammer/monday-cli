"""Commands for managing Monday.com board columns (structure).

Verb commands (create/update/delete/list) are registered on columns_app by
the sibling functions below, added in the dependent issues (#86/#87/#88/#89).
"""

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import columns_app, get_client
from monday_cli.client.queries import GET_BOARD_COLUMNS
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json, secho_err

_LABELLED_TYPES = {"status", "dropdown"}


def _parse_labels(col: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse status/dropdown labels from a column's settings_str into a sorted list.

    Status columns have settings_str like: {"labels": {"0": "Done", "1": "Working on it"}}
    Dropdown columns have settings_str like: {"labels": [{"id": 1, "name": "Alpha"}, ...]}

    Returns a list of {"index": int, "label": str} sorted by index, or an empty list
    if the column type is not labelled, has no settings_str, or parsing fails.
    """
    if col.get("type") not in _LABELLED_TYPES:
        return []
    settings_str = col.get("settings_str")
    if not settings_str:
        return []
    try:
        settings = json.loads(settings_str)
    except (json.JSONDecodeError, TypeError):
        return []
    labels = settings.get("labels")
    parsed: list[dict[str, Any]] = []
    if isinstance(labels, dict):
        # status: {"0": "Done", "1": "Working on it", ...}
        for idx, label in labels.items():
            try:
                parsed.append({"index": int(idx), "label": label})
            except (TypeError, ValueError):
                continue
        parsed.sort(key=lambda x: x["index"])
    elif isinstance(labels, list):
        # dropdown (read-back): [{"id": 1, "name": "Alpha"}, ...]
        for entry in labels:
            if isinstance(entry, dict):
                parsed.append({"index": entry.get("id"), "label": entry.get("name")})
        parsed.sort(key=lambda x: (x["index"] is None, x["index"]))
    return parsed


@columns_app.command("list")
def list_columns(
    board_id: int | None = typer.Option(None, "--board-id", "-b", help="ID of the board"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table instead of JSON"),
) -> None:
    """List all columns on a board with id, title, type, and status/dropdown labels.

    Example:
        monday columns list --board-id 1234567890
        monday columns list --board-id 1234567890 --table
    """
    try:
        if board_id is None:
            secho_err(
                "Error: Board ID is required. Use --board-id",
                fg=typer.colors.RED,
            )
            secho_err(
                "Example: monday columns list --board-id 1234567890",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        client = get_client()
        result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [str(board_id)]})
        boards = result.get("boards", [])
        if not boards:
            secho_err(
                f"Board {board_id} not found or you don't have access",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        board = boards[0]
        board_name = board.get("name", "Unknown")
        raw_columns = board.get("columns", [])

        columns: list[dict[str, Any]] = []
        for col in raw_columns:
            entry: dict[str, Any] = {
                "column_id": col.get("id"),
                "title": col.get("title"),
                "type": col.get("type"),
            }
            labels = _parse_labels(col)
            if labels:
                entry["labels"] = labels
            columns.append(entry)

        if table:
            console = Console()
            rich_table = Table(title=f"Columns on '{board_name}' (Total: {len(columns)})")
            rich_table.add_column("Column ID", style="cyan", no_wrap=True)
            rich_table.add_column("Title", style="green")
            rich_table.add_column("Type", style="yellow")
            rich_table.add_column("Labels", style="magenta")
            for col in columns:
                labels_str = ", ".join(str(lbl["label"]) for lbl in col.get("labels", []))
                rich_table.add_row(
                    col["column_id"] or "",
                    col["title"] or "",
                    col["type"] or "",
                    labels_str,
                )
            console.print(rich_table)
            typer.secho(f"\nTotal columns: {len(columns)}", fg=typer.colors.BLUE)
        else:
            print_json(
                {
                    "board_id": str(board_id),
                    "board_name": board_name,
                    "columns": columns,
                    "total_count": len(columns),
                }
            )

    except AuthenticationError:
        secho_err(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        secho_err(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        secho_err(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        secho_err(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
