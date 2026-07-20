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
from monday_cli.client.mutations import (
    CHANGE_COLUMN_TITLE,
    CHANGE_COLUMN_VALUE_CREATE_LABELS,
    CREATE_COLUMN,
    DELETE_COLUMN,
)
from monday_cli.client.queries import GET_BOARD_COLUMNS, GET_BOARD_FIRST_ITEM
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json, secho_err

_LABELLED_TYPES = {"status", "dropdown"}

# Supported column types for `columns create`. Exotic/formula types are out of
# scope per FRD (mirror, formula, connect_boards, dependency, time_tracking).
_SUPPORTED_TYPES = {
    "status",
    "dropdown",
    "text",
    "long_text",
    "numbers",
    "date",
    "people",
    "link",
    "doc",
    "checkbox",
}


def _apply_label_changes(
    client: Any,
    board_id: int,
    column_id: str,
    target_col: dict[str, Any],
    add_labels: list[str],
    rename_labels: list[str],
) -> dict[str, Any]:
    """Apply label changes (add / rename) to a status or dropdown column.

    Returns a summary dict describing what was applied. Raises MondayAPIError,
    typer.Exit (teaching errors), or any client exception to the caller.

    add_labels:
        For each label, fetch a board item and call CHANGE_COLUMN_VALUE_CREATE_LABELS
        with create_labels_if_missing:true. Requires a board item to exist (teaching
        error if none).

    rename_labels:
        Parse each entry as "old=new". Resolve "old" in the column's current label
        set. The Monday API does NOT expose a public index-preserving rename path
        (change_column_metadata only accepts title/description; change_column_value
        only ADDS labels, not renames them). This function raises a MondayAPIError
        with a clear message after validation so the caller surfaces a teaching error
        rather than silently no-op. See .genesis/VERIFIED_FINDINGS.md for details.
    """
    applied: dict[str, Any] = {}

    # --- parse and validate rename_label entries first (fast, no API) -------
    parsed_renames: list[tuple[str, str]] = []
    for entry in rename_labels:
        if "=" not in entry:
            secho_err(
                f"Error: --rename-label '{entry}' is not in 'old=new' format.",
                fg=typer.colors.RED,
            )
            secho_err(
                "Example: --rename-label 'Stuck=Blocked'",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)
        old_label, _, new_label = entry.partition("=")
        parsed_renames.append((old_label.strip(), new_label.strip()))

    # --- resolve current labels for rename validation -----------------------
    if parsed_renames:
        current_labels = _parse_labels(target_col)
        label_texts = [lbl["label"] for lbl in current_labels]
        for old_label, new_label in parsed_renames:
            matching = [lbl for lbl in current_labels if lbl["label"] == old_label]
            if not matching:
                secho_err(
                    f"Error: Label '{old_label}' not found in column '{column_id}'.",
                    fg=typer.colors.RED,
                )
                secho_err(
                    f"Current labels: {', '.join(label_texts) or '(none)'}",
                    fg=typer.colors.BLUE,
                )
                raise typer.Exit(1)

        # The Monday.com public API does not expose an index-preserving label
        # rename path. change_column_metadata only accepts title/description
        # (ColumnProperty enum). change_column_value with create_labels_if_missing
        # only ADDS labels, not renames them (verified live — VERIFIED_FINDINGS.md).
        # Rather than silently no-op, surface a clear teaching error so the caller
        # knows the limitation and can work around it (delete + re-add the label
        # via the Monday.com UI, or recreate the column).
        raise MondayAPIError(
            "Rename-label is not supported: the Monday.com public API does not expose "
            "an index-preserving label rename path. "
            "To rename a label, use the Monday.com web UI. "
            "Tip: create a new column with the desired labels or update them via the web UI."
        )

    # --- add labels ----------------------------------------------------------
    if add_labels:
        # Fetch a board item to write to (required by change_column_value).
        item_result = client.execute_query(GET_BOARD_FIRST_ITEM, {"boardIds": [str(board_id)]})
        boards = item_result.get("boards", [])
        item_id: str | None = None
        if boards:
            items_page = boards[0].get("items_page", {})
            items = items_page.get("items", [])
            if items:
                item_id = str(items[0]["id"])

        if item_id is None:
            secho_err(
                f"Error: Board {board_id} has no items. --add-label requires at least one "
                "board item to write to (Monday API limitation). "
                "Create an item on the board first, then retry.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        labels_added: list[str] = []
        for label_text in add_labels:
            client.execute_mutation(
                CHANGE_COLUMN_VALUE_CREATE_LABELS,
                {
                    "boardId": str(board_id),
                    "itemId": item_id,
                    "columnId": column_id,
                    "value": json.dumps({"label": label_text}),
                },
            )
            labels_added.append(label_text)

        applied["labels_added"] = labels_added

    return applied


def _build_defaults(column_type: str, labels: list[str]) -> str | None:
    """Build the ``defaults`` JSON string for status/dropdown label seeding.

    Returns a JSON string suitable for the Monday ``create_column`` mutation's
    ``defaults`` argument, or ``None`` when the type does not support labels or
    no labels were supplied.

    Shapes are VERIFIED live (see .genesis/VERIFIED_FINDINGS.md):

    - status:   ``{"labels": {"1": "A", "2": "B"}}``  (index→label map, start at 1)
    - dropdown: ``{"settings": {"labels": [{"id": 1, "label": "A"}, ...]}}``
                (nested under "settings", write-key is "label"; read-back uses "name")
    """
    if not labels:
        return None
    if column_type == "status":
        return json.dumps({"labels": {str(i): name for i, name in enumerate(labels, start=1)}})
    if column_type == "dropdown":
        return json.dumps(
            {
                "settings": {
                    "labels": [{"id": i, "label": name} for i, name in enumerate(labels, start=1)]
                }
            }
        )
    return None  # caller handles AC4 (labels on unsupported type)


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


@columns_app.command("update")
def update_column(
    board_id: int = typer.Option(..., "--board-id", "-b", help="ID of the board"),
    column_id: str = typer.Option(..., "--column-id", "-c", help="ID of the column to update"),
    title: str | None = typer.Option(None, "--title", "-t", help="New column title"),
    add_label: list[str] = typer.Option(
        [], "--add-label", help="Label to add (repeatable; status/dropdown columns only)"
    ),
    rename_label: list[str] = typer.Option(
        [], "--rename-label", help="'old=new' rename (repeatable; status/dropdown only)"
    ),
) -> None:
    """Rename a column and/or add/rename its status/dropdown labels.

    At least one of --title, --add-label, or --rename-label must be provided.
    --add-label and --rename-label only apply to status and dropdown columns.

    Example:
        monday columns update -b 123 -c status --title "State"
        monday columns update -b 123 -c status --add-label "Blocked"
        monday columns update -b 123 -c status --rename-label "Stuck=Blocked"
    """
    try:
        if not title and not add_label and not rename_label:
            secho_err(
                "Error: Nothing to update. Pass --title, --add-label, or --rename-label.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        client = get_client()

        # Resolve the column + its type/current labels from the board schema.
        board_result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [str(board_id)]})
        boards = board_result.get("boards", [])
        if not boards:
            secho_err(
                f"Board {board_id} not found or you don't have access",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        columns = boards[0].get("columns", [])
        target = next((c for c in columns if c.get("id") == column_id), None)
        if target is None:
            secho_err(
                f"Column '{column_id}' not found on board {board_id}.",
                fg=typer.colors.YELLOW,
            )
            secho_err(
                f"Tip: run 'monday columns list --board-id {board_id}' to see column ids.",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        col_type = target.get("type")
        if (add_label or rename_label) and col_type not in _LABELLED_TYPES:
            secho_err(
                f"Error: --add-label/--rename-label apply only to status/dropdown columns "
                f"(this column is type '{col_type}').",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        applied: dict[str, Any] = {"column_id": column_id, "board_id": str(board_id)}

        # 1) Title change.
        if title:
            client.execute_mutation(
                CHANGE_COLUMN_TITLE,
                {"boardId": str(board_id), "columnId": column_id, "title": title},
            )
            applied["title"] = title

        # 2) Label add / rename.
        if add_label or rename_label:
            applied["labels_changed"] = _apply_label_changes(
                client,
                board_id,
                column_id,
                target,
                list(add_label),
                list(rename_label),
            )

        secho_err("✓ Column updated successfully!", fg=typer.colors.GREEN)
        print_json(applied)

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


@columns_app.command("create")
def create_column(
    board_id: int = typer.Option(..., "--board-id", "-b", help="ID of the board"),
    title: str = typer.Option(..., "--title", "-t", help="Title of the new column"),
    column_type: str = typer.Option(
        ..., "--type", help="Monday column type (e.g. status, dropdown, text)"
    ),
    labels: str | None = typer.Option(
        None, "--labels", help="Comma-separated labels for status/dropdown columns"
    ),
    column_id: str | None = typer.Option(
        None, "--column-id", help="Custom column id (1-20 chars, a-z/_; must be unique on board)"
    ),
    description: str | None = typer.Option(None, "--description", help="Column description"),
) -> None:
    """Create a board column of a given type, optionally seeding status/dropdown labels.

    Supported types: checkbox, date, doc, dropdown, link, long_text, numbers,
    people, status, text.

    Labels (--labels) are only accepted for status and dropdown columns. Passing
    --labels with any other type is a teaching error (exit 1, no API call).

    Example:
        monday columns create --board-id 123 --title Priority --type status --labels "Low,High"
        monday columns create --board-id 123 --title Notes --type text
    """
    try:
        column_type = column_type.strip().lower()
        if column_type not in _SUPPORTED_TYPES:
            secho_err(
                f"Error: Unsupported column type '{column_type}'.",
                fg=typer.colors.RED,
            )
            secho_err(
                f"Supported types: {', '.join(sorted(_SUPPORTED_TYPES))}",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        label_list = [s.strip() for s in labels.split(",") if s.strip()] if labels else []
        if label_list and column_type not in _LABELLED_TYPES:
            secho_err(
                f"Error: --labels only applies to {', '.join(sorted(_LABELLED_TYPES))} columns,"
                f" not '{column_type}'.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        client = get_client()
        variables: dict[str, Any] = {
            "boardId": str(board_id),
            "title": title,
            "columnType": column_type,
        }
        defaults = _build_defaults(column_type, label_list)
        if defaults is not None:
            variables["defaults"] = defaults
        if column_id:
            variables["columnId"] = column_id
        if description:
            variables["description"] = description

        result = client.execute_mutation(CREATE_COLUMN, variables)
        column = result.get("create_column")
        if not column or not column.get("id"):
            secho_err(
                "Error: Failed to create column. No data returned from API.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        secho_err(
            f"✓ Column '{column.get('title')}' created successfully!",
            fg=typer.colors.GREEN,
        )
        print_json(
            {
                "column_id": column.get("id"),
                "title": column.get("title"),
                "type": column.get("type"),
                "board_id": str(board_id),
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


@columns_app.command("delete")
def delete_column(
    board_id: int = typer.Option(..., "--board-id", "-b", help="ID of the board"),
    column_id: str = typer.Option(..., "--column-id", "-c", help="ID of the column to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Delete a column from a board (removes the column and all its data).

    WARNING: This action cannot be undone!

    By default, a confirmation prompt is shown before deletion. Use --force
    to skip the prompt (useful for automation scripts).

    Example:
        monday columns delete --board-id 123 --column-id status
        monday columns delete --board-id 123 --column-id status --force
    """
    try:
        client = get_client()

        # Validate the column exists before prompting or deleting (AC4).
        board_result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [str(board_id)]})
        boards = board_result.get("boards", [])
        if not boards:
            secho_err(
                f"Board {board_id} not found or you don't have access",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        columns = boards[0].get("columns", [])
        target = next((c for c in columns if c.get("id") == column_id), None)
        if target is None:
            secho_err(
                f"Column '{column_id}' not found on board {board_id}.",
                fg=typer.colors.YELLOW,
            )
            secho_err(
                f"Tip: run 'monday columns list --board-id {board_id}' to see column ids.",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        col_title = target.get("title", column_id)

        if not force:
            secho_err(
                f"WARNING: This will delete column '{col_title}' ({column_id})"
                f" and all its data from board {board_id}!",
                fg=typer.colors.YELLOW,
            )
            secho_err("This action cannot be undone.", fg=typer.colors.RED)
            confirm_delete = typer.confirm("Are you sure you want to continue?", err=True)
            if not confirm_delete:
                secho_err("Delete cancelled.", fg=typer.colors.BLUE)
                raise typer.Exit(0)

        result = client.execute_mutation(
            DELETE_COLUMN, {"boardId": str(board_id), "columnId": column_id}
        )
        deleted = result.get("delete_column")
        if not deleted or not deleted.get("id"):
            secho_err(
                "Error: Failed to delete column. No data returned from API.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        secho_err(f"✓ Column '{col_title}' deleted successfully!", fg=typer.colors.GREEN)
        print_json(
            {
                "column_id": deleted.get("id"),
                "title": col_title,
                "deleted": True,
                "board_id": str(board_id),
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
