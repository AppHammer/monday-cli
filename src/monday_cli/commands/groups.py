"""Commands for managing Monday.com groups."""

import time
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import get_client, groups_app
from monday_cli.client.mutations import CREATE_GROUP, DELETE_GROUP
from monday_cli.client.queries import GET_BOARD_GROUPS
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json, secho_err

if TYPE_CHECKING:
    from monday_cli.client.graphql_client import MondayGraphQLClient


def _verify_group_deleted(
    client: "MondayGraphQLClient",
    board_id: int,
    group_id: str,
    attempts: int = 4,
    delay: float = 0.75,
) -> bool:
    """Confirm a group is absent from its board, tolerating read-after-delete lag.

    Re-queries ``GET_BOARD_GROUPS`` up to ``attempts`` times, returning ``True``
    as soon as the board is actually returned and the group no longer appears
    among its groups -- a genuine deletion, even when Monday's synchronous
    ``delete_group.deleted`` field reported ``false`` (an eventual-consistency
    artifact this command must not trust). Returns ``False`` if the group
    remains present across *every* attempt, i.e. the mutation was accepted but
    the group is genuinely still there rather than the read merely lagging --
    and also ``False`` if the board itself could never be read (an empty or
    missing ``boards`` response is a failed read, not evidence of deletion, so
    it must never be treated as "verified deleted").
    """
    for attempt in range(attempts):
        verify_result = client.execute_query(
            GET_BOARD_GROUPS,
            {"boardIds": [str(board_id)]},
        )
        verify_boards = verify_result.get("boards", [])
        if verify_boards:
            groups = verify_boards[0].get("groups", [])
            if not any(g.get("id") == group_id for g in groups):
                return True
        if attempt < attempts - 1:
            time.sleep(delay)
    return False


@groups_app.command("list")
def list_groups(
    board_id: int | None = typer.Option(None, "--board-id", "-b", help="ID of the board"),
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
            secho_err(
                "Error: Board ID is required. Use --board-id",
                fg=typer.colors.RED,
            )
            secho_err("Example: monday groups list --board-id 1234567890", fg=typer.colors.BLUE)
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
            secho_err(
                f"Board {board_id} not found or you don't have access to it.",
                fg=typer.colors.YELLOW,
            )
            secho_err(
                "Tip: Use 'monday boards list' to see available boards",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(0)

        board = boards[0]
        board_name = board.get("name", "Unknown")
        groups = board.get("groups", [])

        # Check if board has any groups
        if not groups:
            secho_err(
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
        secho_err(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        secho_err(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        secho_err(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        secho_err(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@groups_app.command("create")
def create_group(
    title: str = typer.Option(..., "--title", "-t", help="Title of the new group"),
    board_id: int = typer.Option(..., "--board-id", "-b", help="ID of the board"),
    color: str | None = typer.Option(None, "--color", "-c", help="Hex color code (e.g., #ff642e)"),
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
                secho_err(
                    "Error: Color must be a hex color code (e.g., #f09999 or #f09)",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            variables["groupColor"] = color

        # Execute mutation
        result = client.execute_query(CREATE_GROUP, variables)

        group = result.get("create_group")

        if not group:
            secho_err(
                "Error: Failed to create group. No data returned from API.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        # Success message
        secho_err(
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
        secho_err(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        secho_err(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        secho_err(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        secho_err(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
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
            secho_err(
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
            secho_err(
                f"Group with title '{title}' not found on board {board_id}",
                fg=typer.colors.YELLOW,
            )
            secho_err(
                "Tip: Use 'monday groups list --board-id {board_id}' to see available groups",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

        # Confirmation prompt
        if not confirm:
            secho_err(
                f"WARNING: This will delete group '{group_title}' and all its items!",
                fg=typer.colors.YELLOW,
            )
            confirm_delete = typer.confirm("Are you sure you want to continue?", err=True)
            if not confirm_delete:
                secho_err("Delete cancelled.", fg=typer.colors.BLUE)
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

            if deleted_group and deleted_group.get("id"):
                # AC-2: success is determined by a truthy `delete_group` result
                # (a non-null `id`), NOT the raw `delete_group.deleted` boolean.
                # Monday's synchronous API routinely returns `deleted: false`
                # even when the group is genuinely gone (eventual-consistency
                # lag), so forwarding that field produced a false-negative signal
                # while the ✓ message and exit 0 said success (FR-0014). We only
                # spend an extra verification re-query when the API itself did
                # not confirm the delete -- keeping the common happy path at zero
                # additional API calls.
                if deleted_group.get("deleted") or _verify_group_deleted(
                    client, board_id, str(group_id)
                ):
                    # AC-1: deleted:true, ✓, exit 0 -- all mutually consistent.
                    secho_err(
                        f"✓ Group '{group_title}' deleted successfully!",
                        fg=typer.colors.GREEN,
                    )
                    output = {
                        "group_id": deleted_group.get("id"),
                        "title": group_title,
                        "deleted": True,
                        "board_id": str(board_id),
                    }
                    print_json(output)
                else:
                    # AC-3: the mutation was accepted but the group is verifiably
                    # still present after a bounded re-query -- a genuine failure,
                    # not lag. Emit a trustworthy `deleted: false` on stdout,
                    # explain on stderr, and exit non-zero. No false positives.
                    secho_err(
                        f"Error: Group '{group_title}' is still present after the "
                        "delete attempt; it was not removed.",
                        fg=typer.colors.RED,
                    )
                    output = {
                        "group_id": deleted_group.get("id"),
                        "title": group_title,
                        "deleted": False,
                        "board_id": str(board_id),
                    }
                    print_json(output)
                    raise typer.Exit(1)
            else:
                secho_err(
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
                    group_still_exists = any(g.get("id") == group_id for g in verify_groups)

                    if not group_still_exists:
                        # Group was deleted despite the error
                        secho_err(
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
        secho_err(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        secho_err(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        secho_err(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except typer.Exit:
        # Let deliberate exits (success exit 0, the AC-3 verified-failure exit 1,
        # not-found exit 1) propagate unchanged. Without this, the catch-all
        # below -- typer.Exit subclasses RuntimeError/Exception -- would reclassify
        # them as an "Unexpected error" and mangle the exit-code contract.
        raise
    except Exception as e:
        secho_err(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
