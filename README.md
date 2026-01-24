# Monday CLI

A command-line interface tool to interact with the Monday.com API. Built with Python and compiled to a standalone binary for Linux.

## Features

- **Workspace Management**: List and filter workspaces with membership filtering
- **Board Management**: List boards with state filtering (active, archived, deleted) and workspace filtering
- **Group Management**: List, create, and delete groups on boards
- **Item Management**: Full CRUD operations - get, create, update, list items with pagination and filtering
- **Subitem Operations**: Create, list, get, and update subitems with full column support
- **Status Management**: List available statuses and update item/subitem statuses using human-readable labels
- **Column Discovery**: List all board columns with their IDs, types, and available options
- **Updates**: Post updates to items and subitems
- **Document Management**: Create and read documents in Monday.com doc columns
- **Pagination Support**: Cursor-based pagination for items and subitems with configurable page sizes
- **Table Output**: Rich table formatting option for all list commands
- **Production Ready**: Includes retry logic, rate limiting, and comprehensive error handling
- **JSON Output**: Machine-readable JSON output for easy integration
- **Verbose Logging**: Debug mode for troubleshooting

## Installation

### From Binary (Recommended)

1. Download the latest binary from releases:
   ```bash
   wget https://github.com/AppHammer/monday-cli/releases/download/v0.1.0/monday
   ```

2. Make it executable:
   ```bash
   chmod +x monday
   ```

3. Move to your PATH:
   ```bash
   sudo mv monday /usr/local/bin/
   ```

### From Source

1. Clone the repository:
   ```bash
   git clone https://github.com/AppHammer/monday-cli.git
   cd monday-cli
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the CLI:
   ```bash
   python -m monday_cli --help
   ```

## Configuration

The CLI requires a Monday.com API token to authenticate. Get your API token from Monday.com:
1. Go to https://apphammer.monday.com/admin/integrations/api
2. Copy your API v2 token

Or navigate manually:
1. Go to Monday.com
2. Click your avatar → Admin → API
3. Copy your API v2 token

### Set Environment Variable

```bash
export MONDAY_API_TOKEN="your_api_token_here"
```

### Using .env File

Create a `.env` file in your working directory:

```bash
MONDAY_API_TOKEN=your_api_token_here
```

## Usage

### Global Options

```bash
monday [OPTIONS] COMMAND [ARGS]...

Options:
  -v, --verbose    Enable verbose output
  -d, --debug      Enable debug logging
  --help           Show help message
```

### Commands

#### Workspaces

**List workspaces:**
```bash
monday workspaces list [OPTIONS]

Options:
  -m, --membership-kind TEXT  Filter by membership (all, member) [default: all]
  -w, --workspace-ids TEXT    Comma-separated workspace IDs to filter
  -t, --table                 Output as table instead of JSON
```

Examples:
```bash
# List all workspaces
monday workspaces list

# List only workspaces you're a member of
monday workspaces list --membership-kind member

# Filter specific workspaces
monday workspaces list --workspace-ids "123,456"

# Table output
monday workspaces list --table
```

#### Boards

**List boards:**
```bash
monday boards list [OPTIONS]

Options:
  -s, --state TEXT          Board state (active, archived, deleted, all) [default: active]
  -w, --workspace-name TEXT Filter by workspace name (case-insensitive)
  --workspace-id TEXT       Filter by workspace ID
  -t, --table               Output as table instead of JSON
```

Examples:
```bash
# List all active boards
monday boards list

# List all boards including archived and deleted
monday boards list --state all

# Filter by workspace name
monday boards list --workspace-name "My Workspace"

# Filter by workspace ID
monday boards list --workspace-id 11890067

# Table output
monday boards list --table
```

#### Groups

**List groups:**
```bash
monday groups list --board-id <BOARD_ID> [OPTIONS]

Options:
  -b, --board-id TEXT  Board ID (required)
  -t, --table          Output as table instead of JSON
```

**Create a group:**
```bash
monday groups create --title <TITLE> --board-id <BOARD_ID> [OPTIONS]

Options:
  -t, --title TEXT     Group title (required)
  -b, --board-id TEXT  Board ID (required)
  -c, --color TEXT     Hex color code (e.g., #ff642e)
```

**Delete a group:**
```bash
monday groups delete --title <TITLE> --board-id <BOARD_ID> [OPTIONS]

Options:
  -t, --title TEXT     Group title (required)
  -b, --board-id TEXT  Board ID (required)
  -y, --confirm        Skip confirmation prompt
```

Examples:
```bash
# List all groups on a board
monday groups list --board-id 1234567890

# Create a new group
monday groups create --title "Sprint 2" --board-id 1234567890

# Create a group with color
monday groups create --title "Sprint 2" --color "#ff642e" --board-id 1234567890

# Delete a group
monday groups delete --title "Sprint 2" --board-id 1234567890 --confirm
```

#### Items

**Get item details:**
```bash
monday items get --item-id <ITEM_ID>

Options:
  -i, --item-id TEXT  Item ID (required)
```

Example:
```bash
monday items get --item-id 1234567890
```

**List items:**
```bash
monday items list <BOARD_ID> [OPTIONS]

Options:
  -b, --board-id TEXT  Board ID (alternative to positional argument)
  -l, --limit INT      Items per page (1-500) [default: 100]
  -a, --all            Fetch all items across all pages
  -c, --cursor TEXT    Pagination cursor for next page
  -g, --group TEXT     Filter by group title (case-insensitive)
  --group-id TEXT      Filter by group ID (exact match)
  -t, --table          Output as table instead of JSON
```

Examples:
```bash
# List items from a board
monday items list 1234567890

# List with pagination
monday items list --board-id 1234567890 --limit 50

# Fetch all items
monday items list --board-id 1234567890 --all

# Filter by group
monday items list --board-id 1234567890 --group "Topics"

# Continue from cursor
monday items list --board-id 1234567890 --cursor "MSw5NzI4MDA5MDAsaV9YcmxJb0p1..."

# Table output
monday items list --board-id 1234567890 --table
```

**Create a new item:**
```bash
monday items create --board-id <BOARD_ID> --name <ITEM_NAME> [OPTIONS]

Options:
  -b, --board-id TEXT       Board ID (required)
  -n, --name TEXT           Item name (required)
  -g, --group-id TEXT       Group ID (optional)
  -c, --column-values TEXT  Column values as JSON (optional)
```

Examples:
```bash
# Simple item creation
monday items create --board-id 9876543210 --name "New Task"

# With group
monday items create --board-id 9876543210 --name "New Task" --group-id "topics"

# With column values
monday items create --board-id 9876543210 --name "New Task" --column-values '{"status":{"index":1}}'
```

**Update item column value:**
```bash
monday items update --item-id <ITEM_ID> --title <COLUMN_TITLE> --value <VALUE>

Options:
  -i, --item-id TEXT  Item ID (required)
  -t, --title TEXT    Column title (required)
  -v, --value TEXT    Value to set (required)
```

Supports: status, text, link, date, numbers, and long-text columns. Auto-detects column type and formats appropriately.

Examples:
```bash
# Update status (case-insensitive label matching)
monday items update --item-id 1234567890 --title "Status" --value "Done"

# Update text field
monday items update --item-id 1234567890 --title "Description" --value "Updated description"

# Update link
monday items update --item-id 1234567890 --title "Github Issue Link" --value "https://github.com/user/repo/issues/123"

# Update date
monday items update --item-id 1234567890 --title "Due Date" --value "2024-12-31"
```

**List all board columns:**
```bash
monday items list-columns --item-id <ITEM_ID>

Options:
  -i, --item-id TEXT  Item ID (required)
```

This command shows all columns on the item's board with their IDs, types, and available options (for status columns).

Example:
```bash
monday items list-columns --item-id 1234567890
```

#### Statuses

**List available statuses for a board:**
```bash
monday statuses list --board-id <BOARD_ID> [OPTIONS]

Options:
  -b, --board-id TEXT  Board ID (required)
  -t, --table          Output as table instead of JSON
```

Shows all status columns and their available options with indices.

Examples:
```bash
# List all status columns
monday statuses list --board-id 1234567890

# Table output
monday statuses list --board-id 1234567890 --table
```

#### Subitems

**Get subitem details:**
```bash
monday subitems get --subitem-id <SUBITEM_ID>

Options:
  --subitem-id TEXT  Subitem ID (required)
```

**List subitems:**
```bash
monday subitems list [OPTIONS]

Options:
  -i, --item-id TEXT   Parent item ID
  -b, --board-id TEXT  Subitems board ID
  -l, --limit INT      Items per page (1-500) [default: 100]
  -a, --all            Fetch all subitems across all pages
  -c, --cursor TEXT    Pagination cursor for next page
  -t, --table          Output as table instead of JSON
```

Examples:
```bash
# List subitems from a parent item
monday subitems list --item-id 1234567890

# List all subitems from a board (with pagination)
monday subitems list --board-id 1234567890

# Fetch all subitems
monday subitems list --board-id 1234567890 --all

# Table output
monday subitems list --board-id 1234567890 --table
```

**Create a subitem:**
```bash
monday subitems create --parent-item-id <PARENT_ITEM_ID> --name <SUBITEM_NAME> [OPTIONS]

Options:
  -p, --parent-item-id TEXT  Parent item ID (required)
  -n, --name TEXT            Subitem name (required)
  -c, --column-values TEXT   Column values as JSON (optional)
```

Examples:
```bash
# Simple subitem creation
monday subitems create --parent-item-id 1234567890 --name "New Subtask"

# With column values
monday subitems create --parent-item-id 1234567890 --name "New Subtask" --column-values '{"status":{"index":1}}'
```

**Update subitem column value:**
```bash
monday subitems update --subitem-id <SUBITEM_ID> --title <COLUMN_TITLE> --value <VALUE>

Options:
  -s, --subitem-id TEXT  Subitem ID (required)
  -t, --title TEXT       Column title (required)
  -v, --value TEXT       Value to set (required)
```

Supports: status, text, link, date, numbers, and long-text columns. Auto-detects column type and formats appropriately.

Examples:
```bash
# Update status
monday subitems update --subitem-id 9999999999 --title "Status" --value "Ready For Work"

# Update link
monday subitems update --subitem-id 9999999999 --title "Github Issue Link" --value "https://foo.com"

# Update date
monday subitems update --subitem-id 9999999999 --title "Due Date" --value "2024-12-31"
```

**List all board columns:**
```bash
monday subitems list-columns --subitem-id <SUBITEM_ID>

Options:
  -s, --subitem-id TEXT  Subitem ID (required)
```

This command shows all columns on the subitem's board with their IDs, types, and available options (for status columns).

Example:
```bash
monday subitems list-columns --subitem-id 9999999999
```

**List available statuses:**
```bash
monday subitems list-statuses --subitem-id <SUBITEM_ID>

Options:
  -s, --subitem-id TEXT  Subitem ID (required)
```

This command shows only status columns with their available options.

Example:
```bash
monday subitems list-statuses --subitem-id 9999999999
```

#### Updates

**Create an update:**
```bash
monday updates create --item-id <ITEM_ID> --body <UPDATE_TEXT>

Options:
  -i, --item-id TEXT  Item or subitem ID (required)
  -b, --body TEXT     Update text content (required)
```

Examples:
```bash
# Update on an item
monday updates create --item-id 1234567890 --body "Work in progress"

# Update on a subitem (same command)
monday updates create --item-id 9999999999 --body "Completed subtask"
```

#### Docs

**Create a document in a doc column:**
```bash
monday docs create --item-id <ITEM_ID> --column-name <COLUMN_NAME> [OPTIONS]

Options:
  -i, --item-id TEXT      Item ID (required)
  -n, --column-name TEXT  Doc column name (required)
  -c, --content TEXT      Initial text content for the document (optional)
```

Examples:
```bash
# Create empty document
monday docs create --item-id 1234567890 --column-name "Monday Doc"

# Create document with initial content
monday docs create --item-id 1234567890 --column-name "Notes" --content "Meeting notes here"
```

**Get document content:**
```bash
monday docs get --item-id <ITEM_ID> --column-name <COLUMN_NAME>

Options:
  -i, --item-id TEXT      Item ID (required)
  -n, --column-name TEXT  Doc column name (required)
```

Retrieves all blocks from a document, including their type and content.

Example:
```bash
monday docs get --item-id 1234567890 --column-name "Monday Doc"
```

Output:
```json
{
  "id": "123456",
  "blocks": [
    {
      "id": "block-1",
      "type": "normal_text",
      "content": "{\"alignment\":\"left\",\"direction\":\"ltr\",\"deltaFormat\":[{\"insert\":\"Document content here\"}]}"
    }
  ]
}
```

### Other Commands

**Show version:**
```bash
monday version
```

## Examples

### Workspace and Board Discovery

```bash
# List all workspaces
monday workspaces list --table

# Find boards in a specific workspace
monday boards list --workspace-name "My Workspace" --table

# List all groups on a board
monday groups list --board-id 1234567890 --table
```

### Item Management Workflow

```bash
# List items with filtering
monday items list --board-id 1234567890 --group "Sprint 1" --table

# Get complete item information
monday items get --item-id 1234567890

# Create item with status
monday items create --board-id 9876543210 --name "Implementation Task" \
  --column-values '{"status":{"index":1}}'

# Update item status using human-readable label
monday items update --item-id 1234567890 --title "Status" --value "Done"

# Discover available columns and statuses
monday items list-columns --item-id 1234567890
monday statuses list --board-id 1234567890 --table
```

### Subitem Management

```bash
# Create subitem
monday subitems create --parent-item-id 1234567890 --name "Subtask 1"

# List subitems
monday subitems list --item-id 1234567890 --table

# Update subitem status
monday subitems update --subitem-id 9999999999 --title "Status" --value "In Progress"
```

### Pagination Examples

```bash
# List items with pagination (50 per page)
monday items list --board-id 1234567890 --limit 50

# Fetch all items automatically
monday items list --board-id 1234567890 --all

# Continue from a cursor
monday items list --board-id 1234567890 --cursor "MSw5NzI4MDA5MDAs..."
```

### Verbose mode for debugging
```bash
monday --verbose items get --item-id 1234567890
```

### Debug mode with full logging
```bash
monday --debug items get --item-id 1234567890
```

## Features in Detail

### Retry Logic
- Automatically retries failed requests
- Exponential backoff (1s, 2s, 4s, etc.)
- Maximum 3 attempts by default
- Retries on network errors and rate limits

### Rate Limiting
- Conservative 60 calls per minute
- Prevents hitting Monday.com API limits
- Automatic throttling when limit approached

### Error Handling
- Clear error messages for common issues
- Authentication errors
- Rate limit notifications
- Network connectivity issues
- API errors with full context

### Logging
- INFO level: Basic operation info
- DEBUG level: HTTP requests/responses, complexity tracking
- Verbose mode: Detailed operation flow

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MONDAY_API_TOKEN` | Monday.com API token (required) | - |
| `MONDAY_API_URL` | Monday.com API endpoint | https://api.monday.com/v2 |
| `LOG_LEVEL` | Logging level | INFO |
| `RETRY_MAX_ATTEMPTS` | Maximum retry attempts | 3 |
| `RETRY_BACKOFF_FACTOR` | Retry backoff multiplier | 2.0 |
| `RATE_LIMIT_CALLS` | Max API calls per period | 60 |
| `RATE_LIMIT_PERIOD` | Rate limit period (seconds) | 60 |

## Building from Source

### Build Binary

1. Install build dependencies:
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   ```

2. Run the build script:
   ```bash
   python build/build_binary.py
   ```

3. Binary will be created at `dist/monday`

### Run Tests

```bash
pytest
```

### Code Quality

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

## Troubleshooting

### "Invalid API token" error
- Ensure `MONDAY_API_TOKEN` is set correctly
- Verify the token is valid in Monday.com settings
- Check for extra spaces or quotes in the token

### "Rate limit exceeded" error
- Wait for the rate limit to reset (shown in error message)
- Reduce the frequency of API calls
- Configure a lower rate limit in environment variables

### "Item not found" error
- Verify the item ID is correct
- Ensure you have access to the board/item
- Check if the item was deleted

### Network errors
- Check your internet connection
- Verify Monday.com is accessible
- Try again with `--debug` for more details

## API Reference

This CLI interacts with Monday.com's GraphQL API v2. For more information:
- [Monday.com API Documentation](https://developer.monday.com/api-reference/reference/about-the-api-reference)
- [GraphQL Overview](https://developer.monday.com/api-reference/docs/introduction-to-graphql)
- [Rate Limits](https://developer.monday.com/api-reference/docs/rate-limits)

## License

MIT

## Contributing

Contributions are welcome! Please see CONTRIBUTING.md for details.

## Support

For issues and questions:
- GitHub Issues: https://github.com/AppHammer/monday-cli/issues
- Monday.com API Support: https://support.monday.com

## Changelog

### v0.2.0 (2026-01-24)
- **Workspace Management**: List workspaces with membership and ID filtering
- **Board Management**: List boards with state filtering (active, archived, deleted, all) and workspace filtering
- **Group Management**: List, create, and delete groups on boards with color support
- **Enhanced Item Management**:
  - List items with cursor-based pagination and group filtering
  - Update items using human-readable column titles (supports status, text, link, date, numbers, long-text)
  - Improved column discovery with status options
- **Enhanced Subitem Management**:
  - Get individual subitems
  - List subitems with pagination support (by item or board)
  - Update subitems using human-readable column titles
  - List columns and statuses for subitems
- **Status Management**: New dedicated statuses command group
- **Document Management**: Create and get documents in doc columns with content support
- **Table Output**: Rich table formatting for all list commands
- **Pagination**: Cursor-based pagination with `--all` flag for automatic fetching
- **Improved CLI**: All commands now use named arguments for clarity

### v0.1.0 (2026-01-14)
- Initial release
- Item management (get, create)
- Status management (list statuses, update status by label)
- Column discovery (list all board columns)
- Subitem management (create, update status)
- Update management (create)
- Retry logic and rate limiting
- JSON output format
- Verbose and debug modes
- GitHub Actions workflow for automated releases
