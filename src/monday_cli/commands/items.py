"""Commands for managing Monday.com items."""

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import get_client, items_app
from monday_cli.client.mutations import (
    CHANGE_COLUMN_VALUE,
    CREATE_ITEM,
    DELETE_ITEM,
    MOVE_ITEM_TO_GROUP,
)
from monday_cli.client.queries import (
    GET_BOARD_COLUMNS,
    GET_BOARD_ITEMS,
    GET_ITEM_BY_ID,
    GET_NEXT_ITEMS_PAGE,
)
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json
from monday_cli.utils.resolve import (
    fetch_board_groups,
    format_groups_for_error,
    get_status_columns,
    resolve_group_ref,
)


@items_app.command("get")
def get_item(
    item_id: int | None = typer.Option(None, "--item-id", "-i", help="ID of the item to retrieve"),
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
    board_id: int | None = typer.Option(
        None, "--board-id", "-b", help="ID of the board to create item on"
    ),
    item_name: str | None = typer.Option(None, "--name", "-n", help="Name of the new item"),
    group: str | None = typer.Option(
        None, "--group", "-g", help="Group title OR id (auto-detected; optional)"
    ),
    group_id: str | None = typer.Option(
        None, "--group-id", help="Group id (id-only, long option; optional)"
    ),
    column_values: str | None = typer.Option(
        None,
        "--column-values",
        "-c",
        help='Column values as JSON string (e.g. \'{"status":{"index":1}}\')',
    ),
) -> None:
    """Create a new item on a board.

    Place the item in a group with -g/--group (accepts a group TITLE or id,
    auto-detected) or --group-id (id-only). The two are mutually exclusive;
    -g means the same "title or id" across items list / create / move.

    Example:
        monday items create --board-id 1234567890 --name "New Task"

        monday items create --board-id 1234567890 --name "New Task" --group "Topics"

        monday items create --board-id 1234567890 --name "New Task" -g "topics"

        monday items create --board-id 1234567890 --name "New Task" --group-id "topics"

        monday items create --board-id 1234567890 --name "New Task" \
            --column-values '{"status":{"index":1}}'
    """
    try:
        if board_id is None:
            typer.secho(
                "Error: Board ID is required. Use --board-id",
                fg=typer.colors.RED,
            )
            typer.secho(
                'Example: monday items create --board-id 1234567890 --name "New Task"',
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        if item_name is None:
            typer.secho(
                "Error: Item name is required. Use --name",
                fg=typer.colors.RED,
            )
            typer.secho(
                'Example: monday items create --board-id 1234567890 --name "New Task"',
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        if group and group_id:
            typer.secho(
                "Error: Cannot use both --group and --group-id together. Choose one.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        client = get_client()

        # Resolve the destination group id.
        #   --group-id : id-only, used as-is (no resolution).
        #   -g/--group : title OR id, auto-detected via the shared resolver
        #                (widened from id-only in v0.6.3; ids still work).
        resolved_group_id = group_id
        if group:
            resolved_group, groups = resolve_group_ref(client, str(board_id), group)
            if resolved_group is None:
                typer.secho(
                    f"Error: No group matching '{group}' on board {board_id}",
                    fg=typer.colors.RED,
                )
                typer.secho(
                    f"Available groups: {format_groups_for_error(groups)}",
                    fg=typer.colors.YELLOW,
                )
                typer.secho(
                    "Example: monday items create --board-id "
                    f'{board_id} --name "New Task" --group "Topics"',
                    fg=typer.colors.BLUE,
                )
                raise typer.Exit(1)
            resolved_group_id = resolved_group["id"]

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

        if resolved_group_id:
            variables["groupId"] = resolved_group_id

        result = client.execute_mutation(CREATE_ITEM, variables)
        created_item = result.get("create_item")

        if created_item:
            typer.secho("✓ Item created successfully!", fg=typer.colors.GREEN)
            print_json(created_item)
        else:
            typer.secho("Error: Failed to create item", fg=typer.colors.RED)
            raise typer.Exit(1)

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


@items_app.command("update")
def update_item(
    item_id: int | None = typer.Option(None, "--item-id", "-i", help="ID of the item"),
    title: str | None = typer.Option(
        None, "--title", "-t", help="Column title (e.g., 'Status', 'Github Issue Link')"
    ),
    value: str | None = typer.Option(None, "--value", "-v", help="Value to set"),
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
            typer.secho(
                'Example: monday items update --item-id 1234567890 --title "Status" --value "Done"',
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        if title is None:
            typer.secho(
                "Error: Column title is required. Use --title",
                fg=typer.colors.RED,
            )
            typer.secho(
                'Example: monday items update --item-id 1234567890 --title "Status" --value "Done"',
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        if value is None:
            typer.secho(
                "Error: Value is required. Use --value",
                fg=typer.colors.RED,
            )
            typer.secho(
                'Example: monday items update --item-id 1234567890 --title "Status" --value "Done"',
                fg=typer.colors.BLUE,
            )
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
        columns_result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [board_id]})

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
                fg=typer.colors.RED,
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
                    fg=typer.colors.RED,
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
                    f"Error: Status '{value}' not found in column '{title}'", fg=typer.colors.RED
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
                f"✓ Item column '{title}' updated to '{value}' successfully!", fg=typer.colors.GREEN
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
    item_id: int | None = typer.Option(None, "--item-id", "-i", help="ID of the item"),
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
            typer.secho(
                "Example: monday items list-columns --item-id 1234567890", fg=typer.colors.BLUE
            )
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
        columns_result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [board_id]})

        boards = columns_result.get("boards", [])
        if not boards:
            typer.secho("Error: Could not fetch board columns", fg=typer.colors.RED)
            raise typer.Exit(1)

        board_data = boards[0]
        columns = board_data.get("columns", [])

        # Format columns for easy consumption
        formatted_columns = []
        for col in columns:
            column_info = {"column_id": col["id"], "title": col["title"], "type": col["type"]}

            # Add status options for status columns
            if col.get("type") == "status" and col.get("settings_str"):
                try:
                    settings = json.loads(col["settings_str"])
                    labels = settings.get("labels", {})
                    status_options = [
                        {"index": int(idx), "label": label} for idx, label in labels.items()
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
            "columns": formatted_columns,
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
    board_id: int | None = typer.Argument(None, help="ID of the board to list items from"),
    board_id_opt: int | None = typer.Option(
        None, "--board-id", "-b", help="ID of the board to list items from"
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Items per page (max 500)"),
    all_pages: bool = typer.Option(False, "--all", "-a", help="Fetch all items across all pages"),
    cursor: str | None = typer.Option(
        None, "--cursor", "-c", help="Pagination cursor for next page"
    ),
    group: str | None = typer.Option(
        None, "--group", "-g", help="Filter by group TITLE or id (auto-detected)"
    ),
    group_id: str | None = typer.Option(
        None, "--group-id", help="Filter by group id (id-only, exact match)"
    ),
    status: str | None = typer.Option(
        None, "--status", "-s", help="Filter by status label (case-insensitive)"
    ),
    status_column: str | None = typer.Option(
        None,
        "--status-column",
        help="Which status column to filter on (required when a board has more than one)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table instead of JSON"),
) -> None:
    """List all items/tasks from a board.

    Lists main items (tasks) from regular boards only. This command will NOT list
    subitems - use 'monday subitems list' for that.

    Returns items with pagination support. By default, returns the first 100 items.
    Use --cursor to get the next page, or --all to fetch all items automatically.

    A group and/or status filter (-g/--group, --group-id, --status) ALWAYS scans
    the entire board internally first, even without --all, so a non-empty
    group/status match can never be missed just because it lives on page 2+ (a
    filtered query implies a full scan). When a filter forces this internal full
    scan, the JSON `cursor` is null and `has_more` is false (pagination is
    exhausted); without any filter, normal single-page pagination is unchanged.

    Filter by group using -g/--group (accepts a group TITLE or id, auto-detected)
    or --group-id (id-only, exact match). Passing a group id to -g returns exactly
    what --group-id with the same id returns. An unknown group -- via EITHER flag
    -- is a teaching error (exit 1) listing the board's available groups; a
    valid-but-empty group returns items: [] (exit 0). The resolved group id is
    always echoed under the stable `group_id_filter` JSON key, regardless of
    which flag matched it (`group_filter` is also kept, raw, for -g).

    Filter by status with --status "<label>" (case-insensitive). If the board has
    more than one status column you must name it with --status-column "<title>"
    (otherwise a teaching error lists the choices). --status composes with the
    group filter as a logical AND. Use 'monday groups list' / 'monday statuses
    list' to see available groups and status labels.

    Column values are included by default for complete data export.

    Example:
        monday items list 1234567890

        monday items list --board-id 1234567890

        monday items list --board-id 1234567890 --limit 50

        monday items list --board-id 1234567890 --all

        monday items list --board-id 1234567890 --group "Topics"

        monday items list --board-id 1234567890 --group "topics"

        monday items list --board-id 1234567890 --group-id "topics"

        monday items list --board-id 1234567890 --group "Topics" --all

        monday items list --board-id 1234567890 --status "Done"

        monday items list --board-id 1234567890 --status "High" --status-column "Priority"

        monday items list --board-id 1234567890 --status "Done" --group "In Progress" --all

        monday items list --board-id 1234567890 \
            --cursor "MSw5NzI4MDA5MDAsaV9YcmxJb0p1VEdYc1VWeGlxeF9kLDg4MiwzNXw0MTQ1NzU1MTE5"

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

        # A group and/or status filter forces an internal full-board scan
        # below: filtering only the fetched page would let a non-empty
        # group/status whose matches live beyond page 1 come back as
        # items: [] -- indistinguishable from a genuinely empty group.
        filter_active = bool(group or group_id or status)

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
                "The 'items list' command is for listing main items/tasks"
                " from regular boards only.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        items_page = board.get("items_page", {})
        all_items = items_page.get("items", [])
        next_cursor = items_page.get("cursor")

        # Fetch every remaining page when the caller asked for --all OR when a
        # group/status filter is active (a filtered query implies a full
        # scan -- see `filter_active` above). Progress messages are only
        # printed for an explicit --all; a scan forced internally by a filter
        # must stay invisible so stdout remains clean, parseable JSON.
        pages_fetched = 1
        scan_all = all_pages or filter_active
        if scan_all and next_cursor:
            if all_pages:
                typer.secho(
                    f"Fetching page {pages_fetched}... ({len(all_items)} items)",
                    fg=typer.colors.BLUE,
                )

            while next_cursor:
                pages_fetched += 1
                if all_pages:
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

                if all_pages:
                    typer.secho(
                        f"  Total items so far: {len(all_items)}",
                        fg=typer.colors.BLUE,
                    )

                # Safety check to prevent infinite loops
                if pages_fetched > 1000:
                    if all_pages:
                        typer.secho(
                            "Warning: Reached maximum page limit (1000). Stopping pagination.",
                            fg=typer.colors.YELLOW,
                        )
                    break

        # Apply group filtering if specified (client-side, over the fully
        # scanned item set fetched above when a filter is active).
        #   --group-id : id-only, exact match, validated against the board's
        #     real groups so an unknown id teaches instead of silently
        #     returning items: [].
        #   -g/--group : title OR id, resolved via the shared resolver so that
        #     `-g <id>` filters on the SAME group.id path as `--group-id <id>`.
        # Empty vs unknown are distinguishable: an unknown group value (either
        # flag) is a teaching error (exit 1); a valid-but-empty group falls
        # through to items: [] (exit 0).
        resolved_group_id: str | None = None
        if group_id:
            groups = fetch_board_groups(client, str(final_board_id))
            group_ids = {g.get("id") for g in groups}
            if group_id not in group_ids:
                typer.secho(
                    f"Error: No group matching '{group_id}' on board {final_board_id}",
                    fg=typer.colors.RED,
                )
                typer.secho(
                    f"Available groups: {format_groups_for_error(groups)}",
                    fg=typer.colors.YELLOW,
                )
                example_id = groups[0]["id"] if groups else "group_abc123"
                typer.secho(
                    f"Example: monday items list --board-id {final_board_id} "
                    f'--group-id "{example_id}"',
                    fg=typer.colors.BLUE,
                )
                raise typer.Exit(1)
            resolved_group_id = group_id
            all_items = [
                item
                for item in all_items
                if item.get("group") and item["group"].get("id") == resolved_group_id
            ]
        elif group:
            resolved_group, groups = resolve_group_ref(client, str(final_board_id), group)
            if resolved_group is None:
                typer.secho(
                    f"Error: No group matching '{group}' on board {final_board_id}",
                    fg=typer.colors.RED,
                )
                typer.secho(
                    f"Available groups: {format_groups_for_error(groups)}",
                    fg=typer.colors.YELLOW,
                )
                typer.secho(
                    f'Example: monday items list --board-id {final_board_id} --group "Topics"',
                    fg=typer.colors.BLUE,
                )
                raise typer.Exit(1)
            resolved_group_id = resolved_group["id"]
            all_items = [
                item
                for item in all_items
                if item.get("group") and item["group"].get("id") == resolved_group_id
            ]

        # Apply status filtering if specified (client-side, composes with the
        # group filter above as a logical AND). Resolves which status column to
        # target and validates the label against that column only (C1-C4).
        resolved_status_column_title: str | None = None
        if status:
            status_columns = get_status_columns(client, str(final_board_id))

            chosen_column: dict[str, Any] | None
            if status_column:
                chosen_column = next(
                    (c for c in status_columns if c["title"].lower() == status_column.lower()),
                    None,
                )
                if chosen_column is None:
                    valid = ", ".join(f"'{c['title']}'" for c in status_columns) or "(none)"
                    typer.secho(
                        f"Error: '{status_column}' is not a status column on "
                        f"board {final_board_id}",
                        fg=typer.colors.RED,
                    )
                    typer.secho(f"Available status columns: {valid}", fg=typer.colors.YELLOW)
                    typer.secho(
                        f"Example: monday items list --board-id {final_board_id} "
                        f'--status "Done" --status-column "Status"',
                        fg=typer.colors.BLUE,
                    )
                    raise typer.Exit(1)
            elif len(status_columns) == 1:
                chosen_column = status_columns[0]
            elif len(status_columns) == 0:
                typer.secho(
                    f"Error: Board {final_board_id} has no status columns to filter on.",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            else:
                titles = ", ".join(f"'{c['title']}'" for c in status_columns)
                typer.secho(
                    f"Error: Board {final_board_id} has multiple status columns; "
                    "specify which one with --status-column.",
                    fg=typer.colors.RED,
                )
                typer.secho(f"Status columns: {titles}", fg=typer.colors.YELLOW)
                typer.secho(
                    f"Example: monday items list --board-id {final_board_id} "
                    f'--status "{status}" --status-column "{status_columns[0]["title"]}"',
                    fg=typer.colors.BLUE,
                )
                raise typer.Exit(1)

            # Validate the label against the chosen column's labels only.
            labels = chosen_column["labels"]
            status_lower = status.lower()
            if not any((label or "").lower() == status_lower for label in labels.values()):
                available = ", ".join(f"'{label}'" for label in labels.values()) or "(none)"
                typer.secho(
                    f"Error: Status '{status}' not found in column " f"'{chosen_column['title']}'",
                    fg=typer.colors.RED,
                )
                typer.secho(f"Available statuses: {available}", fg=typer.colors.YELLOW)
                typer.secho(
                    f"Example: monday items list --board-id {final_board_id} "
                    f'--status "{next(iter(labels.values()), "Done")}" '
                    f'--status-column "{chosen_column["title"]}"',
                    fg=typer.colors.BLUE,
                )
                raise typer.Exit(1)

            resolved_status_column_title = chosen_column["title"]
            column_id = chosen_column["id"]

            def _matches_status(item: dict[str, Any]) -> bool:
                for cv in item.get("column_values", []):
                    if cv.get("id") == column_id:
                        text = cv.get("text") or ""
                        # Unset status (blank text) is excluded from a positive match.
                        return text.strip() != "" and text.lower() == status_lower
                return False

            all_items = [item for item in all_items if _matches_status(item)]

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
            rich_table.add_column("Group ID", style="blue", no_wrap=True)
            rich_table.add_column("Creator", style="magenta")
            rich_table.add_column("Created", style="dim")

            for item in all_items:
                item_group = item.get("group") or {}
                group_title = item_group.get("title", "N/A") or "N/A"
                group_id_cell = item_group.get("id", "N/A") or "N/A"
                creator_name = (
                    item.get("creator", {}).get("name", "N/A") if item.get("creator") else "N/A"
                )
                created_at = item.get("created_at", "N/A")
                if created_at != "N/A" and "T" in created_at:
                    # Format to just date
                    created_at = created_at.split("T")[0]

                rich_table.add_row(
                    str(item.get("id", "")),
                    item.get("name", ""),
                    item.get("state", ""),
                    group_title,
                    group_id_cell,
                    creator_name,
                    created_at,
                )

            console.print(rich_table)

            # Show summary info
            if all_pages:
                typer.secho(
                    f"\nTotal items: {len(all_items)} (fetched {pages_fetched} pages)",
                    fg=typer.colors.BLUE,
                )
            else:
                if next_cursor:
                    typer.secho(
                        f"\nShowing {len(all_items)} items. "
                        "Use --cursor to get next page or --all to fetch all items.",
                        fg=typer.colors.BLUE,
                    )
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

            # Add filter metadata if used (reflects ALL active filters). The
            # RESOLVED group id is always surfaced under the single stable
            # `group_id_filter` key regardless of which flag matched it, so an
            # agent can rely on one key; the raw `group_filter` (-g input) is
            # preserved unchanged for backward compatibility -- nothing is
            # renamed or removed, only added.
            if group:
                output["group_filter"] = group
            if resolved_group_id:
                output["group_id_filter"] = resolved_group_id
            if status:
                output["status_filter"] = status
                output["status_column"] = resolved_status_column_title

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


@items_app.command("move")
def move_item(
    item_id: int | None = typer.Option(None, "--item-id", "-i", help="ID of the item to move"),
    group: str | None = typer.Option(
        None, "--group", "-g", help="Destination group TITLE or id (auto-detected)"
    ),
    group_id: str | None = typer.Option(
        None, "--group-id", help="Destination group id (id-only, long option)"
    ),
) -> None:
    """Move an item to another group on its own board.

    Resolve the destination with -g/--group (accepts a group TITLE or id,
    auto-detected — same rule as items list / create) or --group-id (id-only).
    The two are mutually exclusive. The group is resolved against the item's
    OWN board. Moving an item to the group it is already in is a safe no-op
    (exit 0, same JSON shape). Subitems cannot be moved this way.

    Example:
        monday items move --item-id 1234567890 --group-id group_abc

        monday items move --item-id 1234567890 --group "In Progress"

        monday items move --item-id 1234567890 -g topics
    """
    try:
        if item_id is None:
            typer.secho("Error: Item ID is required. Use --item-id", fg=typer.colors.RED)
            typer.secho(
                'Example: monday items move --item-id 1234567890 --group "In Progress"',
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        if group and group_id:
            typer.secho(
                "Error: Cannot use both --group and --group-id together. Choose one.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        if not group and not group_id:
            typer.secho(
                "Error: A destination group is required. Use --group or --group-id",
                fg=typer.colors.RED,
            )
            typer.secho(
                'Example: monday items move --item-id 1234567890 --group "In Progress"',
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        client = get_client()

        # Fetch the item to learn its board and current group.
        result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(item_id)]})
        items = result.get("items", [])
        if not items:
            typer.secho(f"Item {item_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        item = items[0]
        board = item.get("board") or {}
        board_id = board.get("id")
        board_name = board.get("name", "") or ""

        if not board_id:
            typer.secho("Error: Could not determine board for item", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Reject subitems — moving a subitem between groups is out of scope.
        if "subitems of" in board_name.lower():
            typer.secho(
                f"Error: Item {item_id} is a subitem; moving subitems between "
                "groups is not supported.",
                fg=typer.colors.RED,
            )
            typer.secho(
                "Only main items on a regular board can be moved with 'items move'.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        # Resolve the destination group on the item's own board.
        if group_id:
            resolved_group_id = group_id
        else:
            resolved_group, groups = resolve_group_ref(client, str(board_id), group or "")
            if resolved_group is None:
                typer.secho(
                    f"Error: No group matching '{group}' on board {board_id}",
                    fg=typer.colors.RED,
                )
                typer.secho(
                    f"Available groups: {format_groups_for_error(groups)}",
                    fg=typer.colors.YELLOW,
                )
                typer.secho(
                    f'Example: monday items move --item-id {item_id} --group "In Progress"',
                    fg=typer.colors.BLUE,
                )
                raise typer.Exit(1)
            resolved_group_id = resolved_group["id"]

        # A4 — idempotent no-op: already in the target group.
        current_group = item.get("group") or {}
        if current_group.get("id") == resolved_group_id:
            typer.secho(
                f"✓ Item {item_id} is already in group '{current_group.get('title')}' "
                f"({resolved_group_id}); no move needed.",
                fg=typer.colors.GREEN,
            )
            print_json(
                {
                    "id": str(item.get("id")),
                    "name": item.get("name"),
                    "group": current_group,
                    "board": {"id": str(board_id), "name": board_name},
                    "moved": False,
                }
            )
            return

        # Perform the move.
        try:
            move_result = client.execute_mutation(
                MOVE_ITEM_TO_GROUP,
                {"itemId": str(item_id), "groupId": resolved_group_id},
            )
        except MondayAPIError as e:
            groups = fetch_board_groups(client, str(board_id))
            typer.secho(f"API Error: could not move item {item_id}: {str(e)}", fg=typer.colors.RED)
            typer.secho(
                f"Available groups on board {board_id}: {format_groups_for_error(groups)}",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        moved = move_result.get("move_item_to_group")
        if not moved:
            typer.secho(f"Error: Failed to move item {item_id}", fg=typer.colors.RED)
            raise typer.Exit(1)

        moved_group = moved.get("group") or {}
        typer.secho(
            f"✓ Item {item_id} moved to group '{moved_group.get('title')}' "
            f"({moved_group.get('id')})",
            fg=typer.colors.GREEN,
        )
        print_json(
            {
                "id": str(moved.get("id")),
                "name": moved.get("name"),
                "group": moved_group,
                "board": moved.get("board") or {"id": str(board_id), "name": board_name},
                "moved": True,
            }
        )

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
    item_id: int | None = typer.Option(None, "--item-id", "-i", help="ID of the item to delete"),
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
                f"WARNING: This will permanently delete item '{item_name}'"
                f" (ID: {item_id}) from board '{board_name}'!",
                fg=typer.colors.YELLOW,
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
                f"✓ Item '{item_name}' (ID: {item_id}) deleted successfully!", fg=typer.colors.GREEN
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
                    fg=typer.colors.GREEN,
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
