"""Main CLI application for Monday CLI."""


import typer
from pydantic import ValidationError

from monday_cli.client.graphql_client import MondayGraphQLClient
from monday_cli.config import get_settings
from monday_cli.utils.logging import setup_logging
from monday_cli.utils.rate_limit import MondayRateLimiter

app = typer.Typer(
    name="monday",
    help="CLI tool to interact with Monday.com API",
    add_completion=False,
)

# Command groups
items_app = typer.Typer(help="Manage Monday.com items")
subitems_app = typer.Typer(help="Manage Monday.com subitems")
updates_app = typer.Typer(help="Manage Monday.com updates")

app.add_typer(items_app, name="items")
app.add_typer(subitems_app, name="subitems")
app.add_typer(updates_app, name="updates")

# Global state
_client: MondayGraphQLClient | None = None
_verbose: bool = False
_debug: bool = False


def get_client() -> MondayGraphQLClient:
    """Get or create Monday GraphQL client.

    Returns:
        Initialized GraphQL client

    Raises:
        typer.Exit: If client cannot be created
    """
    global _client

    if _client is None:
        try:
            settings = get_settings()
            rate_limiter = MondayRateLimiter(
                calls=settings.rate_limit_calls,
                period=settings.rate_limit_period,
            )
            _client = MondayGraphQLClient(
                api_token=settings.monday_api_token,
                api_url=settings.monday_api_url,
                rate_limiter=rate_limiter,
                retry_max_attempts=settings.retry_max_attempts,
                retry_backoff_factor=settings.retry_backoff_factor,
            )
        except ValidationError as e:
            typer.secho(
                "Error: Missing required configuration. Set MONDAY_API_TOKEN environment variable.",
                fg=typer.colors.RED,
            )
            if _debug:
                typer.secho(str(e), fg=typer.colors.RED)
            raise typer.Exit(1)
        except Exception as e:
            typer.secho(f"Error initializing client: {str(e)}", fg=typer.colors.RED)
            if _debug:
                raise
            raise typer.Exit(1)

    return _client


@app.callback()
def main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
) -> None:
    """Monday CLI - Interact with Monday.com API."""
    global _verbose, _debug
    _verbose = verbose
    _debug = debug
    setup_logging(verbose=verbose, debug=debug)


@app.command()
def version() -> None:
    """Show version information."""
    typer.echo("monday-cli version 0.1.0")


def main() -> None:
    """Main entry point."""
    try:
        app()
    finally:
        # Clean up client on exit
        global _client
        if _client is not None:
            _client.close()


if __name__ == "__main__":
    main()


# Import command modules to register commands (after all functions are defined)
from monday_cli.commands import items, subitems, updates  # noqa: F401, E402
