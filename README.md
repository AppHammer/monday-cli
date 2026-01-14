# Monday CLI

A command-line interface tool to interact with the Monday.com API. Built with Python and compiled to a standalone binary for Linux.

## Features

- **Item Management**: Get, create, and manage items on Monday.com boards
- **Subitem Operations**: Create subitems and update their status
- **Updates**: Post updates to items and subitems
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

#### Items

**Get item details:**
```bash
monday items get <ITEM_ID>
```

Example:
```bash
monday items get 1234567890
```

**Create a new item:**
```bash
monday items create <BOARD_ID> <ITEM_NAME> [OPTIONS]

Options:
  -g, --group-id TEXT        Group ID (optional)
  -c, --column-values TEXT   Column values as JSON (optional)
```

Examples:
```bash
# Simple item creation
monday items create 9876543210 "New Task"

# With group
monday items create 9876543210 "New Task" --group-id "topics"

# With column values
monday items create 9876543210 "New Task" --column-values '{"status":{"index":1},"date":"2026-01-15"}'
```

#### Subitems

**Create a subitem:**
```bash
monday subitems create <PARENT_ITEM_ID> <SUBITEM_NAME> [OPTIONS]

Options:
  -c, --column-values TEXT   Column values as JSON (optional)
```

Example:
```bash
monday subitems create 1234567890 "New Subtask"
monday subitems create 1234567890 "New Subtask" --column-values '{"status":{"index":1}}'
```

**Update subitem status:**
```bash
monday subitems update-status <SUBITEM_ID> <BOARD_ID> <COLUMN_ID> <STATUS_INDEX>
```

Example:
```bash
monday subitems update-status 9999999999 1234567890 status 1
```

Status index corresponds to the position in your status column (e.g., 0=Done, 1=Working, 2=Stuck).

#### Updates

**Create an update:**
```bash
monday updates create <ITEM_ID> <UPDATE_TEXT>
```

Examples:
```bash
# Update on an item
monday updates create 1234567890 "Work in progress"

# Update on a subitem (same command)
monday updates create 9999999999 "Completed subtask"
```

### Other Commands

**Show version:**
```bash
monday version
```

## Examples

### Get complete item information
```bash
monday items get 1234567890
```

Output:
```json
{
  "id": "1234567890",
  "name": "My Task",
  "state": "active",
  "board": {
    "id": "987654",
    "name": "My Board"
  },
  "column_values": [...],
  "updates": [...],
  "subitems": [...]
}
```

### Create item with status
```bash
monday items create 9876543210 "Implementation Task" \
  --column-values '{"status":{"index":1},"priority":{"index":0}}'
```

### Verbose mode for debugging
```bash
monday --verbose items get 1234567890
```

### Debug mode with full logging
```bash
monday --debug items get 1234567890
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

### v0.1.0 (2026-01-14)
- Initial release
- Item management (get, create)
- Subitem management (create, update status)
- Update management (create)
- Retry logic and rate limiting
- JSON output format
- Verbose and debug modes
