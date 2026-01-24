"""Commands for managing Monday.com groups."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import get_client, groups_app
from monday_cli.client.mutations import CREATE_GROUP, DELETE_GROUP
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


@groups_app.command("create")
def create_group(
    title: str = typer.Option(..., "--title", "-t", help="Title of the new group"),
    board_id: int = typer.Option(..., "--board-id", "-b", help="ID of the board"),
    color: Optional[str] = typer.Option(None, "--color", "-c", help="Hex color code (e.g., #ff642e)"),
) -> None:
    """Create a new group on a board.

    Creates a new empty group with the specified title and optional color.
    Groups are used to organize items on a board.

    Example:
        monday groups create --title "Group 3" --board-id 1234567890

        monday groups create --title "Group 3" --color "#f09999" --board-id 1234567890
    """
    try:
        client = get_client()

        # Build variables
        variables = {
            "boardId": str(board_id),
            "groupName": title,
        }

        # Add color if provided
        if color:
            # Validate hex color format
            if not color.startswith("#") or len(color) not in [4, 7]:
                typer.secho(
                    "Error: Color must be a hex color code (e.g., #f09999 or #f09)",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            variables["groupColor"] = color

        # Execute mutation
        result = client.execute_query(CREATE_GROUP, variables)

        group = result.get("create_group")

        if not group:
            typer.secho(
                "Error: Failed to create group. No data returned from API.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        # Success message
        typer.secho(
            f"✓ Group '{group.get('title')}' created successfully!",
            fg=typer.colors.GREEN,
        )

        # Output group details
        output = {
            "group_id": group.get("id"),
            "title": group.get("title"),
            "color": group.get("color"),
            "board_id": str(board_id),
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


@groups_app.command("delete")
def delete_group(
    title: str = typer.Option(..., "--title", "-t", help="Title of the group to delete"),
    board_id: int = typer.Option(..., "--board-id", "-b", help="ID of the board"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete a group from a board.

    Deletes a group and all of its items from the board.
    WARNING: This action cannot be undone!

    Example:
        monday groups delete --title "Group 3" --board-id 1234567890

        monday groups delete --title "Group 3" --board-id 1234567890 --confirm
    """
    try:
        client = get_client()

        # First, get the group ID by title
        result = client.execute_query(
            GET_BOARD_GROUPS,
            {"boardIds": [str(board_id)]},
        )

        boards = result.get("boards", [])

        if not boards:
            typer.secho(
                f"Board {board_id} not found or you don't have access to it.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        board = boards[0]
        groups = board.get("groups", [])

        # Find group by title
        group_id = None
        group_title = None
        for group in groups:
            if group.get("title", "").lower() == title.lower():
                group_id = group.get("id")
                group_title = group.get("title")
                break

        if not group_id:
            typer.secho(
                f"Group with title '{title}' not found on board {board_id}",
                fg=typer.colors.YELLOW,
            )
            typer.secho(
                "Tip: Use 'monday groups list --board-id {board_id}' to see available groups",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        # Confirmation prompt
        if not confirm:
            typer.secho(
                f"WARNING: This will delete group '{group_title}' and all its items!",
                fg=typer.colors.YELLOW,
            )
            confirm_delete = typer.confirm("Are you sure you want to continue?")
            if not confirm_delete:
                typer.secho("Delete cancelled.", fg=typer.colors.BLUE)
                raise typer.Exit(0)

        # Execute deletion
        try:
            delete_result = client.execute_query(
                DELETE_GROUP,
                {
                    "boardId": str(board_id),
                    "groupId": group_id,
                },
            )

            deleted_group = delete_result.get("delete_group")

            if deleted_group:
                # Success message
                typer.secho(
                    f"✓ Group '{group_title}' deleted successfully!",
                    fg=typer.colors.GREEN,
                )

                # Output deletion details
                output = {
                    "group_id": deleted_group.get("id"),
                    "title": group_title,
                    "deleted": deleted_group.get("deleted"),
                    "board_id": str(board_id),
                }

                print_json(output)
            else:
                typer.secho(
                    "Error: Failed to delete group. No data returned from API.",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)

        except MondayAPIError as api_err:
            # Check if it's an authorization error - sometimes the deletion happens
            # despite the error, so verify if group still exists
            if "unauthorized" in str(api_err).lower():
                # Verify deletion by checking if group still exists
                verify_result = client.execute_query(
                    GET_BOARD_GROUPS,
                    {"boardIds": [str(board_id)]},
                )
                verify_boards = verify_result.get("boards", [])
                if verify_boards:
                    verify_groups = verify_boards[0].get("groups", [])
                    group_still_exists = any(
                        g.get("id") == group_id for g in verify_groups
                    )

                    if not group_still_exists:
                        # Group was deleted despite the error
                        typer.secho(
                            f"✓ Group '{group_title}' deleted successfully!",
                            fg=typer.colors.GREEN,
                        )
                        output = {
                            "group_id": group_id,
                            "title": group_title,
                            "deleted": True,
                            "board_id": str(board_id),
                        }
                        print_json(output)
                        return

            # If we get here, deletion truly failed
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
