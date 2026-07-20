"""Integration tests for `monday columns list` and `columns create` (FR-0018).

Read-only list tests run against the shared scratch test board (18422673411)
without creating or deleting anything. The create tests (issue #86) use the
``created_column`` factory fixture from conftest.py to provision real columns
and tear them down at the end of the test.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.integration.helpers import run_cli


@pytest.mark.integration
def test_columns_list_on_test_board(test_board_id: str) -> None:
    """AC1/AC2: columns list returns every column with parsed status labels.

    Asserts:
      - Exit 0 and clean JSON output (enforced by run_cli / _extract_json).
      - Top-level keys: board_id, board_name, columns, total_count.
      - The pre-existing "Status" status column appears with non-empty labels.
      - Every label has 'index' (int) and 'label' (non-empty str).
      - Every column has column_id, title, type.
    """
    data = run_cli("columns", "list", "--board-id", test_board_id)

    assert isinstance(data, dict)
    assert data.get("board_id") == test_board_id
    assert "board_name" in data
    assert isinstance(data.get("columns"), list)
    assert isinstance(data.get("total_count"), int)
    assert data["total_count"] == len(data["columns"])
    assert data["total_count"] > 0, "test board must have at least one column"

    # Every column must carry the required keys
    for col in data["columns"]:
        assert "column_id" in col, f"missing column_id in {col}"
        assert "title" in col, f"missing title in {col}"
        assert "type" in col, f"missing type in {col}"

    # The pre-existing "Status" status column must appear with labels
    status_cols = [
        c for c in data["columns"] if c.get("title") == "Status" and c.get("type") == "status"
    ]
    assert len(status_cols) >= 1, (
        "Test board 18422673411 must have a status column titled 'Status' "
        "— board may have been mutated or the test board id changed."
    )
    status_col = status_cols[0]
    assert "labels" in status_col, "Status column must include parsed labels"
    labels = status_col["labels"]
    assert (
        isinstance(labels, list) and len(labels) > 0
    ), "Status column must have at least one label"
    for lbl in labels:
        assert isinstance(lbl.get("index"), int), f"label index must be int: {lbl}"
        assert (
            isinstance(lbl.get("label"), str) and lbl["label"]
        ), f"label string must be non-empty: {lbl}"
    # Labels must be sorted by index
    indexes = [lbl["index"] for lbl in labels]
    assert indexes == sorted(indexes), "status labels must be sorted by index"


# ---------------------------------------------------------------------------
# columns create — issue #86 / AC1 + AC2
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_create_text_column_round_trips(
    test_board_id: str,
    created_column: Callable[..., str],
) -> None:
    """AC1: a created text column appears in columns list with the correct type.

    Creates a text column via the CLI, then verifies it appears in the
    `columns list` output.  Teardown removes the column (via #88 once merged).
    """
    column_id = created_column("text-col", "text")

    # Verify the column appears in the board's column list
    data = run_cli("columns", "list", "--board-id", test_board_id)
    assert isinstance(data, dict)
    all_ids = [c.get("column_id") for c in data.get("columns", [])]
    assert column_id in all_ids, (
        f"Newly created column {column_id} not found in columns list. "
        f"Present columns: {all_ids}"
    )

    # The column must have type "text" (exact string from Monday API)
    col = next(c for c in data["columns"] if c.get("column_id") == column_id)
    assert col.get("type") == "text", f"Expected type 'text', got {col.get('type')!r}"


@pytest.mark.integration
def test_create_status_column_with_labels_verified(
    test_board_id: str,
    created_column: Callable[..., str],
) -> None:
    """AC2: a status column created with --labels has those labels verifiable via columns list.

    Creates a status column with two labels ("Low" and "High"), then asserts
    that `columns list` returns them in the correct seeded order (index 1 →
    Low, index 2 → High), confirming the verified defaults shape round-trips.
    """
    column_id = created_column("status-col", "status", labels="Low,High")

    data = run_cli("columns", "list", "--board-id", test_board_id)
    assert isinstance(data, dict)

    col = next(
        (c for c in data.get("columns", []) if c.get("column_id") == column_id),
        None,
    )
    assert col is not None, f"Newly created status column {column_id} not found in columns list."
    assert col.get("type") == "status"
    assert "labels" in col, "Status column must expose parsed labels"

    label_map = {lbl["index"]: lbl["label"] for lbl in col["labels"]}
    assert label_map.get(1) == "Low", f"Expected index 1 → 'Low', got {label_map}"
    assert label_map.get(2) == "High", f"Expected index 2 → 'High', got {label_map}"
