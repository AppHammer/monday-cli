"""Commands for managing Monday.com status columns."""

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import get_client, statuses_app
from monday_cli.client.queries import GET_BOARD_COLUMNS
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


@statuses_app.command("list")
def list_statuses(
    board_id: Optional[int] = typer.Option(None, "--board-id", "-b", help="ID of the board"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table instead of JSON"),
) -> None:
    """List all available status columns and their options for a board.

    This command fetches all status columns from the specified board
    and displays their available status options.

    Example:
        monday statuses list --board-id 1234567890

        monday statuses list --board-id 1234567890 --table
    """
    try:
        if board_id is None:
            typer.secho(
                "Error: Board ID is required. Use --board-id",
                fg=typer.colors.RED,
            )
            typer.secho("Example: monday statuses list --board-id 1234567890", fg=typer.colors.BLUE)
            raise typer.Exit(1)

        client = get_client()

        # Get board columns with settings
        columns_result = client.execute_query(
            GET_BOARD_COLUMNS,
            {"boardIds": [str(board_id)]}
        )

        boards = columns_result.get("boards", [])
        if not boards:
            typer.secho(
                f"Board {board_id} not found or you don't have access",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        board_data = boards[0]
        board_name = board_data.get("name", "Unknown")
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

        # Output as table or JSON
        if table:
            console = Console()
            rich_table = Table(title=f"Status Columns for '{board_name}' (ID: {board_id})")

            rich_table.add_column("Column ID", style="cyan", no_wrap=True)
            rich_table.add_column("Column Title", style="green")
            rich_table.add_column("Index", style="yellow", justify="right")
            rich_table.add_column("Status Label", style="magenta")

            for col in status_columns:
                column_id = col["column_id"]
                column_title = col["column_title"]

                # Add a row for each status option
                for i, status in enumerate(col["statuses"]):
                    # Only show column info on first row
                    if i == 0:
                        rich_table.add_row(
                            column_id,
                            column_title,
                            str(status["index"]),
                            status["label"]
                        )
                    else:
                        rich_table.add_row(
                            "",  # Empty column ID
                            "",  # Empty column title
                            str(status["index"]),
                            status["label"]
                        )

            console.print(rich_table)
            typer.secho(f"\nTotal status columns: {len(status_columns)}", fg=typer.colors.BLUE)
        else:
            # Output results
            output = {
                "board_id": str(board_id),
                "board_name": board_name,
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
