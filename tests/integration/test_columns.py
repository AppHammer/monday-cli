"""Integration tests for `monday columns list` (issue #89 / FR-0018).

Read-only tests against the shared scratch test board (18422673411). Nothing
is created or deleted — this suite only exercises the list command.
"""

from __future__ import annotations

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
