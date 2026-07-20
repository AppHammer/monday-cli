"""Unit tests for `monday columns list` (issue #89 / FR-0018).

Exercises the columns list command with a FakeClient (zero network traffic)
to lock in the output contract:

  * AC1/AC2: JSON output has board_id, board_name, columns[], total_count;
    status and dropdown columns include parsed labels; non-labelled columns
    omit the labels key.
  * AC3: --table keeps stdout non-JSON (Rich table only).
  * AC4/AC5: missing --board-id and board-not-found each exit 1 with a
    teaching message on stderr and clean stdout.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from monday_cli.cli import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers / test data builders
# ---------------------------------------------------------------------------


def _text_column(col_id: str, title: str) -> dict[str, Any]:
    """Plain text column — no settings_str labels."""
    return {"id": col_id, "title": title, "type": "text", "settings_str": "{}"}


def _status_column(col_id: str, title: str, labels: dict[str, str]) -> dict[str, Any]:
    """Status column with a dict-style labels map."""
    return {
        "id": col_id,
        "title": title,
        "type": "status",
        "settings_str": json.dumps({"labels": labels}),
    }


def _dropdown_column(col_id: str, title: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Dropdown column with a list-style labels array (read-back shape).

    Each entry has {"id": int, "name": str} — matching the verified live
    API shape from VERIFIED_FINDINGS.md.
    """
    return {
        "id": col_id,
        "title": title,
        "type": "dropdown",
        "settings_str": json.dumps({"labels": entries}),
    }


class FakeColumnsClient:
    """Fake MondayGraphQLClient that returns canned board/column data."""

    def __init__(
        self,
        *,
        board_name: str = "Test Board",
        columns: list[dict[str, Any]] | None = None,
        empty_boards: bool = False,
    ) -> None:
        self.board_name = board_name
        self.columns = columns or []
        self.empty_boards = empty_boards
        self.queries: list[tuple[str, Any]] = []

    def execute_query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.queries.append((query, variables))
        if "columns {" in query:
            if self.empty_boards:
                return {"boards": []}
            board_id = ((variables or {}).get("boardIds") or ["1"])[0]
            return {
                "boards": [
                    {
                        "id": board_id,
                        "name": self.board_name,
                        "columns": self.columns,
                    }
                ]
            }
        raise AssertionError(f"Unexpected query:\n{query[:120]}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def use_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch columns.get_client to return the supplied FakeColumnsClient."""

    def _use(client: FakeColumnsClient) -> FakeColumnsClient:
        monkeypatch.setattr("monday_cli.commands.columns.get_client", lambda: client)
        return client

    return _use


def _invoke(*args: str) -> Any:
    return runner.invoke(app, list(args))


# ---------------------------------------------------------------------------
# AC1: basic JSON output shape
# ---------------------------------------------------------------------------


def test_lists_all_columns_as_json(use_client: Any) -> None:
    """AC1: default output is a single JSON document with the required keys."""
    cols = [
        _text_column("name", "Name"),
        _status_column("status", "Status", {"0": "Done", "1": "Working on it"}),
    ]
    use_client(FakeColumnsClient(board_name="My Board", columns=cols))

    result = _invoke("columns", "list", "--board-id", "999")

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["board_id"] == "999"
    assert data["board_name"] == "My Board"
    assert data["total_count"] == 2
    col_ids = [c["column_id"] for c in data["columns"]]
    assert "name" in col_ids
    assert "status" in col_ids
    # Every column must have column_id, title, type
    for col in data["columns"]:
        assert "column_id" in col
        assert "title" in col
        assert "type" in col


# ---------------------------------------------------------------------------
# AC2: status label parsing — sorted ascending by index
# ---------------------------------------------------------------------------


def test_status_labels_sorted_by_index(use_client: Any) -> None:
    """AC2: status labels are parsed and sorted by integer index ascending."""
    # Deliberately pass labels out of natural dict order
    cols = [
        _status_column(
            "status_col",
            "Priority",
            {"2": "Stuck", "0": "Working on it", "1": "Done"},
        )
    ]
    use_client(FakeColumnsClient(columns=cols))

    result = _invoke("columns", "list", "--board-id", "1")

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    status_col = next(c for c in data["columns"] if c["column_id"] == "status_col")
    assert "labels" in status_col
    labels = status_col["labels"]
    indexes = [lbl["index"] for lbl in labels]
    assert indexes == sorted(indexes), "labels must be sorted by index"
    assert labels[0] == {"index": 0, "label": "Working on it"}
    assert labels[1] == {"index": 1, "label": "Done"}
    assert labels[2] == {"index": 2, "label": "Stuck"}


# ---------------------------------------------------------------------------
# AC2: dropdown label parsing — normalized to {index, label}
# ---------------------------------------------------------------------------


def test_dropdown_labels_normalized(use_client: Any) -> None:
    """AC2: dropdown labels (list of {id,name}) are normalized to {index,label}."""
    cols = [
        _dropdown_column(
            "dropdown_col",
            "Category",
            [{"id": 2, "name": "Beta"}, {"id": 1, "name": "Alpha"}],
        )
    ]
    use_client(FakeColumnsClient(columns=cols))

    result = _invoke("columns", "list", "--board-id", "1")

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    dropdown_col = next(c for c in data["columns"] if c["column_id"] == "dropdown_col")
    assert "labels" in dropdown_col
    labels = dropdown_col["labels"]
    # Should be sorted by id (index) ascending
    indexes = [lbl["index"] for lbl in labels]
    assert indexes == sorted(indexes)
    assert labels[0] == {"index": 1, "label": "Alpha"}
    assert labels[1] == {"index": 2, "label": "Beta"}


# ---------------------------------------------------------------------------
# AC2: non-labelled column omits the labels key
# ---------------------------------------------------------------------------


def test_non_labelled_column_omits_labels_key(use_client: Any) -> None:
    """AC2: text columns must have NO 'labels' key in the output (omit, not empty list)."""
    cols = [_text_column("notes", "Notes")]
    use_client(FakeColumnsClient(columns=cols))

    result = _invoke("columns", "list", "--board-id", "1")

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    text_col = next(c for c in data["columns"] if c["column_id"] == "notes")
    assert "labels" not in text_col, "Non-labelled columns must omit the 'labels' key entirely"


# ---------------------------------------------------------------------------
# AC3: --table keeps stdout non-JSON
# ---------------------------------------------------------------------------


def test_table_flag_stdout_is_not_json(use_client: Any) -> None:
    """AC3: --table renders a Rich table; stdout contains no JSON document."""
    cols = [_text_column("name", "Name")]
    use_client(FakeColumnsClient(columns=cols))

    result = _invoke("columns", "list", "--board-id", "1", "--table")

    assert result.exit_code == 0, result.stderr
    # stdout must NOT be parseable as JSON
    try:
        json.loads(result.stdout)
        pytest.fail("--table stdout must not be a JSON document")
    except json.JSONDecodeError:
        pass  # expected: table output is not JSON


# ---------------------------------------------------------------------------
# AC5: missing --board-id → teaching error + exit 1
# ---------------------------------------------------------------------------


def test_missing_board_id_exits_1(use_client: Any) -> None:
    """AC5: omitting --board-id produces a teaching error on stderr and exits 1."""
    use_client(FakeColumnsClient())

    result = _invoke("columns", "list")

    assert result.exit_code == 1
    assert result.stdout.strip() == "", "stdout must be empty on missing board-id error"
    assert "board" in result.stderr.lower() or "board-id" in result.stderr.lower()


# ---------------------------------------------------------------------------
# AC4: board not found → stderr warning + exit 1
# ---------------------------------------------------------------------------


def test_board_not_found_exits_1(use_client: Any) -> None:
    """AC4: when the API returns no boards, exit 1 with a warning on stderr."""
    use_client(FakeColumnsClient(empty_boards=True))

    result = _invoke("columns", "list", "--board-id", "9999")

    assert result.exit_code == 1
    assert result.stdout.strip() == "", "stdout must be empty on board-not-found error"
    assert "not found" in result.stderr.lower() or "access" in result.stderr.lower()
