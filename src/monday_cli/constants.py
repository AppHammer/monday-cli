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

# Document write limits (FR-0005)
# Maximum bytes per add_content_to_doc_from_markdown call.
# Monday.com's CellLimitExceededException is observed around 40–50 KB of
# markdown payload. We set the safe threshold conservatively at 20 KB so each
# chunk stays well inside the limit even with overhead.
DOC_CHUNK_MAX_BYTES = 20_000  # 20 KB per chunk

# Maximum seconds to wait for a large doc-content write mutation. The default
# REQUEST_TIMEOUT (30 s) is too short for very large documents; this is used
# specifically for add_content_to_doc_from_markdown calls.
DOC_WRITE_TIMEOUT = 120  # seconds

# Maximum loop iterations (page=1 re-fetches) when clearing doc blocks.
# Each iteration fetches up to 100 blocks and issues up to 100 deletes.
# This bounds the number of round-trips, not the total deletes; see
# DOC_CLEAR_MAX_TOTAL_DELETES for the absolute delete cap.
DOC_CLEAR_MAX_ITERATIONS = 1_000

# Hard cap on the total number of blocks deleted in a single clear operation.
# Prevents an infinite-loop scenario where a silently-failing delete allows the
# loop to issue ~100,000 mutations before hitting DOC_CLEAR_MAX_ITERATIONS.
# 100 blocks/iteration × 1000 iterations = 100,000; we cap at 10,000 to give
# a clear error before anything pathological runs for hours.
DOC_CLEAR_MAX_TOTAL_DELETES = 10_000

# Maximum pages to scan when searching for a dedup sentinel in _doc_has_dedup_key.
# This is a page-based (1-indexed) bound, distinct from the iteration-based
# DOC_CLEAR_MAX_ITERATIONS used in _delete_all_doc_blocks.
DOC_SCAN_MAX_PAGES = 1_000

# Bounded retry for CREATE_DOC after a freshly-created item (eventual consistency).
# Monday's API can briefly return "Item not found" for items that were just created
# (BUG-2/FR-0015). When CREATE_DOC returns that specific transient error, the call
# is retried up to DOC_CREATE_RETRY_ATTEMPTS total times (not additional retries on
# top of an initial attempt — the first attempt counts toward this total).
# DOC_CREATE_RETRY_DELAY is the sleep between consecutive attempts.
# Non-transient errors are never retried; only "item not found" triggers this path.
DOC_CREATE_RETRY_ATTEMPTS = 4  # total attempts (1 initial + up to 3 retries) for CREATE_DOC
DOC_CREATE_RETRY_DELAY = 2.0  # seconds to wait between consecutive attempts
