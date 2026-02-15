"""Commands for managing Monday.com items."""

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import get_client, items_app
from monday_cli.client.mutations import CHANGE_COLUMN_VALUE, CREATE_ITEM, DELETE_ITEM
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
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the item to retrieve"),
) -> None:
    """Get all information for a specific item by ID.

    Retrieves item details including:
    - Basic information (name, state, timestamps)
    - Board and group information
    - Column values
    - Assets (files/documents)
    - Updates
    - Subitems

    Example:
        monday items get --item-id 1234567890
    """
    try:
        if item_id is None:
            typer.secho(
                "Error: Item ID is required. Use --item-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday items get --item-id 1234567890", fg=typer.colors.BLUE)
            raise typer.Exit(1)

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
    board_id: Optional[int] = typer.Option(None, "--board-id", "-b", help="ID of the board to create item on"),
    item_name: Optional[str] = typer.Option(None, "--name", "-n", help="Name of the new item"),
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
        monday items create --board-id 1234567890 --name "New Task"

        monday items create --board-id 1234567890 --name "New Task" --group-id "topics"

        monday items create --board-id 1234567890 --name "New Task" --column-values '{"status":{"index":1}}'
    """
    try:
        if board_id is None:
            typer.secho(
                "Error: Board ID is required. Use --board-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday items create --board-id 1234567890 --name \"New Task\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        if item_name is None:
            typer.secho(
                "Error: Item name is required. Use --name",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday items create --board-id 1234567890 --name \"New Task\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

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


@items_app.command("update")
def update_item(
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the item"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Column title (e.g., 'Status', 'Github Issue Link')"),
    value: Optional[str] = typer.Option(None, "--value", "-v", help="Value to set"),
) -> None:
    """Update an item column value using human-readable column titles.

    This command automatically determines the column type and formats the value
    appropriately. Supports status, text, link, date, and other column types.

    Example:
        monday items update --item-id 1234567890 --title "Status" --value "Done"

        monday items update --item-id 1234567890 --title "Github Issue Link" --value "https://foo.com"

        monday items update --item-id 1234567890 --title "Due Date" --value "2024-12-31"
    """
    try:
        if item_id is None:
            typer.secho(
                "Error: Item ID is required. Use --item-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday items update --item-id 1234567890 --title \"Status\" --value \"Done\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        if title is None:
            typer.secho(
                "Error: Column title is required. Use --title",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday items update --item-id 1234567890 --title \"Status\" --value \"Done\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        if value is None:
            typer.secho(
                "Error: Value is required. Use --value",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday items update --item-id 1234567890 --title \"Status\" --value \"Done\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

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

        # Get board columns to find the column by title
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

        # Find the column by title (case-insensitive)
        target_column = None
        title_lower = title.lower()
        for col in columns:
            if col["title"].lower() == title_lower:
                target_column = col
                break

        if not target_column:
            available_titles = ", ".join(f"'{col['title']}'" for col in columns)
            typer.secho(
                f"Error: Column with title '{title}' not found on board {board_id}",
                fg=typer.colors.RED
            )
            typer.secho(f"Available columns: {available_titles}", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        column_id = target_column["id"]
        column_type = target_column.get("type")

        # Format value based on column type
        formatted_value = None

        if column_type == "status":
            # For status columns, find the index for the given label
            settings_str = target_column.get("settings_str")
            if not settings_str:
                typer.secho(
                    f"Error: Status column '{title}' has no status options configured",
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
            value_lower = value.lower()

            for idx, label in labels.items():
                if label.lower() == value_lower:
                    status_index = int(idx)
                    break

            if status_index is None:
                available_labels = ", ".join(f"'{label}'" for label in labels.values())
                typer.secho(
                    f"Error: Status '{value}' not found in column '{title}'",
                    fg=typer.colors.RED
                )
                typer.secho(f"Available statuses: {available_labels}", fg=typer.colors.YELLOW)
                raise typer.Exit(1)

            formatted_value = json.dumps({"index": status_index})

        elif column_type == "text":
            # Plain text column
            formatted_value = json.dumps(value)

        elif column_type == "link":
            # Link column
            formatted_value = json.dumps({"url": value, "text": value})

        elif column_type == "date":
            # Date column
            formatted_value = json.dumps({"date": value})

        elif column_type == "numbers":
            # Numbers column
            formatted_value = json.dumps(value)

        elif column_type == "long-text":
            # Long text column
            formatted_value = json.dumps({"text": value})

        else:
            # For other column types, try to pass the value as-is
            # User may need to provide JSON for complex types
            try:
                # Try to parse as JSON first
                json.loads(value)
                formatted_value = value
            except json.JSONDecodeError:
                # If not JSON, wrap as string
                formatted_value = json.dumps(value)

        # Update the column value
        variables = {
            "boardId": board_id,
            "itemId": str(item_id),
            "columnId": column_id,
            "value": formatted_value,
        }

        update_result = client.execute_mutation(CHANGE_COLUMN_VALUE, variables)
        updated_item = update_result.get("change_column_value")

        if updated_item:
            typer.secho(
                f"✓ Item column '{title}' updated to '{value}' successfully!",
                fg=typer.colors.GREEN
            )
            print_json(updated_item)
        else:
            typer.secho("Error: Failed to update item column", fg=typer.colors.RED)
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
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the item"),
) -> None:
    """List all board columns for an item in an easy-to-use format.

    This command fetches all columns from the item's board, making it easy
    to see column IDs and types for use in update commands.

    Example:
        monday items list-columns --item-id 1234567890
    """
    try:
        if item_id is None:
            typer.secho(
                "Error: Item ID is required. Use --item-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday items list-columns --item-id 1234567890", fg=typer.colors.BLUE)
            raise typer.Exit(1)

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
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Filter by group title (case-insensitive)"),
    group_id: Optional[str] = typer.Option(None, "--group-id", help="Filter by group ID (exact match)"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table instead of JSON"),
) -> None:
    """List all items/tasks from a board.

    Lists main items (tasks) from regular boards only. This command will NOT list
    subitems - use 'monday subitems list' for that.

    Returns items with pagination support. By default, returns the first 100 items.
    Use --cursor to get the next page, or --all to fetch all items automatically.

    Filter by group using --group (matches group title, case-insensitive) or
    --group-id (matches exact group ID). Use 'monday groups list' to see available groups.

    Column values are included by default for complete data export.

    Example:
        monday items list 1234567890

        monday items list --board-id 1234567890

        monday items list --board-id 1234567890 --limit 50

        monday items list --board-id 1234567890 --all

        monday items list --board-id 1234567890 --group "Topics"

        monday items list --board-id 1234567890 --group-id "topics"

        monday items list --board-id 1234567890 --group "Topics" --all

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

        # Validate that both group filters aren't used together
        if group and group_id:
            typer.secho(
                "Error: Cannot use both --group and --group-id together. Choose one.",
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

        # Check if this is a subitems board - REFUSE to list subitems
        if "subitems of" in board_name.lower():
            typer.secho(
                f"Error: Board '{board_name}' is a subitems board.",
                fg=typer.colors.RED,
            )
            typer.secho(
                f"Use 'monday subitems list --board-id {final_board_id}' to list subitems.",
                fg=typer.colors.BLUE,
            )
            typer.secho(
                "The 'items list' command is for listing main items/tasks from regular boards only.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

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

        # Apply group filtering if specified (client-side filtering)
        if group or group_id:
            original_count = len(all_items)

            if group_id:
                # Exact match on group ID
                all_items = [
                    item for item in all_items
                    if item.get("group") and item["group"].get("id") == group_id
                ]
            else:  # group filter (title)
                # Case-insensitive match on group title
                group_lower = group.lower()
                all_items = [
                    item for item in all_items
                    if item.get("group") and item["group"].get("title", "").lower() == group_lower
                ]

            filtered_count = len(all_items)
            if filtered_count == 0:
                typer.secho(
                    f"No items found in group '{group or group_id}' on board {final_board_id}",
                    fg=typer.colors.YELLOW,
                )
                typer.secho(
                    f"Tip: Use 'monday groups list {final_board_id}' to see available groups",
                    fg=typer.colors.BLUE,
                )
                raise typer.Exit(0)

            # Show filter info when fetching multiple pages
            if all_pages and original_count != filtered_count:
                typer.secho(
                    f"Filtered {original_count} items to {filtered_count} in group '{group or group_id}'",
                    fg=typer.colors.GREEN,
                )

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

            # Add filter metadata if used
            if group:
                output["group_filter"] = group
            if group_id:
                output["group_id_filter"] = group_id

            print_json(output)

    except typer.Exit:
        raise
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


@items_app.command("delete")
def delete_item(
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the item to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Delete an item from Monday.com.

    WARNING: This action cannot be undone! The item and all its data will be permanently deleted.

    By default, you will be prompted to confirm the deletion. Use --force to skip the prompt
    (useful for automation scripts).

    Example:
        monday items delete --item-id 1234567890

        monday items delete --item-id 1234567890 --force
    """
    try:
        if item_id is None:
            typer.secho(
                "Error: Item ID is required. Use --item-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday items delete --item-id 1234567890", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        client = get_client()

        # First, get the item to verify it exists and get its name
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(item_id)]})
        items = result.get("items", [])

        if not items:
            typer.secho(f"Item {item_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        item = items[0]
        item_name = item.get("name", "Unknown")
        board = item.get("board", {})
        board_name = board.get("name", "Unknown") if board else "Unknown"

        # Confirmation prompt (unless --force is used)
        if not force:
            typer.secho(
                f"WARNING: This will permanently delete item '{item_name}' (ID: {item_id}) from board '{board_name}'!",
                fg=typer.colors.YELLOW
            )
            typer.secho("This action cannot be undone.", fg=typer.colors.RED)
            confirm_delete = typer.confirm("Are you sure you want to continue?")
            if not confirm_delete:
                typer.secho("Delete cancelled.", fg=typer.colors.BLUE)
                raise typer.Exit(0)

        # Execute delete mutation
        variables = {"itemId": str(item_id)}
        delete_result = client.execute_mutation(DELETE_ITEM, variables)
        deleted_item = delete_result.get("delete_item")

        if deleted_item:
            typer.secho(
                f"✓ Item '{item_name}' (ID: {item_id}) deleted successfully!",
                fg=typer.colors.GREEN
            )
            output = {
                "item_id": str(item_id),
                "item_name": item_name,
                "board_name": board_name,
                "deleted": True,
            }
            print_json(output)
        else:
            # Deletion may have succeeded but returned no data
            # Verify by trying to fetch the item again
            typer.secho("Verifying deletion...", fg=typer.colors.YELLOW)
            verify_result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(item_id)]})
            verify_items = verify_result.get("items", [])

            if not verify_items:
                # Item is gone, deletion succeeded
                typer.secho(
                    f"✓ Item '{item_name}' (ID: {item_id}) deleted successfully!",
                    fg=typer.colors.GREEN
                )
                output = {
                    "item_id": str(item_id),
                    "item_name": item_name,
                    "board_name": board_name,
                    "deleted": True,
                }
                print_json(output)
            else:
                typer.secho("Error: Failed to delete item", fg=typer.colors.RED)
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
