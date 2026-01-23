"""Commands for managing Monday.com items."""

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import get_client, items_app
from monday_cli.client.mutations import CHANGE_COLUMN_VALUE, CREATE_ITEM
from monday_cli.client.queries import (
    GET_BOARD_COLUMNS,
    GET_BOARD_ITEMS,
    GET_ITEM_BY_ID,
    GET_NEXT_ITEMS_PAGE,
)
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


@items_app.command("get")
def get_item(
    item_id: int = typer.Argument(..., help="ID of the item to retrieve"),
) -> None:
    """Get all information for a specific item by ID.

    Retrieves item details including:
    - Basic information (name, state, timestamps)
    - Board and group information
    - Column values
    - Assets (files/documents)
    - Updates
    - Subitems
    """
    try:
        client = get_client()
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(item_id)]})

        items = result.get("items", [])
        if not items:
            typer.secho(f"Item {item_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        print_json(items[0])

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


@items_app.command("create")
def create_item(
    board_id: int = typer.Argument(..., help="ID of the board to create item on"),
    item_name: str = typer.Argument(..., help="Name of the new item"),
    group_id: Optional[str] = typer.Option(None, "--group-id", "-g", help="Group ID (optional)"),
    column_values: Optional[str] = typer.Option(
        None,
        "--column-values",
        "-c",
        help='Column values as JSON string (e.g. \'{"status":{"index":1}}\')',
    ),
) -> None:
    """Create a new item on a board.

    Example:
        monday items create 1234567890 "New Task"

        monday items create 1234567890 "New Task" --group-id "topics"

        monday items create 1234567890 "New Task" --column-values '{"status":{"index":1}}'
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
            "boardId": str(board_id),
            "itemName": item_name,
            "columnValues": column_values_str,
        }

        if group_id:
            variables["groupId"] = group_id

        result = client.execute_mutation(CREATE_ITEM, variables)
        created_item = result.get("create_item")

        if created_item:
            typer.secho("✓ Item created successfully!", fg=typer.colors.GREEN)
            print_json(created_item)
        else:
            typer.secho("Error: Failed to create item", fg=typer.colors.RED)
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


@items_app.command("list-statuses")
def list_statuses(
    item_id: int = typer.Argument(..., help="ID of the item"),
) -> None:
    """List all available status columns and their options for an item's board.

    This command fetches the item's board and displays all status columns
    with their available status options.

    Example:
        monday items list-statuses 1234567890
    """
    try:
        client = get_client()

        # First, get the item to find its board ID
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(item_id)]})
        items = result.get("items", [])

        if not items:
            typer.secho(f"Item {item_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        item = items[0]
        board = item.get("board")

        if not board:
            typer.secho("Error: Could not determine board for item", fg=typer.colors.RED)
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
            "item_id": str(item_id),
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


@items_app.command("update-status")
def update_item_status(
    item_id: int = typer.Argument(..., help="ID of the item"),
    column_id: str = typer.Argument(..., help="ID of the status column"),
    status_label: str = typer.Argument(..., help="Status label (e.g., 'Done', 'In Progress')"),
) -> None:
    """Update the status of an item using a human-readable status label.

    First fetches available statuses to find the index for the given label,
    then updates the item's status column.

    Example:
        monday items update-status 1234567890 status "Done"
        monday items update-status 1234567890 status_1 "In Progress"
    """
    try:
        client = get_client()

        # First, get the item to find its board ID
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(item_id)]})
        items = result.get("items", [])

        if not items:
            typer.secho(f"Item {item_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        item = items[0]
        board = item.get("board")

        if not board:
            typer.secho("Error: Could not determine board for item", fg=typer.colors.RED)
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
            "itemId": str(item_id),
            "columnId": column_id,
            "value": status_value,
        }

        update_result = client.execute_mutation(CHANGE_COLUMN_VALUE, variables)
        updated_item = update_result.get("change_column_value")

        if updated_item:
            typer.secho(
                f"✓ Status updated to '{status_label}' successfully!",
                fg=typer.colors.GREEN
            )
            print_json(updated_item)
        else:
            typer.secho("Error: Failed to update item status", fg=typer.colors.RED)
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


@items_app.command("list-columns")
def list_columns(
    item_id: int = typer.Argument(..., help="ID of the item"),
) -> None:
    """List all board columns for an item in an easy-to-use format.

    This command fetches all columns from the item's board, making it easy
    to see column IDs and types for use in update commands.

    Example:
        monday items list-columns 1234567890
    """
    try:
        client = get_client()

        # First, get the item to find its board ID
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(item_id)]})
        items = result.get("items", [])

        if not items:
            typer.secho(f"Item {item_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        item = items[0]
        board = item.get("board")

        if not board:
            typer.secho("Error: Could not determine board for item", fg=typer.colors.RED)
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
            "item_id": str(item_id),
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


@items_app.command("list")
def list_items(
    board_id: Optional[int] = typer.Argument(None, help="ID of the board to list items from"),
    board_id_opt: Optional[int] = typer.Option(None, "--board-id", "-b", help="ID of the board to list items from"),
    limit: int = typer.Option(100, "--limit", "-l", help="Items per page (max 500)"),
    all_pages: bool = typer.Option(False, "--all", "-a", help="Fetch all items across all pages"),
    cursor: Optional[str] = typer.Option(None, "--cursor", "-c", help="Pagination cursor for next page"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table instead of JSON"),
) -> None:
    """List all items from a board ID.

    Returns items with pagination support. By default, returns the first 100 items.
    Use --cursor to get the next page, or --all to fetch all items automatically.

    Column values are included by default for complete data export.

    Example:
        monday items list 1234567890

        monday items list --board-id 1234567890

        monday items list --board-id 1234567890 --limit 50

        monday items list --board-id 1234567890 --all

        monday items list --board-id 1234567890 --cursor "MSw5NzI4MDA5MDAsaV9YcmxJb0p1VEdYc1VWeGlxeF9kLDg4MiwzNXw0MTQ1NzU1MTE5"

        monday items list --board-id 1234567890 --table
    """
    try:
        # Determine which board_id to use
        final_board_id = board_id_opt if board_id_opt is not None else board_id

        if final_board_id is None:
            typer.secho(
                "Error: Board ID is required. Provide it as an argument or use --board-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday items list 1234567890", fg=typer.colors.BLUE)
            typer.secho("Example: monday items list --board-id 1234567890", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        # Validate limit
        if limit < 1 or limit > 500:
            typer.secho(
                "Error: Limit must be between 1 and 500",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        client = get_client()

        # Fetch first page
        variables = {
            "boardIds": [str(final_board_id)],
            "limit": limit,
        }

        if cursor:
            variables["cursor"] = cursor

        result = client.execute_query(GET_BOARD_ITEMS, variables)

        boards = result.get("boards", [])
        if not boards:
            typer.secho(
                f"Board {final_board_id} not found or you don't have access",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        board = boards[0]
        board_name = board.get("name", "Unknown")
        items_page = board.get("items_page", {})
        all_items = items_page.get("items", [])
        next_cursor = items_page.get("cursor")

        # If --all flag is set, fetch all pages
        pages_fetched = 1
        if all_pages and next_cursor:
            typer.secho(
                f"Fetching page {pages_fetched}... ({len(all_items)} items)",
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
                all_items.extend(page_items)
                next_cursor = next_page.get("cursor")

                typer.secho(
                    f"  Total items so far: {len(all_items)}",
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
            title = f"{board_name} - Items"
            if all_pages:
                title += f" ({len(all_items)} total, {pages_fetched} pages)"
            else:
                title += f" ({len(all_items)} items" + (", more available)" if next_cursor else ")")

            rich_table = Table(title=title)

            rich_table.add_column("ID", style="cyan", no_wrap=True)
            rich_table.add_column("Name", style="green")
            rich_table.add_column("State", style="yellow")
            rich_table.add_column("Group", style="blue")
            rich_table.add_column("Creator", style="magenta")
            rich_table.add_column("Created", style="dim")

            for item in all_items:
                group_title = item.get("group", {}).get("title", "N/A") if item.get("group") else "N/A"
                creator_name = item.get("creator", {}).get("name", "N/A") if item.get("creator") else "N/A"
                created_at = item.get("created_at", "N/A")
                if created_at != "N/A" and "T" in created_at:
                    # Format to just date
                    created_at = created_at.split("T")[0]

                rich_table.add_row(
                    str(item.get("id", "")),
                    item.get("name", ""),
                    item.get("state", ""),
                    group_title,
                    creator_name,
                    created_at,
                )

            console.print(rich_table)

            # Show summary info
            if all_pages:
                typer.secho(f"\nTotal items: {len(all_items)} (fetched {pages_fetched} pages)", fg=typer.colors.BLUE)
            else:
                if next_cursor:
                    typer.secho(f"\nShowing {len(all_items)} items. Use --cursor to get next page or --all to fetch all items.", fg=typer.colors.BLUE)
                else:
                    typer.secho(f"\nTotal items: {len(all_items)}", fg=typer.colors.BLUE)
        else:
            if all_pages:
                output = {
                    "board_id": str(final_board_id),
                    "board_name": board_name,
                    "items": all_items,
                    "total_items": len(all_items),
                    "pages_fetched": pages_fetched,
                }
            else:
                output = {
                    "board_id": str(final_board_id),
                    "board_name": board_name,
                    "items": all_items,
                    "cursor": next_cursor,
                    "has_more": next_cursor is not None,
                    "items_count": len(all_items),
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
