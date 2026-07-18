"""Read-coverage integration tests for `monday statuses list` (US-0002-02).

Statuses has no create/delete surface, so this suite is purely read-only:
it proves `statuses list --board-id <test_board_id>` returns the status
columns on the shared scratch test board along with their label options
(the schema `items update` / `subitems update` rely on for status writes),
and smoke-checks `--table` rendering. Nothing is created or deleted on any
board.
"""

from __future__ import annotations

import pytest

from tests.integration.helpers import run_cli


@pytest.mark.integration
def test_list_returns_status_columns_with_labels(test_board_id: str) -> None:
    data = run_cli("statuses", "list", "--board-id", test_board_id)

    assert isinstance(data, dict)
    assert data.get("board_id") == test_board_id
    assert "board_name" in data
    assert "status_columns" in data

    status_columns = data["status_columns"]
    assert isinstance(status_columns, list)
    assert len(status_columns) > 0, "test board must have at least one status column"

    for column in status_columns:
        assert "column_id" in column
        assert "column_title" in column
        assert isinstance(column["statuses"], list)
        assert len(column["statuses"]) > 0

        for status in column["statuses"]:
            assert "index" in status
            assert "label" in status
            assert isinstance(status["index"], int)
            assert isinstance(status["label"], str)
            assert status["label"] != ""


@pytest.mark.integration
def test_list_table_output_renders_without_error(test_board_id: str) -> None:
    output = run_cli("statuses", "list", "--board-id", test_board_id, "--table", raw=True)

    assert output.strip() != ""
