"""Commands for managing Monday.com workspaces."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from monday_cli.cli import get_client, workspaces_app
from monday_cli.client.queries import GET_WORKSPACES
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


@workspaces_app.command("list")
def list_workspaces(
    limit: int = typer.Option(100, "--limit", "-l", help="Number of workspaces to return"),
    membership_kind: Optional[str] = typer.Option(
        "all",
        "--membership-kind",
        "-m",
        help="Filter by membership: all, member",
    ),
    workspace_ids: Optional[str] = typer.Option(
        None,
        "--workspace-ids",
        "-w",
        help="Comma-separated workspace IDs to filter",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table instead of JSON"),
) -> None:
    """List all workspaces available to you.

    By default, shows all workspaces you have access to.
    Use --membership-kind to filter by membership type.

    Example:
        monday workspaces list

        monday workspaces list --limit 50

        monday workspaces list --membership-kind member

        monday workspaces list --workspace-ids "123,456"

        monday workspaces list --table
    """
    try:
        # Validate membership_kind parameter
        valid_membership_kinds = ["all", "member"]
        if membership_kind and membership_kind.lower() not in valid_membership_kinds:
            typer.secho(
                f"Error: Invalid membership-kind '{membership_kind}'. Valid options: {', '.join(valid_membership_kinds)}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        # Validate limit
        if limit < 1:
            typer.secho(
                "Error: Limit must be greater than 0",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        client = get_client()

        # Build variables
        variables = {
            "limit": limit,
        }

        # Add membership_kind if not "all"
        if membership_kind and membership_kind.lower() != "all":
            variables["membership_kind"] = membership_kind.lower()

        # Parse workspace IDs if provided
        if workspace_ids:
            try:
                ids = [id.strip() for id in workspace_ids.split(",")]
                variables["ids"] = ids
            except Exception as e:
                typer.secho(
                    f"Error: Invalid workspace IDs format: {str(e)}",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)

        result = client.execute_query(GET_WORKSPACES, variables)

        workspaces = result.get("workspaces", [])

        if not workspaces:
            typer.secho("No workspaces found matching your criteria.", fg=typer.colors.YELLOW)
            typer.secho(
                "Tip: Try 'monday workspaces list --membership-kind all' to see all accessible workspaces",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(0)

        # Output as table or JSON
        if table:
            console = Console()
            rich_table = Table(title=f"Workspaces (Showing {len(workspaces)})")

            rich_table.add_column("ID", style="cyan", no_wrap=True)
            rich_table.add_column("Name", style="green")
            rich_table.add_column("Kind", style="yellow")
            rich_table.add_column("Description", style="blue")
            rich_table.add_column("Account Product ID", style="magenta")

            for workspace in workspaces:
                account_product = workspace.get("account_product", {})
                account_product_info = "N/A"
                if account_product:
                    product_id = account_product.get("id", "")
                    product_kind = account_product.get("kind", "")
                    if product_id:
                        account_product_info = f"{product_id} ({product_kind})" if product_kind else product_id

                rich_table.add_row(
                    str(workspace.get("id", "")),
                    workspace.get("name", ""),
                    workspace.get("kind", ""),
                    workspace.get("description", "N/A") or "N/A",
                    account_product_info,
                )

            console.print(rich_table)
            typer.secho(f"\nTotal returned: {len(workspaces)}", fg=typer.colors.BLUE)
        else:
            # Format output with metadata
            output = {
                "workspaces": workspaces,
                "total_returned": len(workspaces),
                "limit": limit,
            }

            if membership_kind:
                output["membership_kind_filter"] = membership_kind

            if workspace_ids:
                output["workspace_ids_filter"] = workspace_ids

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
