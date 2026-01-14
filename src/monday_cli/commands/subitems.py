"""Commands for managing Monday.com subitems."""

import json
from typing import Optional

import typer

from monday_cli.cli import get_client, subitems_app
from monday_cli.client.mutations import CHANGE_COLUMN_VALUE, CREATE_SUBITEM
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


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
