"""Commands for managing Monday.com updates."""

from typing import Optional

import typer

from monday_cli.cli import get_client, updates_app
from monday_cli.client.mutations import CREATE_UPDATE
from monday_cli.client.queries import GET_ITEM_UPDATES
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


@updates_app.command("get")
def get_updates(
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the item"),
) -> None:
    """Get updates and replies for an item.

    Returns item basics (id, name, board, group) with all updates and their replies.
    Omits column values for a cleaner view focused on conversation.

    Example:
        monday updates get --item-id 1234567890
    """
    try:
        if item_id is None:
            typer.secho(
                "Error: Item ID is required. Use --item-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday updates get --item-id 1234567890", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        client = get_client()

        variables = {"itemIds": [str(item_id)]}
        result = client.execute_query(GET_ITEM_UPDATES, variables)

        items = result.get("items", [])
        if not items:
            typer.secho(f"No item found with ID {item_id}", fg=typer.colors.YELLOW)
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


@updates_app.command("create")
def create_update(
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the item or subitem"),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="Update text content"),
) -> None:
    """Create an update on an item or subitem.

    This command works for both regular items and subitems.

    Example:
        monday updates create --item-id 1234567890 --body "Work in progress"

        monday updates create --item-id 9999999999 --body "Completed subtask"
    """
    try:
        if item_id is None:
            typer.secho(
                "Error: Item ID is required. Use --item-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday updates create --item-id 1234567890 --body \"Work in progress\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        if body is None:
            typer.secho(
                "Error: Body text is required. Use --body",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday updates create --item-id 1234567890 --body \"Work in progress\"", fg=typer.colors.BLUE)
            raise typer.Exit(1)

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
