"""Commands for managing Monday.com items."""

import json
from typing import Optional

import typer

from monday_cli.cli import get_client, items_app
from monday_cli.client.mutations import CREATE_ITEM
from monday_cli.client.queries import GET_ITEM_BY_ID
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
