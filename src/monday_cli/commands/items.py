"""Commands for managing Monday.com items."""

import json
from typing import Optional

import typer

from monday_cli.cli import get_client, items_app
from monday_cli.client.mutations import CHANGE_COLUMN_VALUE, CREATE_ITEM
from monday_cli.client.queries import GET_BOARD_COLUMNS, GET_ITEM_BY_ID
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
