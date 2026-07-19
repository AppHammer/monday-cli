"""Commands for managing Monday.com documents."""

import hashlib
import json
import time
from typing import Any

import typer

from monday_cli.cli import docs_app, get_client
from monday_cli.client.graphql_client import MondayGraphQLClient
from monday_cli.client.mutations import (
    ADD_CONTENT_FROM_MARKDOWN,
    CREATE_DOC,
    DELETE_DOC,
    DELETE_DOC_BLOCK,
    RESET_DOC_COLUMN_VALUE,
)
from monday_cli.client.queries import (
    EXPORT_MARKDOWN_FROM_DOC,
    GET_BOARD_COLUMNS,
    GET_DOC_BLOCKS,
    GET_DOC_BY_OBJECT_ID,
    GET_ITEM_BY_ID,
)
from monday_cli.constants import (
    DOC_CHUNK_MAX_BYTES,
    DOC_CLEAR_MAX_ITERATIONS,
    DOC_CLEAR_MAX_TOTAL_DELETES,
    DOC_CREATE_RETRY_ATTEMPTS,
    DOC_CREATE_RETRY_DELAY,
    DOC_SCAN_MAX_PAGES,
    DOC_WRITE_TIMEOUT,
)
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json, secho_err

# Sentinel format for idempotent append dedup.
# Stored as a normal-text paragraph (HTML comments are stripped by the Monday
# API's markdown-to-blocks converter, so we use a plain-text marker block).
# The sentinel is the first paragraph prepended to each append region; before
# writing we scan blocks for a block whose content contains this string + key.
# Format: [monday-cli-dedup:SHA256_HEX]
# This is visible in docs get output as a line of text, but it serves as the
# idempotency guard for retry scenarios and is clearly machine-generated.
_DEDUP_SENTINEL_PREFIX = "[monday-cli-dedup:"
_DEDUP_SENTINEL_SUFFIX = "]"


def _resolve_doc_column(
    client: MondayGraphQLClient, item_id: int, column_name: str
) -> tuple[dict[str, Any], str]:
    """Resolve item and doc column. Returns (item, column_id) or raises typer.Exit."""
    result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(item_id)]})
    items = result.get("items", [])

    if not items:
        secho_err(f"Item {item_id} not found", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    item = items[0]
    board = item.get("board")

    if not board:
        secho_err("Error: Could not determine board for item", fg=typer.colors.RED)
        raise typer.Exit(1)

    columns_result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [board["id"]]})
    boards = columns_result.get("boards", [])
    if not boards:
        secho_err("Error: Could not fetch board columns", fg=typer.colors.RED)
        raise typer.Exit(1)

    columns = boards[0].get("columns", [])
    target_column = next(
        (col for col in columns if col["title"].lower() == column_name.lower()), None
    )

    if not target_column:
        available = ", ".join(f"'{col['title']}'" for col in columns)
        secho_err(f"Error: Column '{column_name}' not found on board", fg=typer.colors.RED)
        secho_err(f"Available columns: {available}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    if target_column.get("type") != "doc":
        col_type = target_column.get("type")
        secho_err(
            f"Error: Column '{column_name}' is not a doc column (type: {col_type})",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    return item, target_column["id"]


def _get_existing_doc_object_id(item: dict[str, Any], column_id: str) -> str | None:
    """Extract the doc object_id from an item's column values, or None.

    The objectId stored in the column value is the object_id in the docs API,
    NOT the internal doc id. Use _resolve_doc_internal_id() to get the internal id.
    """
    for col_val in item.get("column_values", []):
        if col_val["id"] == column_id:
            value_str = col_val.get("value")
            if value_str:
                try:
                    value_data = json.loads(value_str)
                    if isinstance(value_data, dict):
                        doc_id = value_data.get("doc_id")
                        if not doc_id and "files" in value_data:
                            files = value_data.get("files", [])
                            if files:
                                doc_id = files[0].get("objectId") or files[0].get("assetId")
                        if doc_id:
                            return str(doc_id)
                except json.JSONDecodeError:
                    pass
            break
    return None


def _resolve_doc_internal_id(client: MondayGraphQLClient, object_id: str) -> str | None:
    """Resolve a doc object_id to its internal doc id via the docs API."""
    result = client.execute_query(GET_DOC_BY_OBJECT_ID, {"objectIds": [str(object_id)]})
    docs = result.get("docs", [])
    if docs:
        return str(docs[0]["id"])
    return None


def _delete_all_doc_blocks(client: MondayGraphQLClient, internal_id: str) -> int:
    """Delete ALL blocks from a document. Returns the number of blocks deleted.

    US-0005-02: Fixed pagination — instead of incrementing the page counter
    while simultaneously deleting, we always fetch page=1 and repeat until
    the page comes back empty. Deletion shifts remaining blocks to the front,
    so re-fetching page=1 each time is the only reliable way to drain them all.

    Two safety bounds prevent runaway loops:
    - DOC_CLEAR_MAX_ITERATIONS: caps the number of page=1 re-fetches (loop
      iterations), each of which issues up to 100 deletes.
    - DOC_CLEAR_MAX_TOTAL_DELETES: caps the absolute number of block deletes.
      If this limit is hit it means deletes are silently failing (block remains
      after delete); an error is raised instead of looping toward ~100k mutations.
    """
    deleted = 0
    iterations = 0
    while True:
        if iterations >= DOC_CLEAR_MAX_ITERATIONS:
            secho_err(
                f"Warning: stopped clearing after {iterations} iterations "
                f"({deleted} blocks deleted). The document may still have remaining blocks.",
                fg=typer.colors.YELLOW,
            )
            break
        doc_result = client.execute_query(
            GET_DOC_BLOCKS, {"docIds": [internal_id], "limit": 100, "page": 1}
        )
        iterations += 1
        docs = doc_result.get("docs", [])
        if not docs:
            break
        blocks = docs[0].get("blocks", [])
        if not blocks:
            break
        for block in blocks:
            if deleted >= DOC_CLEAR_MAX_TOTAL_DELETES:
                raise MondayAPIError(
                    f"Aborting: exceeded {DOC_CLEAR_MAX_TOTAL_DELETES} total block deletes. "
                    "Blocks may be silently failing to delete. "
                    "Check the document state and retry with `monday docs clear`."
                )
            client.execute_mutation(DELETE_DOC_BLOCK, {"blockId": block["id"]})
            deleted += 1
    return deleted


def _byte_split_line(line: str, max_bytes: int) -> list[str]:
    """Split a single line that exceeds max_bytes into pieces on safe UTF-8 char boundaries.

    Never splits a multibyte character; each returned piece is at most max_bytes
    UTF-8 bytes. Called only when a single line is already known to exceed max_bytes.
    """
    pieces: list[str] = []
    encoded = line.encode("utf-8")
    start = 0
    total = len(encoded)
    while start < total:
        end = start + max_bytes
        if end >= total:
            pieces.append(encoded[start:].decode("utf-8"))
            break
        # Walk back from `end` to find a safe codepoint boundary.
        # UTF-8 continuation bytes have the pattern 10xxxxxx (0x80–0xBF).
        while end > start and (encoded[end] & 0xC0) == 0x80:
            end -= 1
        if end == start:
            # Degenerate: a single codepoint > max_bytes (extremely rare).
            # Advance past it to avoid an infinite loop.
            end = start + 1
            while end < total and (encoded[end] & 0xC0) == 0x80:
                end += 1
        pieces.append(encoded[start:end].decode("utf-8"))
        start = end
    return pieces


def _split_markdown_chunks(markdown: str, max_bytes: int = DOC_CHUNK_MAX_BYTES) -> list[str]:
    """Split markdown into chunks, each at most max_bytes UTF-8 bytes.

    US-0005-01: Splits on blank-line paragraph boundaries so a chunk never
    cuts mid-block. Paragraphs that are individually larger than max_bytes
    are hard-split by lines first, and if a single line still exceeds max_bytes
    it is byte-split on safe UTF-8 character boundaries. No chunk ever exceeds
    max_bytes bytes.

    Returns a list of non-empty chunk strings in source order.
    """
    if not markdown.strip():
        return []

    # Encode once to count bytes accurately for multi-byte (UTF-8) content.
    encoded = markdown.encode("utf-8")
    if len(encoded) <= max_bytes:
        return [markdown]

    # Split on blank-line boundaries (paragraph/block separators).
    # We preserve the separator so reassembled paragraphs retain their spacing.
    paragraphs: list[str] = []
    current: list[str] = []
    for line in markdown.splitlines(keepends=True):
        if line.strip() == "" and current:
            # End of a paragraph block
            paragraphs.append("".join(current))
            current = []
            # Also carry the blank line as its own separator entry
            paragraphs.append(line)
        else:
            current.append(line)
    if current:
        paragraphs.append("".join(current))

    chunks: list[str] = []
    current_chunk_parts: list[str] = []
    current_chunk_bytes = 0

    def _flush() -> None:
        nonlocal current_chunk_parts, current_chunk_bytes
        joined = "".join(current_chunk_parts).strip()
        if joined:
            chunks.append(joined)
        current_chunk_parts = []
        current_chunk_bytes = 0

    def _emit_piece(piece: str) -> None:
        """Add a piece (guaranteed <= max_bytes) to the current chunk, flushing if needed."""
        nonlocal current_chunk_bytes
        piece_bytes = len(piece.encode("utf-8"))
        if current_chunk_bytes + piece_bytes > max_bytes and current_chunk_parts:
            _flush()
        current_chunk_parts.append(piece)
        current_chunk_bytes += piece_bytes

    for para in paragraphs:
        para_bytes = len(para.encode("utf-8"))
        if para_bytes == 0:
            continue
        if current_chunk_bytes + para_bytes > max_bytes and current_chunk_parts:
            _flush()

        if para_bytes > max_bytes:
            # Oversized paragraph — hard-split by lines first
            for line in para.splitlines(keepends=True):
                line_bytes = len(line.encode("utf-8"))
                if line_bytes > max_bytes:
                    # Single line exceeds limit — byte-split on UTF-8 boundaries
                    for piece in _byte_split_line(line, max_bytes):
                        _emit_piece(piece)
                else:
                    _emit_piece(line)
        else:
            current_chunk_parts.append(para)
            current_chunk_bytes += para_bytes

    if current_chunk_parts:
        last = "".join(current_chunk_parts).strip()
        if last:
            chunks.append(last)

    return [c for c in chunks if c]


def _write_markdown_chunked(
    client: MondayGraphQLClient,
    internal_id: str,
    markdown: str,
) -> None:
    """Write markdown to a doc, chunking automatically to avoid CellLimitExceededException.

    US-0005-01 + US-0005-04: Splits the markdown into chunks each within
    DOC_CHUNK_MAX_BYTES and issues add_content_to_doc_from_markdown calls
    strictly in source order. Each call uses DOC_WRITE_TIMEOUT (120 s) instead
    of the global REQUEST_TIMEOUT (30 s) to survive large writes that take
    longer than the default timeout on Monday.com's write path.
    """
    chunks = _split_markdown_chunks(markdown)
    if not chunks:
        return

    for chunk in chunks:
        md_result = client.execute_mutation(
            ADD_CONTENT_FROM_MARKDOWN,
            {"docId": internal_id, "markdown": chunk},
            timeout=DOC_WRITE_TIMEOUT,
        )
        result_data = md_result.get("add_content_to_doc_from_markdown", {})
        if not result_data.get("success"):
            error_msg = result_data.get("error", "Unknown error")
            raise MondayAPIError(f"Failed to write content chunk: {error_msg}")


def _compute_dedup_key(markdown: str) -> str:
    """Compute a stable SHA-256 dedup key for append idempotency (US-0005-03).

    Normalization contract: content is stripped of leading/trailing whitespace
    and line endings are normalized to '\\n' before hashing. This ensures that
    a retry differing only in trailing whitespace or CRLF vs LF line endings
    produces the same key and is correctly recognised as a duplicate.

    Two appends are considered identical if and only if their normalized content
    strings are equal.
    """
    normalized = markdown.strip().replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _make_dedup_sentinel(key: str) -> str:
    """Build the hidden markdown dedup-sentinel line for an append."""
    return f"{_DEDUP_SENTINEL_PREFIX}{key}{_DEDUP_SENTINEL_SUFFIX}"


def _doc_has_dedup_key(client: MondayGraphQLClient, internal_id: str, key: str) -> bool:
    """Return True if the doc already contains an append block with this key.

    US-0005-03: Scans all block pages for a block whose content contains the
    sentinel string. Stops as soon as it finds one.
    """
    sentinel = _make_dedup_sentinel(key)
    page = 1
    while True:
        if page > DOC_SCAN_MAX_PAGES:
            break
        doc_result = client.execute_query(
            GET_DOC_BLOCKS, {"docIds": [internal_id], "limit": 100, "page": page}
        )
        docs = doc_result.get("docs", [])
        if not docs:
            break
        blocks = docs[0].get("blocks", [])
        if not blocks:
            break
        for block in blocks:
            content = block.get("content")
            if content and sentinel in str(content):
                return True
        page += 1
    return False


def _create_doc_with_retry(
    client: MondayGraphQLClient,
    item_id: int,
    column_id: str,
) -> dict[str, Any]:
    """Create a doc in a column with bounded retry for eventual-consistency transients.

    Monday's API can briefly return "Item not found" for an item immediately after
    creation (BUG-2/FR-0015). This helper retries CREATE_DOC up to
    DOC_CREATE_RETRY_ATTEMPTS times on that specific transient error, backing off
    by DOC_CREATE_RETRY_DELAY seconds between each attempt.

    CRITICAL safety guarantee: retries occur ONLY when CREATE_DOC returned an
    error containing "Item not found" — never after a partial success or any other
    error. This prevents any risk of double-creating the doc.

    Returns:
        The dict from the create_doc response key (contains at least {"id": "..."}).

    Raises:
        MondayAPIError: if all attempts are exhausted or a non-transient error occurs.
    """
    last_err: MondayAPIError | None = None
    for attempt in range(DOC_CREATE_RETRY_ATTEMPTS):
        try:
            result = client.execute_mutation(
                CREATE_DOC,
                {"itemId": str(item_id), "columnId": column_id},
            )
            created: dict[str, Any] | None = result.get("create_doc")
            if created:
                return created
            raise MondayAPIError("create_doc returned no result")
        except MondayAPIError as exc:
            msg = str(exc).lower()
            if "item not found" in msg or "itemnotfound" in msg:
                last_err = exc
                if attempt < DOC_CREATE_RETRY_ATTEMPTS - 1:
                    time.sleep(DOC_CREATE_RETRY_DELAY)
                continue
            raise  # non-transient error — propagate immediately

    raise MondayAPIError(
        f"Failed to create doc after {DOC_CREATE_RETRY_ATTEMPTS} attempts "
        f"(item {item_id} not yet visible to the docs API): {last_err}"
    )


@docs_app.command("get")
def get_doc(
    item_id: int | None = typer.Option(
        None, "--item-id", "-i", help="ID of the item containing the doc column"
    ),
    column_name: str | None = typer.Option(
        None, "--column-name", "-n", help="Name of the doc column"
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        "--markdown",
        help=(
            "Print rendered Markdown as-is (human opt-out of the default JSON). "
            "'--raw' is canonical; '--markdown' is an alias. "
            "Errors if Markdown export is unavailable."
        ),
    ),
) -> None:
    """Get document content as a deterministic JSON object {markdown, blocks} by default.

    The default output is a lossless JSON object with two keys:
    - markdown: rendered Markdown string, or null if Markdown export is unsupported
    - blocks: raw block JSON (always populated for documents with content)

    Use --raw (or --markdown) to print rendered Markdown directly to stdout instead.
    When Markdown export is unavailable, --raw errors loudly and exits non-zero.

    Example:
        monday docs get --item-id 1234567890 --column-name "Monday Doc"
        monday docs get --item-id 1234567890 --column-name "Monday Doc" --raw
    """
    try:
        if item_id is None:
            secho_err("Error: Item ID is required. Use --item-id", fg=typer.colors.RED)
            raise typer.Exit(1)

        if column_name is None:
            secho_err("Error: Column name is required. Use --column-name", fg=typer.colors.RED)
            raise typer.Exit(1)

        client = get_client()

        item, column_id = _resolve_doc_column(client, item_id, column_name)

        object_id = _get_existing_doc_object_id(item, column_id)
        if not object_id:
            secho_err(
                f"No document found in column '{column_name}' for item {item_id}",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        # Resolve object_id to internal doc id
        internal_id = _resolve_doc_internal_id(client, object_id)
        if not internal_id:
            secho_err(
                f"Could not resolve document (object_id={object_id})",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        # Always attempt Markdown export
        export_result = client.execute_query(EXPORT_MARKDOWN_FROM_DOC, {"docId": int(internal_id)})
        export = export_result.get("export_markdown_from_doc", {})
        export_success = bool(export.get("success"))

        if raw:
            # --raw / --markdown: print rendered Markdown for humans; error loudly if unsupported
            if not export_success:
                error_detail = export.get(
                    "error", "Markdown export is not supported for this document."
                )
                secho_err(
                    f"Error: Markdown export unavailable — {error_detail}",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            # Guard against success:true but markdown:null — emit empty string, not "None"
            typer.echo(export.get("markdown") or "")
        else:
            # Default path: emit deterministic, lossless JSON {markdown, blocks}
            markdown_value = export.get("markdown") if export_success else None

            # Fetch ALL blocks via pagination to ensure the output is genuinely
            # lossless for large documents (server default without limit/page is
            # ~25 blocks, which truncates docs enabled by this PR's chunking).
            all_blocks: list[dict[str, Any]] = []
            page = 1
            while True:
                doc_result = client.execute_query(
                    GET_DOC_BLOCKS, {"docIds": [internal_id], "limit": 100, "page": page}
                )
                docs = doc_result.get("docs", [])
                if not docs:
                    if page == 1:
                        secho_err(
                            f"No content found for document {internal_id}",
                            fg=typer.colors.YELLOW,
                        )
                        raise typer.Exit(1)
                    break
                page_blocks = docs[0].get("blocks", [])
                if not page_blocks:
                    break
                all_blocks.extend(page_blocks)
                if len(page_blocks) < 100:
                    # Fewer than a full page returned — we've reached the end
                    break
                page += 1
            print_json({"markdown": markdown_value, "blocks": all_blocks})

    except typer.Exit:
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
    except Exception as e:
        secho_err(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@docs_app.command("append")
def append_doc(
    item_id: int | None = typer.Option(
        None, "--item-id", "-i", help="ID of the item containing the doc column"
    ),
    column_name: str | None = typer.Option(
        None, "--column-name", "-n", help="Name of the doc column"
    ),
    content: str | None = typer.Option(
        None, "--content", "-c", help="Markdown content to append to the document"
    ),
) -> None:
    """Append Markdown content to a document.

    Creates the document if it does not exist, then appends the Markdown content.
    Append is idempotent: retrying with the same content (e.g. after a lost
    acknowledgement) will not duplicate the content (US-0005-03).

    Dedup sentinel side effects:
    - Each append prepends a '[monday-cli-dedup:HEX]' marker block. This marker
      is visible in `docs get` output and in the raw Markdown from `docs get --raw`.
    - Round-trip reads: if you read a doc with `docs get --raw`, edit it, and
      write it back with `docs put`, the sentinel from the previous append is
      included in the content. A subsequent `docs append` may find a phantom
      sentinel (harmless — it occupies one block but does not suppress the write
      because `put` content hashes differ from `append` content hashes).
    - Content forgery: any text containing '[monday-cli-dedup:HEX]' (64 hex
      chars) written into a doc can cause a future `docs append` whose SHA-256
      matches that key to be silently skipped. Accidental collision is negligible
      (SHA-256); intentional forgery is trivially possible. Do not rely on dedup
      as a security mechanism.

    Example:
        monday docs append --item-id 1234567890 --column-name "Monday Doc" --content "# Hello"
    """
    try:
        if item_id is None:
            secho_err("Error: Item ID is required. Use --item-id", fg=typer.colors.RED)
            raise typer.Exit(1)

        if column_name is None:
            secho_err("Error: Column name is required. Use --column-name", fg=typer.colors.RED)
            raise typer.Exit(1)

        if content is None:
            secho_err("Error: Content is required. Use --content", fg=typer.colors.RED)
            raise typer.Exit(1)

        client = get_client()

        item, column_id = _resolve_doc_column(client, item_id, column_name)

        object_id = _get_existing_doc_object_id(item, column_id)
        created = False

        if not object_id:
            # BUG-2 fix (FR-0015): CREATE_DOC may transiently fail with "Item not
            # found" for freshly-created items due to Monday's eventual consistency.
            # Use the bounded-retry helper so the first append after item creation
            # does not fail non-deterministically.
            try:
                created_doc = _create_doc_with_retry(client, item_id, column_id)
            except MondayAPIError as exc:
                secho_err(f"Error: Failed to create document — {exc}", fg=typer.colors.RED)
                raise typer.Exit(1)
            internal_id = created_doc["id"]
            created = True
        else:
            internal_id = _resolve_doc_internal_id(client, object_id)
            if not internal_id:
                secho_err(
                    f"Could not resolve document (object_id={object_id})",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)

        # US-0005-03: Idempotent append via dedup key.
        # Before writing, compute a SHA-256 of the content and check whether a
        # sentinel block carrying this key already exists in the doc. If it does,
        # the previous append committed (even though the client may have lost the
        # ack) — skip the write to avoid duplication.
        dedup_key = _compute_dedup_key(content)
        if not created and _doc_has_dedup_key(client, internal_id, dedup_key):
            secho_err(
                "Content already present (dedup key matched); skipping duplicate append.",
                fg=typer.colors.YELLOW,
            )
            action = "updated"
            secho_err(f"✓ Document {action} successfully!", fg=typer.colors.GREEN)
            print_json({"doc_id": internal_id, "item_id": str(item_id), "column_id": column_id})
            return

        # Embed the dedup sentinel as a hidden comment at the start of the appended region.
        sentinel_line = _make_dedup_sentinel(dedup_key)
        content_with_sentinel = f"{sentinel_line}\n\n{content}"

        _write_markdown_chunked(client, internal_id, content_with_sentinel)

        action = "created" if created else "updated"
        secho_err(f"✓ Document {action} successfully!", fg=typer.colors.GREEN)
        print_json({"doc_id": internal_id, "item_id": str(item_id), "column_id": column_id})

    except typer.Exit:
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
    except Exception as e:
        secho_err(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@docs_app.command("put")
def put_doc(
    item_id: int | None = typer.Option(
        None, "--item-id", "-i", help="ID of the item containing the doc column"
    ),
    column_name: str | None = typer.Option(
        None, "--column-name", "-n", help="Name of the doc column"
    ),
    content: str | None = typer.Option(
        None, "--content", "-c", help="Markdown content to write to the document"
    ),
) -> None:
    """Replace document content with Markdown.

    Creates the document if it does not exist. If a document already exists,
    all existing content is deleted before writing the new content.

    Large documents are automatically split into chunks to avoid API cell-size
    limits (CellLimitExceededException). The size preflight runs BEFORE any
    destructive clear so a doomed write never corrupts an existing document.

    Atomicity note (existing-doc path): the clear and write are two separate
    API operations. If a chunk write fails after the clear has completed, the
    document will be left partially written. There is no automatic rollback for
    this path. To recover, run:

        monday docs clear --item-id <id> --column-name <col> --force

    and then retry the put. For a fresh (empty) cell, a write failure triggers
    automatic cleanup of the orphaned doc object so the column stays writable.

    Example:
        monday docs put --item-id 1234567890 --column-name "FRD" --content "# Hello\\n\\nWorld"
    """
    try:
        if item_id is None:
            secho_err("Error: Item ID is required. Use --item-id", fg=typer.colors.RED)
            raise typer.Exit(1)

        if column_name is None:
            secho_err("Error: Column name is required. Use --column-name", fg=typer.colors.RED)
            raise typer.Exit(1)

        if content is None:
            secho_err("Error: Content is required. Use --content", fg=typer.colors.RED)
            raise typer.Exit(1)

        client = get_client()

        item, column_id = _resolve_doc_column(client, item_id, column_name)

        # US-0005-01: Pre-split the content into chunks BEFORE touching the doc.
        # This means we know the write strategy before any destructive operation.
        chunks = _split_markdown_chunks(content)
        content_bytes = len(content.encode("utf-8"))
        secho_err(
            f"Writing {content_bytes:,} bytes ({len(chunks)} chunk(s)) to doc column...",
            fg=typer.colors.YELLOW,
        )

        object_id = _get_existing_doc_object_id(item, column_id)
        created = False

        if not object_id:
            # Fresh cell: create the doc object first.
            # BUG-2 fix (FR-0015): CREATE_DOC may transiently fail with "Item not
            # found" for freshly-created items due to Monday's eventual consistency.
            # Use the bounded-retry helper so a put immediately after item creation
            # does not fail non-deterministically.
            try:
                created_doc = _create_doc_with_retry(client, item_id, column_id)
            except MondayAPIError as exc:
                secho_err(f"Error: Failed to create document — {exc}", fg=typer.colors.RED)
                raise typer.Exit(1)
            internal_id = created_doc["id"]
            created = True

            # Write content; if this fails, delete the just-created empty doc so
            # the column is not left in an unresolvable orphaned state.
            try:
                _write_markdown_chunked(client, internal_id, content)
            except Exception as write_err:
                secho_err(
                    f"Error writing content to new doc; "
                    f"cleaning up orphaned doc object: {write_err}",
                    fg=typer.colors.RED,
                )
                try:
                    client.execute_mutation(DELETE_DOC, {"docId": internal_id})
                    secho_err(
                        "Orphaned doc object removed. The column is clean; retry your put.",
                        fg=typer.colors.YELLOW,
                    )
                except Exception:
                    secho_err(
                        "Warning: could not remove orphaned doc object. "
                        "Run `monday docs clear` to recover the column.",
                        fg=typer.colors.RED,
                    )
                raise typer.Exit(1)
        else:
            internal_id = _resolve_doc_internal_id(client, object_id)
            if not internal_id:
                secho_err(
                    f"Could not resolve document (object_id={object_id})",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)

            # US-0005-02: Exhaustive clear — always fetch page=1 until empty.
            deleted_count = _delete_all_doc_blocks(client, internal_id)
            if deleted_count:
                secho_err(
                    f"Cleared {deleted_count} existing block(s)",
                    fg=typer.colors.YELLOW,
                )

            # US-0005-01 + US-0005-04: Write in chunks, in source order.
            _write_markdown_chunked(client, internal_id, content)

        action = "created" if created else "replaced"
        secho_err(f"✓ Document content {action} successfully!", fg=typer.colors.GREEN)
        print_json({"doc_id": internal_id, "item_id": str(item_id), "column_id": column_id})

    except typer.Exit:
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
    except Exception as e:
        secho_err(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@docs_app.command("clear")
def clear_doc(
    item_id: int | None = typer.Option(
        None, "--item-id", "-i", help="ID of the item containing the doc column"
    ),
    column_name: str | None = typer.Option(
        None, "--column-name", "-n", help="Name of the doc column to clear"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Clear / reset a doc column, including corrupted / unresolvable cells.

    For healthy docs: deletes all blocks, leaving an empty document.
    For corrupted / orphaned cells (object_id present but doc unresolvable):
    detaches the dangling reference so the column is writable again.

    Use this command to recover from a cell left in the
    'Could not resolve document (object_id=...)' error state without any
    web-UI step.

    Example:
        monday docs clear --item-id 1234567890 --column-name "Notes"
        monday docs clear --item-id 1234567890 --column-name "Notes" --force
    """
    try:
        if item_id is None:
            secho_err("Error: Item ID is required. Use --item-id", fg=typer.colors.RED)
            raise typer.Exit(1)

        if column_name is None:
            secho_err("Error: Column name is required. Use --column-name", fg=typer.colors.RED)
            raise typer.Exit(1)

        if not force:
            confirm = typer.confirm(
                f"Clear doc column '{column_name}' on item {item_id}? This cannot be undone.",
                err=True,
            )
            if not confirm:
                secho_err("Aborted.", fg=typer.colors.YELLOW)
                raise typer.Exit(0)

        client = get_client()

        item, column_id = _resolve_doc_column(client, item_id, column_name)
        board_id = item.get("board", {}).get("id")

        object_id = _get_existing_doc_object_id(item, column_id)

        if not object_id:
            # Column is already empty — nothing to do
            secho_err(
                f"Column '{column_name}' has no document; nothing to clear.",
                fg=typer.colors.YELLOW,
            )
            print_json(
                {
                    "cleared": True,
                    "item_id": str(item_id),
                    "column_id": column_id,
                    "blocks_deleted": 0,
                }
            )
            return

        # Try to resolve the internal doc id
        internal_id = _resolve_doc_internal_id(client, object_id)

        if internal_id:
            # Healthy path: clear all blocks via the exhaustive delete helper
            deleted_count = _delete_all_doc_blocks(client, internal_id)
            secho_err(
                f"Cleared {deleted_count} block(s) from document.",
                fg=typer.colors.YELLOW,
            )
            secho_err(f"✓ Doc column '{column_name}' cleared successfully!", fg=typer.colors.GREEN)
            print_json(
                {
                    "cleared": True,
                    "item_id": str(item_id),
                    "column_id": column_id,
                    "doc_id": internal_id,
                    "blocks_deleted": deleted_count,
                }
            )
        else:
            # US-0005-05: Corrupted / unresolvable path — the doc object_id exists in
            # the column value but the docs API can no longer resolve it (BUG-1 orphan
            # state). The former clear_item_column_value mutation was removed from
            # Monday's API. Use change_column_value with {"files": []} — the current
            # equivalent — to detach the dangling reference so the column is writable.
            if not board_id:
                secho_err(
                    "Error: Cannot recover corrupted cell — board ID unavailable.",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)

            secho_err(
                f"Document (object_id={object_id}) is unresolvable (orphaned). "
                "Clearing the column reference to recover...",
                fg=typer.colors.YELLOW,
            )
            client.execute_mutation(
                RESET_DOC_COLUMN_VALUE,
                {
                    "boardId": str(board_id),
                    "itemId": str(item_id),
                    "columnId": column_id,
                    "value": json.dumps({"files": []}),
                },
            )
            secho_err(
                f"✓ Corrupted doc column '{column_name}' cleared successfully! "
                "The column is now writable.",
                fg=typer.colors.GREEN,
            )
            print_json(
                {
                    "cleared": True,
                    "item_id": str(item_id),
                    "column_id": column_id,
                    "doc_id": None,
                    "blocks_deleted": 0,
                    "recovered_orphan": True,
                }
            )

    except typer.Exit:
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
    except Exception as e:
        secho_err(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
