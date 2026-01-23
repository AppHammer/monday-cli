"""Commands for managing Monday.com groups."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import get_client, groups_app
from monday_cli.client.queries import GET_BOARD_GROUPS
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


@groups_app.command("list")
def list_groups(
    board_id: Optional[int] = typer.Option(None, "--board-id", "-b", help="ID of the board"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table instead of JSON"),
) -> None:
    """List all groups on a board.

    Shows group ID, title, color, and position for all groups on the specified board.
    Group IDs are used for creating items in specific groups or filtering items by group.

    Example:
        monday groups list --board-id 1234567890

        monday groups list --board-id 1234567890 --table
    """
    try:
        if board_id is None:
            typer.secho(
                "Error: Board ID is required. Use --board-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday groups list --board-id 1234567890", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        client = get_client()

        # Execute query to get board groups
        result = client.execute_query(
            GET_BOARD_GROUPS,
            {"boardIds": [str(board_id)]},
        )

        boards = result.get("boards", [])

        # Check if board exists
        if not boards:
            typer.secho(
                f"Board {board_id} not found or you don't have access to it.",
                fg=typer.colors.YELLOW,
            )
            typer.secho(
                "Tip: Use 'monday boards list' to see available boards",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(0)

        board = boards[0]
        board_name = board.get("name", "Unknown")
        groups = board.get("groups", [])

        # Check if board has any groups
        if not groups:
            typer.secho(
                f"No groups found on board '{board_name}' (ID: {board_id})",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(0)

        # Output as table or JSON
        if table:
            console = Console()
            rich_table = Table(title=f"Groups on '{board_name}' (Total: {len(groups)})")

            rich_table.add_column("ID", style="cyan", no_wrap=True)
            rich_table.add_column("Title", style="green")
            rich_table.add_column("Color", style="blue")
            rich_table.add_column("Position", justify="right", style="white")

            for group in groups:
                rich_table.add_row(
                    group.get("id", ""),
                    group.get("title", ""),
                    group.get("color", ""),
                    str(group.get("position", "")),
                )

            console.print(rich_table)
            typer.secho(f"\nTotal groups: {len(groups)}", fg=typer.colors.BLUE)
        else:
            # Format output with metadata
            output = {
                "board_id": str(board_id),
                "board_name": board_name,
                "groups": groups,
                "total_count": len(groups),
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
