"""Constants for Monday.com CLI."""

# API Configuration
MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_API_VERSION = "2024-01"

# Rate Limiting
DEFAULT_RATE_LIMIT_CALLS = 60
DEFAULT_RATE_LIMIT_PERIOD = 60  # seconds
COMPLEXITY_WARNING_THRESHOLD = 1_000_000  # Warn if less than 1M complexity remaining

# Retry Configuration
DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_FACTOR = 2.0
DEFAULT_RETRY_MIN_WAIT = 1  # seconds
DEFAULT_RETRY_MAX_WAIT = 60  # seconds

# Logging
DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# HTTP Configuration
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "monday-cli/0.1.0"
