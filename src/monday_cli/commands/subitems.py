"""Commands for managing Monday.com subitems."""

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import get_client, subitems_app
from monday_cli.client.mutations import CHANGE_COLUMN_VALUE, CREATE_SUBITEM
from monday_cli.client.queries import (
    GET_BOARD_COLUMNS,
    GET_BOARD_ITEMS,
    GET_ITEM_BY_ID,
    GET_ITEM_SUBITEMS,
    GET_NEXT_ITEMS_PAGE,
)
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


@subitems_app.command("list")
def list_subitems(
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the parent item to list subitems from"),
    board_id: Optional[int] = typer.Option(None, "--board-id", "-b", help="ID of the subitems board to list from"),
    limit: int = typer.Option(100, "--limit", "-l", help="Items per page (max 500, only used with --board-id)"),
    all_pages: bool = typer.Option(False, "--all", "-a", help="Fetch all subitems across all pages (only used with --board-id)"),
    cursor: Optional[str] = typer.Option(None, "--cursor", "-c", help="Pagination cursor for next page (only used with --board-id)"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table instead of JSON"),
) -> None:
    """List subitems from a parent item or board.

    You can list subitems in two ways:
    1. By parent item ID (--item-id): Lists all subitems belonging to a specific parent item
    2. By board ID (--board-id): Lists all subitems from a board
       - For main boards: Aggregates all subitems from all items on the board
       - For subitems boards: Lists all subitems directly (with pagination support)

    Note: Use 'monday items list' for main items/tasks on regular boards.

    Example:
        monday subitems list --item-id 1234567890

        monday subitems list --board-id 1234567890

        monday subitems list --board-id 1234567890 --table

        monday subitems list --board-id 1234567890 --all
    """
    try:
        if item_id is None and board_id is None:
            typer.secho(
                "Error: Either --item-id or --board-id is required",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday subitems list --item-id 1234567890", fg=typer.colors.BLUE)
            typer.secho("Example: monday subitems list --board-id 1234567890", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        if item_id is not None and board_id is not None:
            typer.secho(
                "Error: Cannot use both --item-id and --board-id. Choose one.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        client = get_client()

        # Case 1: List subitems by parent item ID
        if item_id is not None:
            result = client.execute_query(GET_ITEM_SUBITEMS, {"itemIds": [str(item_id)]})
            items = result.get("items", [])

            if not items:
                typer.secho(f"Item {item_id} not found", fg=typer.colors.YELLOW)
                raise typer.Exit(1)

            item = items[0]
            item_name = item.get("name", "Unknown")
            subitems = item.get("subitems", [])

            if not subitems:
                typer.secho(f"No subitems found for item {item_id} ({item_name})", fg=typer.colors.YELLOW)
                raise typer.Exit(0)

            # Output as table or JSON
            if table:
                console = Console()
                rich_table = Table(title=f"Subitems of '{item_name}' (ID: {item_id})")

                rich_table.add_column("ID", style="cyan", no_wrap=True)
                rich_table.add_column("Name", style="green")
                rich_table.add_column("State", style="yellow")
                rich_table.add_column("Board", style="blue")
                rich_table.add_column("Creator", style="magenta")
                rich_table.add_column("Created", style="dim")

                for subitem in subitems:
                    board_name = subitem.get("board", {}).get("name", "N/A") if subitem.get("board") else "N/A"
                    creator_name = subitem.get("creator", {}).get("name", "N/A") if subitem.get("creator") else "N/A"
                    created_at = subitem.get("created_at", "N/A")
                    if created_at != "N/A" and "T" in created_at:
                        created_at = created_at.split("T")[0]

                    rich_table.add_row(
                        str(subitem.get("id", "")),
                        subitem.get("name", ""),
                        subitem.get("state", ""),
                        board_name,
                        creator_name,
                        created_at,
                    )

                console.print(rich_table)
                typer.secho(f"\nTotal subitems: {len(subitems)}", fg=typer.colors.BLUE)
            else:
                output = {
                    "parent_item_id": str(item_id),
                    "parent_item_name": item_name,
                    "subitems": subitems,
                    "total_subitems": len(subitems),
                }
                print_json(output)

        # Case 2: List subitems by board ID (with pagination)
        else:
            # Validate limit
            if limit < 1 or limit > 500:
                typer.secho(
                    "Error: Limit must be between 1 and 500",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)

            # Fetch first page
            variables = {
                "boardIds": [str(board_id)],
                "limit": limit,
            }

            if cursor:
                variables["cursor"] = cursor

            result = client.execute_query(GET_BOARD_ITEMS, variables)

            boards = result.get("boards", [])
            if not boards:
                typer.secho(
                    f"Board {board_id} not found or you don't have access",
                    fg=typer.colors.YELLOW,
                )
                raise typer.Exit(1)

            board = boards[0]
            board_name = board.get("name", "Unknown")

            # Check if this is a main board (not a subitems board)
            # If it is, we need to fetch all items and their subitems
            if "subitems of" not in board_name.lower():
                # This is a main board - fetch all items with their subitems
                items_page = board.get("items_page", {})
                main_items = items_page.get("items", [])

                # Fetch subitems for each item
                all_subitems = []
                for item in main_items:
                    item_id = item.get("id")
                    if item_id:
                        # Fetch subitems for this item
                        subitems_result = client.execute_query(
                            GET_ITEM_SUBITEMS,
                            {"itemIds": [item_id]}
                        )
                        items_with_subitems = subitems_result.get("items", [])
                        if items_with_subitems:
                            subitems = items_with_subitems[0].get("subitems", [])
                            all_subitems.extend(subitems)

                # For main boards, we don't support pagination with cursor
                # because we're aggregating subitems from multiple items
                next_cursor = None

                if not all_subitems:
                    typer.secho(
                        f"No subitems found on board '{board_name}' (ID: {board_id})",
                        fg=typer.colors.YELLOW,
                    )
                    raise typer.Exit(0)
            else:
                # This is a subitems board - use the items directly
                items_page = board.get("items_page", {})
                all_subitems = items_page.get("items", [])
                next_cursor = items_page.get("cursor")

            # If --all flag is set, fetch all pages
            # (only supported for subitems boards, not main boards)
            pages_fetched = 1
            if all_pages and next_cursor:
                typer.secho(
                    f"Fetching page {pages_fetched}... ({len(all_subitems)} subitems)",
                    fg=typer.colors.BLUE,
                )

                while next_cursor:
                    pages_fetched += 1
                    typer.secho(
                        f"Fetching page {pages_fetched}...",
                        fg=typer.colors.BLUE,
                    )

                    result = client.execute_query(
                        GET_NEXT_ITEMS_PAGE,
                        {"cursor": next_cursor, "limit": limit},
                    )

                    next_page = result.get("next_items_page", {})
                    page_items = next_page.get("items", [])
                    all_subitems.extend(page_items)
                    next_cursor = next_page.get("cursor")

                    typer.secho(
                        f"  Total subitems so far: {len(all_subitems)}",
                        fg=typer.colors.BLUE,
                    )

                    # Safety check to prevent infinite loops
                    if pages_fetched > 1000:
                        typer.secho(
                            "Warning: Reached maximum page limit (1000). Stopping pagination.",
                            fg=typer.colors.YELLOW,
                        )
                        break

            # Format output
            if table:
                console = Console()
                title = f"{board_name} - Subitems"
                if all_pages:
                    title += f" ({len(all_subitems)} total, {pages_fetched} pages)"
                else:
                    title += f" ({len(all_subitems)} subitems" + (", more available)" if next_cursor else ")")

                rich_table = Table(title=title)

                rich_table.add_column("ID", style="cyan", no_wrap=True)
                rich_table.add_column("Name", style="green")
                rich_table.add_column("State", style="yellow")
                rich_table.add_column("Group", style="blue")
                rich_table.add_column("Creator", style="magenta")
                rich_table.add_column("Created", style="dim")

                for subitem in all_subitems:
                    group_title = subitem.get("group", {}).get("title", "N/A") if subitem.get("group") else "N/A"
                    creator_name = subitem.get("creator", {}).get("name", "N/A") if subitem.get("creator") else "N/A"
                    created_at = subitem.get("created_at", "N/A")
                    if created_at != "N/A" and "T" in created_at:
                        created_at = created_at.split("T")[0]

                    rich_table.add_row(
                        str(subitem.get("id", "")),
                        subitem.get("name", ""),
                        subitem.get("state", ""),
                        group_title,
                        creator_name,
                        created_at,
                    )

                console.print(rich_table)

                # Show summary info
                if all_pages:
                    typer.secho(f"\nTotal subitems: {len(all_subitems)} (fetched {pages_fetched} pages)", fg=typer.colors.BLUE)
                else:
                    if next_cursor:
                        typer.secho(f"\nShowing {len(all_subitems)} subitems. Use --cursor to get next page or --all to fetch all subitems.", fg=typer.colors.BLUE)
                    else:
                        typer.secho(f"\nTotal subitems: {len(all_subitems)}", fg=typer.colors.BLUE)
            else:
                if all_pages:
                    output = {
                        "board_id": str(board_id),
                        "board_name": board_name,
                        "subitems": all_subitems,
                        "total_subitems": len(all_subitems),
                        "pages_fetched": pages_fetched,
                    }
                else:
                    output = {
                        "board_id": str(board_id),
                        "board_name": board_name,
                        "subitems": all_subitems,
                        "cursor": next_cursor,
                        "has_more": next_cursor is not None,
                        "subitems_count": len(all_subitems),
                    }

                print_json(output)

    except AuthenticationError:
        typer.secho(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        typer.secho(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@subitems_app.command("create")
def create_subitem(
    parent_item_id: int = typer.Argument(..., help="ID of the parent item"),
    subitem_name: str = typer.Argument(..., help="Name of the new subitem"),
    column_values: Optional[str] = typer.Option(
        None,
        "--column-values",
        "-c",
        help='Column values as JSON string (e.g. \'{"status":{"index":1}}\')',
    ),
) -> None:
    """Create a new subitem under a parent item.

    Example:
        monday subitems create 1234567890 "New Subtask"

        monday subitems create 1234567890 "New Subtask" --column-values '{"status":{"index":1}}'
    """
    try:
        client = get_client()

        # Parse column values if provided
        column_values_dict = None
        if column_values:
            try:
                column_values_dict = json.loads(column_values)
                # Monday.com expects column_values as a JSON string
                column_values_str = json.dumps(column_values_dict)
            except json.JSONDecodeError as e:
                typer.secho(f"Error: Invalid JSON in column-values: {str(e)}", fg=typer.colors.RED)
                raise typer.Exit(1)
        else:
            column_values_str = None

        variables = {
            "parentItemId": str(parent_item_id),
            "itemName": subitem_name,
            "columnValues": column_values_str,
        }

        result = client.execute_mutation(CREATE_SUBITEM, variables)
        created_subitem = result.get("create_subitem")

        if created_subitem:
            typer.secho("✓ Subitem created successfully!", fg=typer.colors.GREEN)
            print_json(created_subitem)
        else:
            typer.secho("Error: Failed to create subitem", fg=typer.colors.RED)
            raise typer.Exit(1)

    except AuthenticationError:
        typer.secho(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        typer.secho(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@subitems_app.command("update-status")
def update_subitem_status(
    subitem_id: int = typer.Argument(..., help="ID of the subitem"),
    board_id: int = typer.Argument(..., help="ID of the board containing the subitem"),
    column_id: str = typer.Argument(..., help="ID of the status column"),
    status_index: int = typer.Argument(..., help="Status index (e.g., 0, 1, 2)"),
) -> None:
    """Update the status of a subitem.

    The status_index corresponds to the position of the status in the column settings.
    For example, if your status column has: Done (0), Working (1), Stuck (2)

    Example:
        monday subitems update-status 9999999999 1234567890 status 1
    """
    try:
        client = get_client()

        # Format the status value as Monday.com expects
        status_value = json.dumps({"index": status_index})

        variables = {
            "boardId": str(board_id),
            "itemId": str(subitem_id),
            "columnId": column_id,
            "value": status_value,
        }

        result = client.execute_mutation(CHANGE_COLUMN_VALUE, variables)
        updated_item = result.get("change_column_value")

        if updated_item:
            typer.secho("✓ Subitem status updated successfully!", fg=typer.colors.GREEN)
            print_json(updated_item)
        else:
            typer.secho("Error: Failed to update subitem status", fg=typer.colors.RED)
            raise typer.Exit(1)

    except AuthenticationError:
        typer.secho(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        typer.secho(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@subitems_app.command("list-columns")
def list_columns(
    subitem_id: int = typer.Argument(..., help="ID of the subitem"),
) -> None:
    """List all board columns for a subitem in an easy-to-use format.

    This command fetches all columns from the subitem's board, making it easy
    to see column IDs and types for use in update commands.

    Example:
        monday subitems list-columns 9999999999
    """
    try:
        client = get_client()

        # First, get the subitem to find its board ID
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(subitem_id)]})
        items = result.get("items", [])

        if not items:
            typer.secho(f"Subitem {subitem_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        subitem = items[0]
        board = subitem.get("board")

        if not board:
            typer.secho("Error: Could not determine board for subitem", fg=typer.colors.RED)
            raise typer.Exit(1)

        board_id = board["id"]
        board_name = board["name"]

        # Get board columns with settings
        columns_result = client.execute_query(
            GET_BOARD_COLUMNS,
            {"boardIds": [board_id]}
        )

        boards = columns_result.get("boards", [])
        if not boards:
            typer.secho("Error: Could not fetch board columns", fg=typer.colors.RED)
            raise typer.Exit(1)

        board_data = boards[0]
        columns = board_data.get("columns", [])

        # Format columns for easy consumption
        formatted_columns = []
        for col in columns:
            column_info = {
                "column_id": col["id"],
                "title": col["title"],
                "type": col["type"]
            }

            # Add status options for status columns
            if col.get("type") == "status" and col.get("settings_str"):
                try:
                    settings = json.loads(col["settings_str"])
                    labels = settings.get("labels", {})
                    status_options = [
                        {"index": int(idx), "label": label}
                        for idx, label in labels.items()
                    ]
                    status_options.sort(key=lambda x: x["index"])
                    column_info["status_options"] = status_options
                except (json.JSONDecodeError, AttributeError, ValueError):
                    pass

            formatted_columns.append(column_info)

        # Output results
        output = {
            "board_id": board_id,
            "board_name": board_name,
            "subitem_id": str(subitem_id),
            "columns": formatted_columns
        }

        print_json(output)

    except AuthenticationError:
        typer.secho(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        typer.secho(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@subitems_app.command("list-statuses")
def list_statuses(
    subitem_id: int = typer.Argument(..., help="ID of the subitem"),
) -> None:
    """List all available status columns and their options for a subitem's board.

    This command fetches the subitem's board and displays all status columns
    with their available status options.

    Example:
        monday subitems list-statuses 9999999999
    """
    try:
        client = get_client()

        # First, get the subitem to find its board ID
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(subitem_id)]})
        items = result.get("items", [])

        if not items:
            typer.secho(f"Subitem {subitem_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        subitem = items[0]
        board = subitem.get("board")

        if not board:
            typer.secho("Error: Could not determine board for subitem", fg=typer.colors.RED)
            raise typer.Exit(1)

        board_id = board["id"]
        board_name = board["name"]

        # Get board columns with settings
        columns_result = client.execute_query(
            GET_BOARD_COLUMNS,
            {"boardIds": [board_id]}
        )

        boards = columns_result.get("boards", [])
        if not boards:
            typer.secho("Error: Could not fetch board columns", fg=typer.colors.RED)
            raise typer.Exit(1)

        board_data = boards[0]
        columns = board_data.get("columns", [])

        # Filter and parse status columns
        status_columns = []
        for col in columns:
            if col.get("type") == "status" and col.get("settings_str"):
                try:
                    settings = json.loads(col["settings_str"])
                    labels = settings.get("labels", {})

                    status_options = [
                        {
                            "index": int(idx),
                            "label": label
                        }
                        for idx, label in labels.items()
                    ]

                    # Sort by index
                    status_options.sort(key=lambda x: x["index"])

                    status_columns.append({
                        "column_id": col["id"],
                        "column_title": col["title"],
                        "statuses": status_options
                    })
                except (json.JSONDecodeError, AttributeError, ValueError):
                    continue

        if not status_columns:
            typer.secho(
                f"No status columns found on board '{board_name}' (ID: {board_id})",
                fg=typer.colors.YELLOW
            )
            raise typer.Exit(0)

        # Output results
        output = {
            "board_id": board_id,
            "board_name": board_name,
            "subitem_id": str(subitem_id),
            "status_columns": status_columns
        }

        print_json(output)

    except AuthenticationError:
        typer.secho(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        typer.secho(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@subitems_app.command("update-status-label")
def update_subitem_status_label(
    subitem_id: int = typer.Argument(..., help="ID of the subitem"),
    column_id: str = typer.Argument(..., help="ID of the status column"),
    status_label: str = typer.Argument(..., help="Status label (e.g., 'Done', 'In Progress')"),
) -> None:
    """Update the status of a subitem using a human-readable status label.

    First fetches available statuses to find the index for the given label,
    then updates the subitem's status column. This is an alternative to
    'update-status' which requires knowing the status index.

    Example:
        monday subitems update-status-label 9999999999 status "Done"
        monday subitems update-status-label 9999999999 status_1 "In Progress"
    """
    try:
        client = get_client()

        # First, get the subitem to find its board ID
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(subitem_id)]})
        items = result.get("items", [])

        if not items:
            typer.secho(f"Subitem {subitem_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        subitem = items[0]
        board = subitem.get("board")

        if not board:
            typer.secho("Error: Could not determine board for subitem", fg=typer.colors.RED)
            raise typer.Exit(1)

        board_id = board["id"]

        # Get board columns to find status options
        columns_result = client.execute_query(
            GET_BOARD_COLUMNS,
            {"boardIds": [board_id]}
        )

        boards = columns_result.get("boards", [])
        if not boards:
            typer.secho("Error: Could not fetch board columns", fg=typer.colors.RED)
            raise typer.Exit(1)

        board_data = boards[0]
        columns = board_data.get("columns", [])

        # Find the specified column and get its status options
        target_column = None
        for col in columns:
            if col["id"] == column_id:
                target_column = col
                break

        if not target_column:
            typer.secho(
                f"Error: Column '{column_id}' not found on board {board_id}",
                fg=typer.colors.RED
            )
            raise typer.Exit(1)

        if target_column.get("type") != "status":
            typer.secho(
                f"Error: Column '{column_id}' is not a status column (type: {target_column.get('type')})",
                fg=typer.colors.RED
            )
            raise typer.Exit(1)

        # Parse status options
        settings_str = target_column.get("settings_str")
        if not settings_str:
            typer.secho(
                f"Error: Column '{column_id}' has no status options configured",
                fg=typer.colors.RED
            )
            raise typer.Exit(1)

        try:
            settings = json.loads(settings_str)
            labels = settings.get("labels", {})
        except json.JSONDecodeError:
            typer.secho("Error: Could not parse column settings", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Find the status index for the given label (case-insensitive)
        status_index = None
        status_label_lower = status_label.lower()

        for idx, label in labels.items():
            if label.lower() == status_label_lower:
                status_index = int(idx)
                break

        if status_index is None:
            available_labels = ", ".join(f"'{label}'" for label in labels.values())
            typer.secho(
                f"Error: Status '{status_label}' not found in column '{column_id}'",
                fg=typer.colors.RED
            )
            typer.secho(f"Available statuses: {available_labels}", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        # Update the status
        status_value = json.dumps({"index": status_index})

        variables = {
            "boardId": board_id,
            "itemId": str(subitem_id),
            "columnId": column_id,
            "value": status_value,
        }

        update_result = client.execute_mutation(CHANGE_COLUMN_VALUE, variables)
        updated_subitem = update_result.get("change_column_value")

        if updated_subitem:
            typer.secho(
                f"✓ Subitem status updated to '{status_label}' successfully!",
                fg=typer.colors.GREEN
            )
            print_json(updated_subitem)
        else:
            typer.secho("Error: Failed to update subitem status", fg=typer.colors.RED)
            raise typer.Exit(1)

    except AuthenticationError:
        typer.secho(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        typer.secho(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
