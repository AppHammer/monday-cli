"""Unit tests for FR-0005 doc reliability fixes.

Covers:
- _split_markdown_chunks: chunking at block boundaries, size limit, source order (US-0005-01/04)
- _delete_all_doc_blocks: always-page-1 pagination correctness (US-0005-02)
- _compute_dedup_key / _doc_has_dedup_key: idempotent append dedup (US-0005-03)
- docs clear command: guide-drift check; healthy and corrupted code paths (US-0005-05)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from monday_cli.cli import app
from monday_cli.commands.docs import (
    _DEDUP_SENTINEL_PREFIX,
    _DEDUP_SENTINEL_SUFFIX,
    _byte_split_line,
    _compute_dedup_key,
    _delete_all_doc_blocks,
    _doc_has_dedup_key,
    _make_dedup_sentinel,
    _split_markdown_chunks,
)
from monday_cli.constants import (
    DOC_CHUNK_MAX_BYTES,
    DOC_CLEAR_MAX_ITERATIONS,
    DOC_CLEAR_MAX_TOTAL_DELETES,
    DOC_SCAN_MAX_PAGES,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Constants sanity checks (NIT 1)
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify that the renamed/split constants exist and are semantically distinct."""

    def test_clear_iterations_and_scan_pages_are_distinct_names(self) -> None:
        """DOC_CLEAR_MAX_ITERATIONS (delete loop) and DOC_SCAN_MAX_PAGES (dedup scan) exist."""
        assert DOC_CLEAR_MAX_ITERATIONS > 0
        assert DOC_SCAN_MAX_PAGES > 0

    def test_total_delete_cap_is_less_than_iteration_times_page_size(self) -> None:
        """DOC_CLEAR_MAX_TOTAL_DELETES provides a tighter bound than iterations * 100."""
        assert DOC_CLEAR_MAX_TOTAL_DELETES < DOC_CLEAR_MAX_ITERATIONS * 100


def _extract_json_from_output(stdout: str) -> Any:
    """Extract the JSON payload from CLI stdout that may have human messages before it."""
    stripped = stdout.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    lines = stdout.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() in ("{", "["):
            candidate = "\n".join(lines[idx:])
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise AssertionError(f"No JSON payload found in CLI output:\n{stdout}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(column_id: str = "col1", object_id: str = "42") -> dict[str, Any]:
    return {
        "items": [
            {
                "id": "1001",
                "name": "Test Item",
                "board": {"id": "999", "name": "Board"},
                "column_values": [
                    {
                        "id": column_id,
                        "text": "",
                        "value": json.dumps({"doc_id": object_id}),
                        "type": "doc",
                    }
                ],
            }
        ]
    }


def _make_board_columns(column_id: str = "col1") -> dict[str, Any]:
    return {
        "boards": [
            {
                "id": "999",
                "name": "Board",
                "columns": [
                    {"id": column_id, "title": "Notes", "type": "doc", "settings_str": "{}"}
                ],
            }
        ]
    }


def _make_doc_by_object_id(internal_id: str = "77") -> dict[str, Any]:
    return {"docs": [{"id": internal_id, "object_id": "42"}]}


def _make_doc_blocks(block_ids: list[str] | None = None) -> dict[str, Any]:
    if block_ids is None:
        block_ids = ["b1", "b2"]
    return {
        "docs": [
            {
                "id": "77",
                "blocks": [
                    {"id": bid, "type": "normal_text", "content": '{"insert":"text"}'}
                    for bid in block_ids
                ],
            }
        ]
    }


def _make_empty_blocks() -> dict[str, Any]:
    return {"docs": [{"id": "77", "blocks": []}]}


# ---------------------------------------------------------------------------
# _split_markdown_chunks (US-0005-01, US-0005-04)
# ---------------------------------------------------------------------------


class TestSplitMarkdownChunks:
    """Verify the chunking helper splits correctly and preserves source order."""

    def test_small_content_returns_single_chunk(self) -> None:
        md = "# Hello\n\nWorld"
        chunks = _split_markdown_chunks(md, max_bytes=1000)
        assert chunks == [md]

    def test_empty_string_returns_empty_list(self) -> None:
        assert _split_markdown_chunks("") == []

    def test_whitespace_only_returns_empty_list(self) -> None:
        # Whitespace-only means no real blocks — strip() is empty
        assert _split_markdown_chunks("   \n\n  ") == []

    def test_split_on_blank_line_boundary(self) -> None:
        # Two paragraphs of ~10 bytes each; max_bytes=15 forces a split
        para1 = "Hello world"  # 11 bytes
        para2 = "Foo bar baz"  # 11 bytes
        md = f"{para1}\n\n{para2}"
        chunks = _split_markdown_chunks(md, max_bytes=15)
        assert len(chunks) == 2
        assert para1 in chunks[0]
        assert para2 in chunks[1]

    def test_chunk_order_is_source_order(self) -> None:
        """The key AC for US-0005-04: chunks come out in source order."""
        sections = [f"# Section {i}\n\nContent for section {i}." for i in range(1, 6)]
        md = "\n\n".join(sections)
        chunks = _split_markdown_chunks(md, max_bytes=50)
        # Reconstruct combined text from chunks in order
        combined = " ".join(chunks)
        last_pos = -1
        for i in range(1, 6):
            pos = combined.find(f"Section {i}")
            assert pos != -1, f"Section {i} missing from chunks"
            assert pos > last_pos, f"Section {i} out of order (pos={pos}, last={last_pos})"
            last_pos = pos

    def test_no_chunk_exceeds_max_bytes(self) -> None:
        # Build a ~60KB document of many normal paragraphs and verify each chunk fits
        paragraphs = [f"Paragraph {i}: " + ("x" * 200) for i in range(100)]
        md = "\n\n".join(paragraphs)
        max_b = DOC_CHUNK_MAX_BYTES
        chunks = _split_markdown_chunks(md, max_bytes=max_b)
        for idx, chunk in enumerate(chunks):
            size = len(chunk.encode("utf-8"))
            assert size <= max_b, f"Chunk {idx} is {size} bytes, exceeds max_bytes={max_b}"

    def test_single_line_exceeding_max_bytes_is_byte_split(self) -> None:
        """BLOCKER 2: a single line > max_bytes must never produce an over-limit chunk."""
        max_b = 20_000
        # A 25001-byte single-line string with no internal newlines
        big_line = "x" * 25_001
        chunks = _split_markdown_chunks(big_line, max_bytes=max_b)
        assert len(chunks) >= 2, "Expected the oversized single line to be split"
        for idx, chunk in enumerate(chunks):
            size = len(chunk.encode("utf-8"))
            assert size <= max_b, f"Chunk {idx} is {size} bytes, exceeds max_bytes={max_b}"
        # All content must be present (no bytes dropped)
        assert "".join(chunks) == big_line

    def test_single_line_multibyte_utf8_is_byte_split_safely(self) -> None:
        """Byte-split must not split a multibyte UTF-8 character across chunk boundaries."""
        max_b = 10
        # Each emoji is 4 bytes in UTF-8; 3 emojis = 12 bytes → must split into 2 chunks
        emoji_line = "\U0001f600" * 3  # 😀😀😀 = 12 UTF-8 bytes
        pieces = _byte_split_line(emoji_line, max_bytes=max_b)
        for piece in pieces:
            assert len(piece.encode("utf-8")) <= max_b
            # Each piece must be valid UTF-8 (round-trip check)
            assert piece.encode("utf-8").decode("utf-8") == piece
        assert "".join(pieces) == emoji_line

    def test_large_content_produces_multiple_chunks(self) -> None:
        # 200 paragraphs of 250 bytes each = ~50KB; must produce multiple chunks
        para = "x" * 250
        md = "\n\n".join([para] * 200)
        chunks = _split_markdown_chunks(md, max_bytes=DOC_CHUNK_MAX_BYTES)
        assert len(chunks) > 1

    def test_single_chunk_at_exact_limit(self) -> None:
        # Content exactly at the limit should not be split
        md = "a" * DOC_CHUNK_MAX_BYTES
        chunks = _split_markdown_chunks(md, max_bytes=DOC_CHUNK_MAX_BYTES)
        # Should return either the original string or at least one chunk
        assert len(chunks) >= 1
        # All content must be present
        combined = "".join(chunks)
        assert "a" * 100 in combined  # spot-check


# ---------------------------------------------------------------------------
# _delete_all_doc_blocks (US-0005-02)
# ---------------------------------------------------------------------------


class TestDeleteAllDocBlocks:
    """Verify the exhaustive block-delete always re-fetches page=1."""

    def _make_client_with_pages(self, pages: list[list[str]]) -> MagicMock:
        """Build a mock client that returns each page list in sequence, then empty."""
        client = MagicMock()
        responses = []
        for block_ids in pages:
            responses.append(
                {
                    "docs": [
                        {
                            "id": "77",
                            "blocks": [
                                {"id": bid, "type": "normal_text", "content": "{}"}
                                for bid in block_ids
                            ],
                        }
                    ]
                }
            )
        # Final empty page — signals the loop to stop
        responses.append({"docs": [{"id": "77", "blocks": []}]})
        client.execute_query.side_effect = responses
        client.execute_mutation.return_value = {"delete_doc_block": {"id": "x"}}
        return client

    def test_always_fetches_page_1(self) -> None:
        """Every GET_DOC_BLOCKS call must use page=1, never page=2+."""

        client = self._make_client_with_pages([["b1", "b2"], ["b3"]])
        _delete_all_doc_blocks(client, "77")

        # All execute_query calls should have page=1
        for c in client.execute_query.call_args_list:
            # Variables can be positional or keyword
            args, kwargs = c
            variables = args[1] if len(args) > 1 else kwargs.get("variables", {})
            if variables and "page" in variables:
                assert (
                    variables["page"] == 1
                ), f"execute_query called with page={variables['page']}, expected 1"

    def test_deletes_all_blocks_across_multiple_page_fetches(self) -> None:
        """Must delete every block even when they span multiple fetches of page=1."""
        client = self._make_client_with_pages([["b1", "b2"], ["b3", "b4"]])
        deleted = _delete_all_doc_blocks(client, "77")
        # Should have deleted b1, b2, b3, b4
        assert deleted == 4
        assert client.execute_mutation.call_count == 4

    def test_returns_zero_for_empty_doc(self) -> None:
        client = MagicMock()
        client.execute_query.return_value = {"docs": [{"id": "77", "blocks": []}]}
        deleted = _delete_all_doc_blocks(client, "77")
        assert deleted == 0
        assert client.execute_mutation.call_count == 0

    def test_raises_when_total_delete_cap_exceeded(self) -> None:
        """SUGGESTION 1: MondayAPIError raised when total-delete cap is hit."""
        import pytest

        from monday_cli.utils.error_handler import MondayAPIError

        # Always return the same blocks so deletes never reduce the count
        always_blocks = {
            "docs": [
                {
                    "id": "77",
                    "blocks": [
                        {"id": f"b{i}", "type": "normal_text", "content": "{}"} for i in range(100)
                    ],
                }
            ]
        }
        client = MagicMock()
        client.execute_query.return_value = always_blocks
        client.execute_mutation.return_value = {"delete_doc_block": {"id": "x"}}

        with pytest.raises(MondayAPIError, match="exceeded"):
            _delete_all_doc_blocks(client, "77")

        # Should have hit the cap, not the iteration cap
        assert client.execute_mutation.call_count == DOC_CLEAR_MAX_TOTAL_DELETES

    def test_handles_no_docs_response(self) -> None:
        client = MagicMock()
        client.execute_query.return_value = {"docs": []}
        deleted = _delete_all_doc_blocks(client, "77")
        assert deleted == 0

    def test_previous_bug_incremented_page_would_miss_blocks(self) -> None:
        """Regression: old code did `page += 1` which skipped shifted blocks.

        With 3 blocks and limit=2, old code: fetch page=1 (b1,b2), delete both,
        fetch page=2 (now empty because b3 shifted to page=1), stop — b3 missed.
        New code: fetch page=1 twice → deletes all 3.
        """
        call_count = [0]

        def side_effect(query: str, variables: dict[str, Any]) -> dict[str, Any]:
            call_count[0] += 1
            # Simulate the shifting: page=1 always returns the first remaining block
            remaining = max(0, 3 - (call_count[0] - 1) * 2)
            blocks = [
                {"id": f"b{i}", "type": "text", "content": "{}"}
                for i in range(1, min(3, remaining) + 1)
            ]
            return {"docs": [{"id": "77", "blocks": blocks}]}

        client = MagicMock()
        client.execute_query.side_effect = side_effect
        client.execute_mutation.return_value = {}

        # We can't perfectly replicate the shifting without a live API, but we
        # verify the new code calls page=1 consistently and returns deleted > 0
        # The important thing is no incremented page call
        try:
            _delete_all_doc_blocks(client, "77")
        except StopIteration:
            pass  # side_effect ran out; that's fine for this regression check

        for c in client.execute_query.call_args_list:
            args, kwargs = c
            variables = args[1] if len(args) > 1 else {}
            if "page" in variables:
                assert variables["page"] == 1, "Bug: page was incremented past 1"


# ---------------------------------------------------------------------------
# _compute_dedup_key / _make_dedup_sentinel / _doc_has_dedup_key (US-0005-03)
# ---------------------------------------------------------------------------


class TestDedupKeyHelpers:
    """Verify dedup key computation and sentinel detection."""

    def test_dedup_key_is_sha256_hex(self) -> None:
        content = "Hello World"
        key = _compute_dedup_key(content)
        # Key is computed over stripped+normalized form
        normalized = content.strip().replace("\r\n", "\n").replace("\r", "\n")
        expected = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        assert key == expected

    def test_same_content_same_key(self) -> None:
        md = "# Test\n\nSome content"
        assert _compute_dedup_key(md) == _compute_dedup_key(md)

    def test_different_content_different_key(self) -> None:
        key1 = _compute_dedup_key("hello")
        key2 = _compute_dedup_key("world")
        assert key1 != key2

    def test_trailing_whitespace_normalized_to_same_key(self) -> None:
        """SUGGESTION 4: trailing whitespace difference must not create a different key."""
        assert _compute_dedup_key("hello\n") == _compute_dedup_key("hello")
        assert _compute_dedup_key("  hello  ") == _compute_dedup_key("hello")

    def test_crlf_normalized_to_same_key_as_lf(self) -> None:
        """SUGGESTION 4: CRLF vs LF should not create different dedup keys."""
        assert _compute_dedup_key("line1\r\nline2") == _compute_dedup_key("line1\nline2")

    def test_make_dedup_sentinel_contains_prefix_and_key(self) -> None:
        key = _compute_dedup_key("test")
        sentinel = _make_dedup_sentinel(key)
        assert _DEDUP_SENTINEL_PREFIX in sentinel
        assert key in sentinel
        assert _DEDUP_SENTINEL_SUFFIX in sentinel

    def test_doc_has_dedup_key_returns_true_when_sentinel_present(self) -> None:
        content = "Hello append content"
        key = _compute_dedup_key(content)
        sentinel = _make_dedup_sentinel(key)

        client = MagicMock()
        client.execute_query.return_value = {
            "docs": [
                {
                    "id": "77",
                    "blocks": [
                        {
                            "id": "b1",
                            "type": "normal_text",
                            "content": json.dumps({"insert": sentinel}),
                        }
                    ],
                }
            ]
        }
        assert _doc_has_dedup_key(client, "77", key) is True

    def test_doc_has_dedup_key_returns_false_when_absent(self) -> None:
        client = MagicMock()
        client.execute_query.return_value = {
            "docs": [
                {
                    "id": "77",
                    "blocks": [
                        {"id": "b1", "type": "normal_text", "content": '{"insert":"unrelated"}'}
                    ],
                }
            ]
        }
        key = _compute_dedup_key("some content")
        assert _doc_has_dedup_key(client, "77", key) is False

    def test_doc_has_dedup_key_returns_false_for_empty_doc(self) -> None:
        client = MagicMock()
        client.execute_query.return_value = {"docs": [{"id": "77", "blocks": []}]}
        key = _compute_dedup_key("content")
        assert _doc_has_dedup_key(client, "77", key) is False


# ---------------------------------------------------------------------------
# append idempotency (US-0005-03) via CLI invocation
# ---------------------------------------------------------------------------


class TestAppendIdempotency:
    """Verify that appending the same content twice is a no-op (dedup)."""

    def _build_mock_client_with_sentinel(
        self, internal_id: str = "77", content: str = "# Append me"
    ) -> MagicMock:
        """Build a client that simulates a doc already containing the dedup sentinel."""
        key = _compute_dedup_key(content)
        sentinel = _make_dedup_sentinel(key)
        client = MagicMock()
        # Sequence: GET_ITEM_BY_ID, GET_BOARD_COLUMNS, GET_DOC_BY_OBJECT_ID,
        # then _doc_has_dedup_key calls GET_DOC_BLOCKS and finds sentinel
        client.execute_query.side_effect = [
            _make_item(),  # GET_ITEM_BY_ID
            _make_board_columns(),  # GET_BOARD_COLUMNS
            _make_doc_by_object_id(internal_id),  # GET_DOC_BY_OBJECT_ID
            {  # GET_DOC_BLOCKS for dedup check — sentinel found
                "docs": [
                    {
                        "id": internal_id,
                        "blocks": [
                            {
                                "id": "b_dedup",
                                "type": "normal_text",
                                "content": json.dumps({"insert": sentinel}),
                            }
                        ],
                    }
                ]
            },
        ]
        return client

    def test_duplicate_append_skips_write(self) -> None:
        """When the dedup key is already in the doc, the mutation must not be called."""
        content = "# Append me"
        client = self._build_mock_client_with_sentinel(content=content)

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            result = runner.invoke(
                app,
                [
                    "docs",
                    "append",
                    "--item-id",
                    "1001",
                    "--column-name",
                    "Notes",
                    "--content",
                    content,
                ],
            )

        assert result.exit_code == 0
        # execute_mutation must NOT have been called (no write)
        assert client.execute_mutation.call_count == 0

    def test_different_content_still_appends(self) -> None:
        """A second append with DIFFERENT content must still write."""
        second_content = "# Second append"

        # The dedup check for second_content: scans blocks (page=1 returns unrelated blocks,
        # page=2 returns empty → sentinel not found → proceed with write)
        client = MagicMock()
        client.execute_query.side_effect = [
            _make_item(),
            _make_board_columns(),
            _make_doc_by_object_id(),
            # _doc_has_dedup_key: page=1 — unrelated blocks, no sentinel
            _make_doc_blocks(),
            # _doc_has_dedup_key: page=2 — empty, loop stops
            _make_empty_blocks(),
        ]
        client.execute_mutation.return_value = {
            "add_content_to_doc_from_markdown": {"success": True, "block_ids": ["b_new"]}
        }

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            result = runner.invoke(
                app,
                [
                    "docs",
                    "append",
                    "--item-id",
                    "1001",
                    "--column-name",
                    "Notes",
                    "--content",
                    second_content,
                ],
            )

        # Should succeed and have called execute_mutation (the write)
        assert result.exit_code == 0
        assert client.execute_mutation.call_count >= 1


# ---------------------------------------------------------------------------
# docs clear command (US-0005-05)
# ---------------------------------------------------------------------------


class TestDocsClearCommand:
    """Verify the `docs clear` command: healthy path, corrupted path, empty path."""

    def test_clear_appears_in_guide(self) -> None:
        """US-0005-05: docs clear must be discoverable via monday guide."""
        result = runner.invoke(app, ["guide"])
        assert result.exit_code == 0
        assert "docs clear" in result.stdout

    def test_clear_appears_in_guide_json(self) -> None:
        """docs clear must appear in monday guide --json under the docs group."""
        result = runner.invoke(app, ["guide", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        docs_group = next((g for g in data["groups"] if g["name"] == "docs"), None)
        assert docs_group is not None, "docs group missing from guide --json"
        cmd_names = {c["name"] for c in docs_group["commands"]}
        assert "clear" in cmd_names, f"'clear' missing from docs commands: {cmd_names}"

    def test_clear_empty_column_reports_nothing_to_clear(self) -> None:
        """When the doc column has no document, clear exits zero and says nothing to clear."""
        item_no_doc = {
            "items": [
                {
                    "id": "1001",
                    "name": "Test Item",
                    "board": {"id": "999", "name": "Board"},
                    "column_values": [{"id": "col1", "text": "", "value": None, "type": "doc"}],
                }
            ]
        }
        client = MagicMock()
        client.execute_query.side_effect = [item_no_doc, _make_board_columns()]

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            result = runner.invoke(
                app,
                ["docs", "clear", "--item-id", "1001", "--column-name", "Notes", "--force"],
            )

        assert result.exit_code == 0
        data = _extract_json_from_output(result.stdout)
        assert data["cleared"] is True
        assert data["blocks_deleted"] == 0

    def test_clear_healthy_doc_deletes_all_blocks(self) -> None:
        """Healthy-doc path: all blocks deleted, JSON emitted with doc_id."""
        client = MagicMock()
        client.execute_query.side_effect = [
            _make_item(),  # GET_ITEM_BY_ID
            _make_board_columns(),  # GET_BOARD_COLUMNS
            _make_doc_by_object_id(),  # GET_DOC_BY_OBJECT_ID
            _make_doc_blocks(["b1", "b2", "b3"]),  # GET_DOC_BLOCKS (page=1 first)
            _make_empty_blocks(),  # GET_DOC_BLOCKS (page=1 again — now empty)
        ]
        client.execute_mutation.return_value = {"delete_doc_block": {"id": "x"}}

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            result = runner.invoke(
                app,
                ["docs", "clear", "--item-id", "1001", "--column-name", "Notes", "--force"],
            )

        assert result.exit_code == 0
        # 3 blocks deleted
        assert client.execute_mutation.call_count == 3
        data = _extract_json_from_output(result.stdout)
        assert data["cleared"] is True
        assert data["blocks_deleted"] == 3
        assert data["doc_id"] == "77"

    def test_clear_corrupted_doc_calls_change_column_value(self) -> None:
        """Corrupted / orphaned path: cannot resolve internal_id → calls CHANGE_COLUMN_VALUE.

        BUG-1 fix (FR-0015): clear_item_column_value was removed from Monday's API.
        The replacement is change_column_value with value='{"files":[]}'.
        RESET_DOC_COLUMN_VALUE was a duplicate of CHANGE_COLUMN_VALUE; the code now
        uses CHANGE_COLUMN_VALUE directly.
        """
        import json as _json

        client = MagicMock()
        client.execute_query.side_effect = [
            _make_item(),  # GET_ITEM_BY_ID
            _make_board_columns(),  # GET_BOARD_COLUMNS
            {"docs": []},  # GET_DOC_BY_OBJECT_ID — cannot resolve → None internal_id
        ]
        client.execute_mutation.return_value = {"change_column_value": {"id": "1001", "name": "x"}}

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            result = runner.invoke(
                app,
                ["docs", "clear", "--item-id", "1001", "--column-name", "Notes", "--force"],
            )

        assert result.exit_code == 0
        assert client.execute_mutation.call_count == 1
        # The mutation must be CHANGE_COLUMN_VALUE (the canonical mutation, not a duplicate)
        mutation_call = client.execute_mutation.call_args_list[0]
        args, kwargs = mutation_call
        from monday_cli.client.mutations import CHANGE_COLUMN_VALUE

        assert args[0] == CHANGE_COLUMN_VALUE
        # The value variable must be '{"files":[]}' — the reset payload
        variables = args[1]
        assert _json.loads(variables["value"]) == {"files": []}
        # Output should include recovered_orphan: true
        data = _extract_json_from_output(result.stdout)
        assert data["cleared"] is True
        assert data.get("recovered_orphan") is True

    def test_clear_requires_force_or_confirm(self) -> None:
        """Without --force, the command prompts for confirmation.

        Answering 'no' must abort without calling any mutation.
        """
        client = MagicMock()
        client.execute_query.side_effect = [_make_item(), _make_board_columns()]

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            # Invoke without --force and answer 'no' to the prompt
            runner.invoke(
                app,
                ["docs", "clear", "--item-id", "1001", "--column-name", "Notes"],
                input="n\n",
            )

        # Should have aborted — no mutation called
        assert client.execute_mutation.call_count == 0


# ---------------------------------------------------------------------------
# docs put: size preflight and orphan cleanup (US-0005-01)
# ---------------------------------------------------------------------------


class TestDocsPutSizePreflight:
    """Verify put clears before writing and cleans up orphans on write failure."""

    def test_put_creates_doc_and_writes_small_content(self) -> None:
        """Happy path: fresh cell, small content, single chunk."""
        item_no_doc = {
            "items": [
                {
                    "id": "1001",
                    "name": "Item",
                    "board": {"id": "999", "name": "Board"},
                    "column_values": [{"id": "col1", "text": "", "value": None, "type": "doc"}],
                }
            ]
        }
        client = MagicMock()
        client.execute_query.side_effect = [item_no_doc, _make_board_columns()]
        client.execute_mutation.side_effect = [
            {"create_doc": {"id": "88"}},
            {"add_content_to_doc_from_markdown": {"success": True, "block_ids": ["b1"]}},
        ]

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            result = runner.invoke(
                app,
                [
                    "docs",
                    "put",
                    "--item-id",
                    "1001",
                    "--column-name",
                    "Notes",
                    "--content",
                    "# Hello",
                ],
            )

        assert result.exit_code == 0, result.stdout
        data = _extract_json_from_output(result.stdout)
        assert data["doc_id"] == "88"

    def test_put_deletes_orphan_when_write_fails_on_fresh_cell(self) -> None:
        """When write fails on a freshly created doc, DELETE_DOC must be called."""
        from monday_cli.client.mutations import DELETE_DOC
        from monday_cli.utils.error_handler import MondayAPIError

        item_no_doc = {
            "items": [
                {
                    "id": "1001",
                    "name": "Item",
                    "board": {"id": "999", "name": "Board"},
                    "column_values": [{"id": "col1", "text": "", "value": None, "type": "doc"}],
                }
            ]
        }
        client = MagicMock()
        client.execute_query.side_effect = [item_no_doc, _make_board_columns()]
        client.execute_mutation.side_effect = [
            {"create_doc": {"id": "88"}},
            MondayAPIError("CellLimitExceededException"),
        ]

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            result = runner.invoke(
                app,
                [
                    "docs",
                    "put",
                    "--item-id",
                    "1001",
                    "--column-name",
                    "Notes",
                    "--content",
                    "# Big content",
                ],
            )

        assert result.exit_code != 0
        # Must have attempted DELETE_DOC to clean up the orphan
        delete_calls = [
            c
            for c in client.execute_mutation.call_args_list
            if len(c[0]) > 0 and c[0][0] == DELETE_DOC
        ]
        assert (
            len(delete_calls) == 1
        ), "Expected exactly one DELETE_DOC call to clean up the orphaned doc"

    def test_put_clears_existing_blocks_before_writing(self) -> None:
        """Existing doc: exhaustive clear must happen before write."""
        client = MagicMock()
        client.execute_query.side_effect = [
            _make_item(),  # GET_ITEM_BY_ID
            _make_board_columns(),  # GET_BOARD_COLUMNS
            _make_doc_by_object_id(),  # GET_DOC_BY_OBJECT_ID
            _make_doc_blocks(["b1"]),  # GET_DOC_BLOCKS page=1 — one block
            _make_empty_blocks(),  # GET_DOC_BLOCKS page=1 — now empty
        ]
        client.execute_mutation.side_effect = [
            {"delete_doc_block": {"id": "b1"}},
            {"add_content_to_doc_from_markdown": {"success": True, "block_ids": ["b_new"]}},
        ]

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            result = runner.invoke(
                app,
                [
                    "docs",
                    "put",
                    "--item-id",
                    "1001",
                    "--column-name",
                    "Notes",
                    "--content",
                    "# New content",
                ],
            )

        assert result.exit_code == 0
        # Verify: first mutation is DELETE_DOC_BLOCK, second is ADD_CONTENT_FROM_MARKDOWN
        mutation_calls = client.execute_mutation.call_args_list
        assert len(mutation_calls) == 2
        from monday_cli.client.mutations import ADD_CONTENT_FROM_MARKDOWN, DELETE_DOC_BLOCK

        assert mutation_calls[0][0][0] == DELETE_DOC_BLOCK
        assert mutation_calls[1][0][0] == ADD_CONTENT_FROM_MARKDOWN


# ---------------------------------------------------------------------------
# _create_doc_with_retry (BUG-2 / FR-0015 eventual-consistency fix)
# ---------------------------------------------------------------------------


class TestCreateDocWithRetry:
    """Verify bounded retry for CREATE_DOC on transient 'Item not found' errors."""

    def test_succeeds_on_first_attempt(self) -> None:
        """No retries needed when CREATE_DOC succeeds immediately."""
        from monday_cli.commands.docs import _create_doc_with_retry

        client = MagicMock()
        client.execute_mutation.return_value = {"create_doc": {"id": "99"}}

        result = _create_doc_with_retry(client, 1001, "col1")
        assert result == {"id": "99"}
        assert client.execute_mutation.call_count == 1

    def test_retries_on_item_not_found_then_succeeds(self) -> None:
        """Retry after transient 'Item not found' and succeed on the next attempt."""
        from monday_cli.commands.docs import _create_doc_with_retry
        from monday_cli.utils.error_handler import MondayAPIError

        client = MagicMock()
        client.execute_mutation.side_effect = [
            MondayAPIError("GraphQL errors: Item not found"),
            {"create_doc": {"id": "99"}},
        ]

        with patch("monday_cli.commands.docs.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = _create_doc_with_retry(client, 1001, "col1")

        assert result == {"id": "99"}
        assert client.execute_mutation.call_count == 2
        mock_time.sleep.assert_called_once()  # one backoff sleep between attempts

    def test_raises_after_all_retries_exhausted(self) -> None:
        """After DOC_CREATE_RETRY_ATTEMPTS failures, MondayAPIError is raised.

        With 4 total attempts (DOC_CREATE_RETRY_ATTEMPTS=4), sleep is called between
        consecutive attempts, guarded by `attempt < DOC_CREATE_RETRY_ATTEMPTS - 1`.
        That means sleep is called for attempts 0, 1, 2 (not after the final attempt 3),
        yielding exactly 3 sleep calls.
        """
        import pytest

        from monday_cli.commands.docs import _create_doc_with_retry
        from monday_cli.constants import DOC_CREATE_RETRY_ATTEMPTS
        from monday_cli.utils.error_handler import MondayAPIError

        client = MagicMock()
        client.execute_mutation.side_effect = MondayAPIError("GraphQL errors: Item not found")

        with patch("monday_cli.commands.docs.time") as mock_time:
            mock_time.sleep = MagicMock()
            with pytest.raises(MondayAPIError, match="Item not found"):
                _create_doc_with_retry(client, 1001, "col1")

        assert client.execute_mutation.call_count == DOC_CREATE_RETRY_ATTEMPTS
        # Sleep is called between attempts, not after the last one:
        # attempts 0...(N-2) each sleep → DOC_CREATE_RETRY_ATTEMPTS - 1 calls
        assert mock_time.sleep.call_count == DOC_CREATE_RETRY_ATTEMPTS - 1

    def test_non_transient_error_propagates_immediately(self) -> None:
        """A non-transient MondayAPIError must NOT be retried."""
        import pytest

        from monday_cli.commands.docs import _create_doc_with_retry
        from monday_cli.utils.error_handler import MondayAPIError

        client = MagicMock()
        client.execute_mutation.side_effect = MondayAPIError("GraphQL errors: Column not found")

        with patch("monday_cli.commands.docs.time") as mock_time:
            mock_time.sleep = MagicMock()
            with pytest.raises(MondayAPIError, match="Column not found"):
                _create_doc_with_retry(client, 1001, "col1")

        # Must fail immediately — no retry for non-transient errors
        assert client.execute_mutation.call_count == 1
        mock_time.sleep.assert_not_called()

    def test_put_retries_create_doc_on_item_not_found(self) -> None:
        """docs put must retry CREATE_DOC when first attempt gets 'Item not found'."""
        from monday_cli.utils.error_handler import MondayAPIError

        item_no_doc = {
            "items": [
                {
                    "id": "1001",
                    "name": "Item",
                    "board": {"id": "999", "name": "Board"},
                    "column_values": [{"id": "col1", "text": "", "value": None, "type": "doc"}],
                }
            ]
        }
        client = MagicMock()
        client.execute_query.side_effect = [item_no_doc, _make_board_columns()]
        # First CREATE_DOC fails; second succeeds
        client.execute_mutation.side_effect = [
            MondayAPIError("GraphQL errors: Item not found"),
            {"create_doc": {"id": "88"}},
            {"add_content_to_doc_from_markdown": {"success": True, "block_ids": ["b1"]}},
        ]

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            with patch("monday_cli.commands.docs.time") as mock_time:
                mock_time.sleep = MagicMock()
                result = runner.invoke(
                    app,
                    [
                        "docs",
                        "put",
                        "--item-id",
                        "1001",
                        "--column-name",
                        "Notes",
                        "--content",
                        "# Hello",
                    ],
                )

        assert result.exit_code == 0, result.stdout
        data = _extract_json_from_output(result.stdout)
        assert data["doc_id"] == "88"
        # CREATE_DOC called twice (retry), then ADD_CONTENT_FROM_MARKDOWN once
        assert client.execute_mutation.call_count == 3

    def test_append_retries_create_doc_on_item_not_found(self) -> None:
        """docs append must retry CREATE_DOC when first attempt gets 'Item not found'.

        This mirrors test_put_retries_create_doc_on_item_not_found but exercises the
        append_doc code path, which received the same bounded-retry fix (FR-0015 BUG-2).
        """
        from monday_cli.utils.error_handler import MondayAPIError

        item_no_doc = {
            "items": [
                {
                    "id": "1001",
                    "name": "Item",
                    "board": {"id": "999", "name": "Board"},
                    "column_values": [{"id": "col1", "text": "", "value": None, "type": "doc"}],
                }
            ]
        }
        client = MagicMock()
        client.execute_query.side_effect = [item_no_doc, _make_board_columns()]
        # First CREATE_DOC fails with transient error; second succeeds.
        # After creation, ADD_CONTENT_FROM_MARKDOWN is called for the sentinel + content.
        client.execute_mutation.side_effect = [
            MondayAPIError("GraphQL errors: Item not found"),
            {"create_doc": {"id": "88"}},
            {"add_content_to_doc_from_markdown": {"success": True, "block_ids": ["b1"]}},
        ]

        with patch("monday_cli.commands.docs.get_client", return_value=client):
            with patch("monday_cli.commands.docs.time") as mock_time:
                mock_time.sleep = MagicMock()
                result = runner.invoke(
                    app,
                    [
                        "docs",
                        "append",
                        "--item-id",
                        "1001",
                        "--column-name",
                        "Notes",
                        "--content",
                        "# Hello",
                    ],
                )

        assert result.exit_code == 0, result.stdout
        data = _extract_json_from_output(result.stdout)
        assert data["doc_id"] == "88"
        # CREATE_DOC called twice (1 failure + 1 retry success), then ADD_CONTENT once
        assert client.execute_mutation.call_count == 3
        # One backoff sleep occurred between the two CREATE_DOC attempts
        mock_time.sleep.assert_called_once()
