# Claude Instructions for Monday CLI

This is a CLI tool for interacting with the Monday.com GraphQL API.

## Project Structure

```
src/monday_cli/
├── __init__.py          # Package init with version
├── main.py              # Main CLI entry point
├── client/
│   ├── client.py        # HTTP client with retry/rate limiting
│   ├── models.py        # Pydantic models for API responses
│   ├── queries.py       # GraphQL query templates
│   └── mutations.py     # GraphQL mutation templates
└── commands/
    ├── items.py         # Item management commands
    ├── subitems.py      # Subitem management commands
    └── updates.py       # Update management commands
```

## Monday.com API

### Authentication

Get your API token from: https://apphammer.monday.com/admin/integrations/api

Set the token as environment variable:
```bash
export MONDAY_API_TOKEN="your_token_here"
```

### API Endpoint

- Base URL: `https://api.monday.com/v2`
- All requests are POST with GraphQL body
- Authentication via `Authorization: your_api_token` header

### GraphQL Patterns

#### Queries

Items query requires `ID!` type (string, not int):
```graphql
query GetItem($itemIds: [ID!]!) {
  items(ids: $itemIds) {
    id
    name
    board { id name }
    column_values { id text value type }
  }
}
```

Board columns query (includes status settings):
```graphql
query GetBoardColumns($boardIds: [ID!]!) {
  boards(ids: $boardIds) {
    columns {
      id
      title
      type
      settings_str  # JSON string with status labels
    }
  }
}
```

#### Mutations

Create item:
```graphql
mutation CreateItem($boardId: ID!, $itemName: String!, $columnValues: JSON) {
  create_item(board_id: $boardId, item_name: $itemName, column_values: $columnValues) {
    id
    name
  }
}
```

Update column value (for status changes):
```graphql
mutation ChangeColumnValue($boardId: ID!, $itemId: ID!, $columnId: String!, $value: JSON!) {
  change_column_value(board_id: $boardId, item_id: $itemId, column_id: $columnId, value: $value) {
    id
  }
}
```

### Status Columns

Status columns have `settings_str` containing JSON with label mappings:
```json
{
  "labels": {
    "0": "Done",
    "1": "Working on it",
    "2": "Stuck"
  }
}
```

To update a status, use the index in the value:
```json
{"index": 1}  // Sets status to "Working on it"
```

### Rate Limiting

- Monday.com has complexity-based rate limiting
- Track complexity via `complexity { before after }` in queries
- CLI implements 60 calls/minute conservative limit
- Retry logic with exponential backoff (1s, 2s, 4s)

### Common Column Types

| Type | Description | Value Format |
|------|-------------|--------------|
| `status` | Status dropdown | `{"index": N}` |
| `text` | Plain text | `"string value"` |
| `date` | Date picker | `"YYYY-MM-DD"` |
| `numbers` | Numeric | `"123"` or `123` |
| `people` | Person picker | `{"personsAndTeams": [{"id": N, "kind": "person"}]}` |
| `dropdown` | Dropdown | `{"ids": [1, 2]}` |

## Development

### Build Binary

```bash
python build/build_binary.py
```

Creates standalone Linux binary at `dist/monday`.

### Run from Source

```bash
python -m monday_cli --help
```

### Testing

```bash
pytest
```

## CLI Framework

Uses Typer (v0.21.0+) with sub-commands:
- `monday items <command>` - Item operations
- `monday subitems <command>` - Subitem operations
- `monday updates <command>` - Update operations
- `monday version` - Show version

## Coding Guidelines

### Adding New Commands

1. **Choose the right file**: Add to existing command files based on the resource type:
   - `commands/items.py` - Item operations
   - `commands/subitems.py` - Subitem operations
   - `commands/updates.py` - Update operations
   - Create a new file only for entirely new resource types

2. **Command structure template**:
```python
@items_app.command("command-name")
def command_name(
    required_arg: int = typer.Argument(..., help="Description"),
    optional_arg: Optional[str] = typer.Option(None, "--flag", "-f", help="Description"),
) -> None:
    """Short description of what the command does.

    Example:
        monday items command-name 1234567890
    """
    try:
        client = get_client()
        # ... implementation ...
        print_json(result)

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
```

3. **Required imports for commands**:
```python
import json
from typing import Optional

import typer

from monday_cli.cli import get_client, items_app  # or subitems_app, updates_app
from monday_cli.client.mutations import CHANGE_COLUMN_VALUE, CREATE_ITEM
from monday_cli.client.queries import GET_BOARD_COLUMNS, GET_ITEM_BY_ID
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json
```

### Adding New GraphQL Operations

1. **Queries** go in `client/queries.py`:
```python
GET_SOMETHING = """
query GetSomething($ids: [ID!]!) {
  something(ids: $ids) {
    id
    name
  }
  complexity {
    before
    after
  }
}
"""
```

2. **Mutations** go in `client/mutations.py`:
```python
DO_SOMETHING = """
mutation DoSomething($id: ID!, $value: String!) {
  do_something(id: $id, value: $value) {
    id
  }
}
"""
```

3. **Always include complexity tracking** in queries for rate limit monitoring.

### ID Type Conventions

- **Monday.com IDs** are strings in GraphQL but often passed as integers from CLI
- Always convert to string when sending to API: `str(item_id)`
- Use `int` type hint for CLI arguments for better validation
- GraphQL uses `ID!` type which accepts strings

### Output Conventions

- Use `print_json()` for all data output (enables machine-readable output)
- Use `typer.secho()` for user messages:
  - Success: `fg=typer.colors.GREEN`
  - Warning/not found: `fg=typer.colors.YELLOW`
  - Error: `fg=typer.colors.RED`
- Use checkmark for success: `"✓ Action completed successfully!"`

### Error Handling Pattern

Always handle these exceptions in order:
1. `AuthenticationError` - Invalid API token
2. `RateLimitError` - Rate limit exceeded
3. `MondayAPIError` - API-specific errors
4. `Exception` - Catch-all for unexpected errors

Always `raise typer.Exit(1)` after error messages.

### Development Guidelines

- always use named arguments over positional for clarity
  `monday items get --item-id 123` instead of `monday items get 123`
- all `list` commands should support `--table` option for tabular output
- do not paginate results in CLI; fetch all and let user filter if needed
- standard commands `list`, `get`, `create`, `update`, `delete` for resources


### Testing Changes

```bash
# Run from source
python -m monday_cli --help
python -m monday_cli items --help

# Build and test binary
python build/build_binary.py
./dist/monday --help
```

### Style Guidelines

- Use kebab-case for command names: `list-columns`, `update-status`
- Use snake_case for function names: `list_columns`, `update_status`
- Include docstrings with examples for all commands
- Keep command help text concise but descriptive

## API Reference

- [Monday.com API Docs](https://developer.monday.com/api-reference/reference/about-the-api-reference)
- [GraphQL Guide](https://developer.monday.com/api-reference/docs/introduction-to-graphql)
- [Column Types](https://developer.monday.com/api-reference/docs/column-types-reference)
- [Rate Limits](https://developer.monday.com/api-reference/docs/rate-limits)
