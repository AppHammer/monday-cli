"""Commands for managing Monday.com updates."""

import typer

from monday_cli.cli import get_client, updates_app
from monday_cli.client.mutations import CREATE_UPDATE
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


@updates_app.command("create")
def create_update(
    item_id: int = typer.Argument(..., help="ID of the item or subitem"),
    body: str = typer.Argument(..., help="Update text content"),
) -> None:
    """Create an update on an item or subitem.

    This command works for both regular items and subitems.

    Example:
        monday updates create 1234567890 "Work in progress"

        monday updates create 9999999999 "Completed subtask"
    """
    try:
        client = get_client()

        variables = {
            "itemId": str(item_id),
            "body": body,
        }

        result = client.execute_mutation(CREATE_UPDATE, variables)
        created_update = result.get("create_update")

        if created_update:
            typer.secho("✓ Update created successfully!", fg=typer.colors.GREEN)
            print_json(created_update)
        else:
            typer.secho("Error: Failed to create update", fg=typer.colors.RED)
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
