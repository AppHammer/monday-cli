"""Unit tests for `monday docs get` (FR-0004).

Covers:
- Default JSON output when Markdown export succeeds (AC1, AC2, AC3)
- Default JSON output when Markdown export is unsupported — markdown null, blocks present (AC2, AC3)
- --raw / --markdown success path: unwrapped Markdown on stdout (AC5)
- --raw / --markdown when export is unsupported: error on stderr, non-zero exit (AC6)
- Empty/absent doc keeps existing non-zero exit behaviour (AC existing)
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from monday_cli.cli import app

# Typer 0.27+ CliRunner exposes result.stdout and result.stderr separately.
# No mix_stderr parameter needed — the runner already separates them.
runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(column_id: str = "col1", object_id: str = "42"):
    """Return a minimal items API response for a single item."""
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


def _make_board_columns(column_id: str = "col1"):
    """Return board columns response containing one doc column."""
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


def _make_doc_by_object_id(internal_id: str = "77"):
    """Return docs API response mapping object_id -> internal id."""
    return {"docs": [{"id": internal_id, "object_id": "42"}]}


def _make_export_success(markdown: str = "# Hello\n\nWorld"):
    """Return a successful Markdown export response."""
    return {"export_markdown_from_doc": {"success": True, "markdown": markdown, "error": None}}


def _make_export_failure(error: str = "Export not supported"):
    """Return a failed Markdown export response."""
    return {"export_markdown_from_doc": {"success": False, "markdown": None, "error": error}}


def _make_doc_blocks(internal_id: str = "77"):
    """Return docs blocks response."""
    return {
        "docs": [
            {
                "id": internal_id,
                "blocks": [
                    {"id": "b1", "type": "normal_text", "content": '{"insert":"Hello"}'},
                    {"id": "b2", "type": "normal_text", "content": '{"insert":"World"}'},
                ],
            }
        ]
    }


def _make_no_docs():
    """Return an empty docs response (no content)."""
    return {"docs": []}


def _build_mock_client(responses: list[Any]) -> MagicMock:
    """Build a mock client whose execute_query side_effect cycles through responses."""
    client = MagicMock()
    client.execute_query.side_effect = responses
    return client


# ---------------------------------------------------------------------------
# Test: Default JSON shape — export succeeds (AC1, AC2, AC3)
# ---------------------------------------------------------------------------

class TestDefaultJsonExportSucceeds:
    """Default path when Markdown export succeeds."""

    def _invoke(self, markdown: str = "# Hello\n\nWorld"):
        mock_client = _build_mock_client([
            _make_item(),                          # GET_ITEM_BY_ID
            _make_board_columns(),                  # GET_BOARD_COLUMNS
            _make_doc_by_object_id(),               # GET_DOC_BY_OBJECT_ID
            _make_export_success(markdown),         # EXPORT_MARKDOWN_FROM_DOC
            _make_doc_blocks(),                     # GET_DOC_BLOCKS
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            return runner.invoke(
                app,
                ["docs", "get", "--item-id", "1001", "--column-name", "Notes"],
            )

    def test_exits_zero(self):
        result = self._invoke()
        assert result.exit_code == 0, result.output

    def test_stdout_is_valid_json(self):
        result = self._invoke()
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_has_markdown_key(self):
        result = self._invoke()
        data = json.loads(result.stdout)
        assert "markdown" in data

    def test_has_blocks_key(self):
        result = self._invoke()
        data = json.loads(result.stdout)
        assert "blocks" in data

    def test_markdown_is_non_null_string(self):
        result = self._invoke(markdown="# Test Doc")
        data = json.loads(result.stdout)
        assert data["markdown"] == "# Test Doc"

    def test_blocks_are_populated(self):
        result = self._invoke()
        data = json.loads(result.stdout)
        assert isinstance(data["blocks"], list)
        assert len(data["blocks"]) > 0

    def test_no_bare_markdown_on_stdout(self):
        """Stdout must be valid JSON — not bare, unwrapped Markdown."""
        result = self._invoke(markdown="# Should not appear raw")
        # If JSON parses, it's not bare Markdown
        data = json.loads(result.stdout)
        # The markdown content lives inside the JSON envelope
        assert data["markdown"] is not None

    def test_both_api_calls_made(self):
        """Default success path must call BOTH EXPORT_MARKDOWN_FROM_DOC and GET_DOC_BLOCKS.

        This locks in the intentional two-API-call design so a future change can't
        silently drop the blocks fetch and still pass the other assertions.
        Expected call sequence: GET_ITEM_BY_ID, GET_BOARD_COLUMNS, GET_DOC_BY_OBJECT_ID,
        EXPORT_MARKDOWN_FROM_DOC, GET_DOC_BLOCKS — 5 execute_query calls total.
        """
        mock_client = _build_mock_client([
            _make_item(),
            _make_board_columns(),
            _make_doc_by_object_id(),
            _make_export_success(),
            _make_doc_blocks(),
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                ["docs", "get", "--item-id", "1001", "--column-name", "Notes"],
            )
        assert result.exit_code == 0
        # Exactly 5 calls: GET_ITEM_BY_ID, GET_BOARD_COLUMNS, GET_DOC_BY_OBJECT_ID,
        # EXPORT_MARKDOWN_FROM_DOC, GET_DOC_BLOCKS
        assert mock_client.execute_query.call_count == 5


# ---------------------------------------------------------------------------
# Test: Default JSON shape — export unsupported (AC2, AC3 lossless)
# ---------------------------------------------------------------------------

class TestDefaultJsonExportUnsupported:
    """Default path when Markdown export is unsupported."""

    def _invoke(self):
        mock_client = _build_mock_client([
            _make_item(),
            _make_board_columns(),
            _make_doc_by_object_id(),
            _make_export_failure(),
            _make_doc_blocks(),
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            return runner.invoke(
                app,
                ["docs", "get", "--item-id", "1001", "--column-name", "Notes"],
            )

    def test_exits_zero(self):
        result = self._invoke()
        assert result.exit_code == 0, result.output

    def test_stdout_is_valid_json(self):
        result = self._invoke()
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_markdown_is_null(self):
        """When export is unsupported, markdown must be null (None in Python)."""
        result = self._invoke()
        data = json.loads(result.stdout)
        assert data["markdown"] is None

    def test_blocks_are_still_populated(self):
        """Payload is lossless even when Markdown export is unsupported."""
        result = self._invoke()
        data = json.loads(result.stdout)
        assert isinstance(data["blocks"], list)
        assert len(data["blocks"]) > 0

    def test_no_json_fallback_shape(self):
        """The old fallback emitted the raw docs[0] object; new shape is always {markdown, blocks}."""
        result = self._invoke()
        data = json.loads(result.stdout)
        # Must have exactly these two keys at the top level (may have more in blocks)
        assert set(data.keys()) == {"markdown", "blocks"}


# ---------------------------------------------------------------------------
# Test: --raw success (AC5)
# ---------------------------------------------------------------------------

class TestRawFlagSuccess:
    """--raw / --markdown flag with a successful Markdown export."""

    _markdown_text = "# Raw Document\n\nSome content here."

    def _invoke(self, flag: str = "--raw"):
        mock_client = _build_mock_client([
            _make_item(),
            _make_board_columns(),
            _make_doc_by_object_id(),
            _make_export_success(self._markdown_text),
            # GET_DOC_BLOCKS should NOT be called in raw mode
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            return runner.invoke(
                app,
                ["docs", "get", "--item-id", "1001", "--column-name", "Notes", flag],
            )

    def test_raw_exits_zero(self):
        result = self._invoke("--raw")
        assert result.exit_code == 0, result.output

    def test_raw_stdout_is_markdown_not_json(self):
        """stdout must be the raw Markdown text, not a JSON object."""
        result = self._invoke("--raw")
        # It should NOT be parseable as JSON (it's bare Markdown)
        with pytest.raises((json.JSONDecodeError, ValueError)):
            json.loads(result.stdout)

    def test_raw_stdout_equals_markdown(self):
        """stdout content matches the exported Markdown exactly (plus trailing newline from echo)."""
        result = self._invoke("--raw")
        assert self._markdown_text in result.stdout

    def test_markdown_alias_exits_zero(self):
        """--markdown is a true alias for --raw."""
        result = self._invoke("--markdown")
        assert result.exit_code == 0, result.output

    def test_markdown_alias_stdout_equals_raw(self):
        """--markdown produces identical output to --raw."""
        raw_result = self._invoke("--raw")
        md_result = self._invoke("--markdown")
        assert raw_result.stdout == md_result.stdout

    def test_raw_does_not_fetch_blocks(self):
        """In --raw mode, GET_DOC_BLOCKS must NOT be called (blocks not needed)."""
        mock_client = _build_mock_client([
            _make_item(),
            _make_board_columns(),
            _make_doc_by_object_id(),
            _make_export_success(self._markdown_text),
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                ["docs", "get", "--item-id", "1001", "--column-name", "Notes", "--raw"],
            )
        assert result.exit_code == 0
        # Only 4 calls: GET_ITEM_BY_ID, GET_BOARD_COLUMNS, GET_DOC_BY_OBJECT_ID, EXPORT_MARKDOWN_FROM_DOC
        assert mock_client.execute_query.call_count == 4


# ---------------------------------------------------------------------------
# Test: --raw with unsupported export (AC6)
# ---------------------------------------------------------------------------

class TestRawFlagUnsupportedExport:
    """--raw when Markdown export is unsupported: error on stderr, non-zero exit."""

    def _invoke(self, flag: str = "--raw"):
        mock_client = _build_mock_client([
            _make_item(),
            _make_board_columns(),
            _make_doc_by_object_id(),
            _make_export_failure("Export not supported for this document type"),
            # GET_DOC_BLOCKS must NOT be called in --raw mode
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            return runner.invoke(
                app,
                ["docs", "get", "--item-id", "1001", "--column-name", "Notes", flag],
            )

    def test_raw_exits_nonzero(self):
        result = self._invoke("--raw")
        assert result.exit_code != 0

    def test_error_goes_to_stderr(self):
        """Error message must appear on stderr, not stdout.

        Specifically: the failure message must be in result.stderr, and
        result.stdout must be completely empty (no JSON fallback, no bare text).
        """
        result = self._invoke("--raw")
        # The error message must land on stderr
        assert "Error" in result.stderr
        # stdout must be completely empty — no fallback output
        assert result.stdout.strip() == ""

    def test_no_json_on_stdout(self):
        """No JSON fallback on stdout when --raw fails."""
        result = self._invoke("--raw")
        assert result.stdout.strip() == ""

    def test_markdown_alias_also_errors(self):
        """--markdown alias also errors loudly when export is unavailable."""
        result = self._invoke("--markdown")
        assert result.exit_code != 0
        assert result.stdout.strip() == ""

    def test_does_not_fetch_blocks(self):
        """In --raw mode, GET_DOC_BLOCKS must NOT be called even on failure."""
        mock_client = _build_mock_client([
            _make_item(),
            _make_board_columns(),
            _make_doc_by_object_id(),
            _make_export_failure(),
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                ["docs", "get", "--item-id", "1001", "--column-name", "Notes", "--raw"],
            )
        assert result.exit_code != 0
        # Only 4 calls: GET_ITEM_BY_ID, GET_BOARD_COLUMNS, GET_DOC_BY_OBJECT_ID, EXPORT_MARKDOWN_FROM_DOC
        assert mock_client.execute_query.call_count == 4


# ---------------------------------------------------------------------------
# Test: Empty/absent doc keeps existing non-zero exit
# ---------------------------------------------------------------------------

class TestEmptyOrAbsentDoc:
    """Existing not-found behaviour is preserved."""

    def test_no_doc_column_value_exits_nonzero(self):
        """When the doc column has no value, exit non-zero (no document found)."""
        item_no_doc = {
            "items": [
                {
                    "id": "1001",
                    "name": "Test Item",
                    "board": {"id": "999", "name": "Board"},
                    "column_values": [
                        {
                            "id": "col1",
                            "text": "",
                            "value": None,  # No doc linked
                            "type": "doc",
                        }
                    ],
                }
            ]
        }
        mock_client = _build_mock_client([
            item_no_doc,
            _make_board_columns(),
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                ["docs", "get", "--item-id", "1001", "--column-name", "Notes"],
            )
        assert result.exit_code != 0

    def test_blocks_query_returns_no_docs_exits_nonzero(self):
        """When GET_DOC_BLOCKS returns no docs, exit non-zero."""
        mock_client = _build_mock_client([
            _make_item(),
            _make_board_columns(),
            _make_doc_by_object_id(),
            _make_export_failure(),  # export fails
            _make_no_docs(),          # and blocks also empty
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                ["docs", "get", "--item-id", "1001", "--column-name", "Notes"],
            )
        assert result.exit_code != 0

    def test_item_not_found_exits_nonzero(self):
        """When the item doesn't exist, exit non-zero."""
        mock_client = _build_mock_client([
            {"items": []},  # GET_ITEM_BY_ID returns nothing
        ])
        with patch("monday_cli.commands.docs.get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                ["docs", "get", "--item-id", "9999", "--column-name", "Notes"],
            )
        assert result.exit_code != 0
