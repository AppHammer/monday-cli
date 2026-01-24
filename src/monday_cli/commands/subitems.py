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


@subitems_app.command("get")
def get_subitem(
    subitem_id: Optional[int] = typer.Option(None, "--subitem-id", help="Subitem ID"),
) -> None:
    """Get a single subitem by ID.

    Example:
        monday subitems get --subitem-id 1234567890
    """
    if subitem_id is None:
        typer.secho(
            "Error: --subitem-id is required\n"
            "Usage: monday subitems get --subitem-id <id>",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    try:
        client = get_client()
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(subitem_id)]})
        items = result.get("items", [])

        if not items:
            typer.secho(f"Subitem {subitem_id} not found", fg=typer.colors.YELLOW)
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
                rich_table.add_column("Parent ID", style="blue", no_wrap=True)
                rich_table.add_column("Status", style="yellow")
                rich_table.add_column("Creator", style="magenta")
                rich_table.add_column("Created", style="dim")

                for subitem in subitems:
                    creator_name = subitem.get("creator", {}).get("name", "N/A") if subitem.get("creator") else "N/A"
                    created_at = subitem.get("created_at", "N/A")
                    if created_at != "N/A" and "T" in created_at:
                        created_at = created_at.split("T")[0]

                    # Extract status from column_values
                    status_text = "N/A"
                    column_values = subitem.get("column_values", [])
                    for col in column_values:
                        if col.get("type") == "status":
                            status_text = col.get("text", "N/A") or "N/A"
                            break

                    rich_table.add_row(
                        str(subitem.get("id", "")),
                        subitem.get("name", ""),
                        str(item_id),
                        status_text,
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
                rich_table.add_column("Status", style="yellow")
                rich_table.add_column("Group", style="blue")
                rich_table.add_column("Creator", style="magenta")
                rich_table.add_column("Created", style="dim")

                for subitem in all_subitems:
                    group_title = subitem.get("group", {}).get("title", "N/A") if subitem.get("group") else "N/A"
                    creator_name = subitem.get("creator", {}).get("name", "N/A") if subitem.get("creator") else "N/A"
                    created_at = subitem.get("created_at", "N/A")
                    if created_at != "N/A" and "T" in created_at:
                        created_at = created_at.split("T")[0]

                    # Extract status from column_values
                    status_text = "N/A"
                    column_values = subitem.get("column_values", [])
                    for col in column_values:
                        if col.get("type") == "status":
                            status_text = col.get("text", "N/A") or "N/A"
                            break

                    rich_table.add_row(
                        str(subitem.get("id", "")),
                        subitem.get("name", ""),
                        status_text,
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
    parent_item_id: Optional[int] = typer.Option(None, "--parent-item-id", "-p", help="ID of the parent item"),
    subitem_name: Optional[str] = typer.Option(None, "--name", "-n", help="Name of the new subitem"),
    column_values: Optional[str] = typer.Option(
        None,
        "--column-values",
        "-c",
        help='Column values as JSON string (e.g. \'{"status":{"index":1}}\')',
    ),
) -> None:
    """Create a new subitem under a parent item.

    Example:
        monday subitems create --parent-item-id 1234567890 --name "New Subtask"

        monday subitems create --parent-item-id 1234567890 --name "New Subtask" --column-values '{"status":{"index":1}}'
    """
    try:
        if parent_item_id is None:
            typer.secho(
                "Error: Parent item ID is required. Use --parent-item-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday subitems create --parent-item-id 1234567890 --name \"New Subtask\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        if subitem_name is None:
            typer.secho(
                "Error: Subitem name is required. Use --name",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday subitems create --parent-item-id 1234567890 --name \"New Subtask\"", fg=typer.colors.BLUE)
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


@subitems_app.command("list-columns")
def list_columns(
    subitem_id: Optional[int] = typer.Option(None, "--subitem-id", "-s", help="ID of the subitem"),
) -> None:
    """List all board columns for a subitem in an easy-to-use format.

    This command fetches all columns from the subitem's board, making it easy
    to see column IDs and types for use in update commands.

    Example:
        monday subitems list-columns --subitem-id 9999999999
    """
    try:
        if subitem_id is None:
            typer.secho(
                "Error: Subitem ID is required. Use --subitem-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday subitems list-columns --subitem-id 9999999999", fg=typer.colors.BLUE)
            raise typer.Exit(1)

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
    subitem_id: Optional[int] = typer.Option(None, "--subitem-id", "-s", help="ID of the subitem"),
) -> None:
    """List all available status columns and their options for a subitem's board.

    This command fetches the subitem's board and displays all status columns
    with their available status options.

    Example:
        monday subitems list-statuses --subitem-id 9999999999
    """
    try:
        if subitem_id is None:
            typer.secho(
                "Error: Subitem ID is required. Use --subitem-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday subitems list-statuses --subitem-id 9999999999", fg=typer.colors.BLUE)
            raise typer.Exit(1)

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


@subitems_app.command("update")
def update_subitem(
    subitem_id: Optional[int] = typer.Option(None, "--subitem-id", "-s", help="ID of the subitem"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Column title (e.g., 'Status', 'Github Issue Link')"),
    value: Optional[str] = typer.Option(None, "--value", "-v", help="Value to set"),
) -> None:
    """Update a subitem column value using human-readable column titles.

    This command automatically determines the column type and formats the value
    appropriately. Supports status, text, link, date, and other column types.

    Example:
        monday subitems update --subitem-id 9999999999 --title "Status" --value "Ready For Work"

        monday subitems update --subitem-id 9999999999 --title "Github Issue Link" --value "https://foo.com"

        monday subitems update --subitem-id 9999999999 --title "Due Date" --value "2024-12-31"
    """
    try:
        if subitem_id is None:
            typer.secho(
                "Error: Subitem ID is required. Use --subitem-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday subitems update --subitem-id 9999999999 --title \"Status\" --value \"Ready For Work\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        if title is None:
            typer.secho(
                "Error: Column title is required. Use --title",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday subitems update --subitem-id 9999999999 --title \"Status\" --value \"Ready For Work\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        if value is None:
            typer.secho(
                "Error: Value is required. Use --value",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday subitems update --subitem-id 9999999999 --title \"Status\" --value \"Ready For Work\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

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
            "itemId": str(subitem_id),
            "columnId": column_id,
            "value": formatted_value,
        }

        update_result = client.execute_mutation(CHANGE_COLUMN_VALUE, variables)
        updated_subitem = update_result.get("change_column_value")

        if updated_subitem:
            typer.secho(
                f"✓ Subitem column '{title}' updated to '{value}' successfully!",
                fg=typer.colors.GREEN
            )
            print_json(updated_subitem)
        else:
            typer.secho("Error: Failed to update subitem column", fg=typer.colors.RED)
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
