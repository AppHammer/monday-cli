"""Commands for managing Monday.com boards."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import boards_app, get_client
from monday_cli.client.queries import GET_BOARDS
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


@boards_app.command("list")
def list_boards(
    limit: int = typer.Option(25, "--limit", "-l", help="Number of boards to return (max 100)"),
    page: int = typer.Option(1, "--page", "-p", help="Page number (starts at 1)"),
    state: Optional[str] = typer.Option(
        "active",
        "--state",
        "-s",
        help="Board state: active, archived, deleted, all",
    ),
    workspace_name: Optional[str] = typer.Option(None, "--workspace-name", "-w", help="Filter by workspace name"),
    workspace_id: Optional[int] = typer.Option(None, "--workspace-id", help="Filter by workspace ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table instead of JSON"),
) -> None:
    """List all boards available to you.

    By default, shows only active boards (not archived or deleted).
    Use --state to filter by board state.
    Use --workspace-name or --workspace-id to filter by workspace.

    Example:
        monday boards list

        monday boards list --limit 50

        monday boards list --state all

        monday boards list --state archived --page 2

        monday boards list --workspace-name "GENISIS-Demoboard"

        monday boards list --workspace-id 11890067

        monday boards list --table
    """
    try:
        # Validate state parameter
        valid_states = ["active", "archived", "deleted", "all"]
        if state and state.lower() not in valid_states:
            typer.secho(
                f"Error: Invalid state '{state}'. Valid options: {', '.join(valid_states)}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        # Validate limit
        if limit < 1 or limit > 100:
            typer.secho(
                "Error: Limit must be between 1 and 100",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        # Validate page
        if page < 1:
            typer.secho(
                "Error: Page must be 1 or greater",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        client = get_client()

        # Build variables
        variables = {
            "limit": limit,
            "page": page,
        }

        # Add state if not "all"
        if state and state.lower() != "all":
            variables["state"] = state.lower()

        # Add workspace_ids if workspace_id is specified (API-level filtering)
        if workspace_id:
            variables["workspace_ids"] = [str(workspace_id)]

        result = client.execute_query(GET_BOARDS, variables)

        boards = result.get("boards", [])

        # Filter by workspace name if specified (client-side filtering)
        # Note: API doesn't support filtering by workspace name, only by ID
        if workspace_name:
            boards = [
                board for board in boards
                if board.get("workspace") and board["workspace"].get("name", "").lower() == workspace_name.lower()
            ]

        if not boards:
            typer.secho("No boards found matching your criteria.", fg=typer.colors.YELLOW)
            typer.secho(
                "Tip: Try 'monday boards list --state all' to see archived boards",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(0)

        # Output as table or JSON
        if table:
            console = Console()
            rich_table = Table(title=f"Boards (Page {page}, Showing {len(boards)} of {limit} max)")

            rich_table.add_column("ID", style="cyan", no_wrap=True)
            rich_table.add_column("Name", style="green")
            rich_table.add_column("Workspace", style="blue")
            rich_table.add_column("WS ID", style="blue", no_wrap=True)
            rich_table.add_column("State", style="yellow")
            rich_table.add_column("Kind", style="magenta")
            rich_table.add_column("Items", justify="right", style="white")
            rich_table.add_column("Updated", style="dim")

            for board in boards:
                workspace = board.get("workspace", {})
                workspace_name = workspace.get("name", "N/A") if workspace else "N/A"
                workspace_id_str = str(workspace.get("id", "N/A")) if workspace else "N/A"
                updated_at = board.get("updated_at", "N/A")
                if updated_at != "N/A" and "T" in updated_at:
                    # Format to just date
                    updated_at = updated_at.split("T")[0]

                rich_table.add_row(
                    str(board.get("id", "")),
                    board.get("name", ""),
                    workspace_name,
                    workspace_id_str,
                    board.get("state", ""),
                    board.get("board_kind", ""),
                    str(board.get("items_count", 0)),
                    updated_at,
                )

            console.print(rich_table)
            typer.secho(f"\nTotal returned: {len(boards)}", fg=typer.colors.BLUE)
        else:
            # Format output with metadata
            output = {
                "boards": boards,
                "total_returned": len(boards),
                "page": page,
                "limit": limit,
            }

            if state:
                output["state_filter"] = state

            if workspace_name:
                output["workspace_name_filter"] = workspace_name

            if workspace_id:
                output["workspace_id_filter"] = workspace_id

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
