"""FR-0009 Epic C (#60): items list --status / --status-column.

Covers label matching (C1), multi-status-column disambiguation (C2), bad
column / bad label teaching errors (C2/C3), unset-status exclusion (C3),
valid-label-zero-matches (X8), and group AND status composition (C4).
"""

from __future__ import annotations

import json

from monday_cli.cli import app

from .conftest import FakeClient, status_column

STATUS_COL = status_column("status_col", "Status", {"0": "Not Started", "1": "Done", "2": "Stuck"})
PRIORITY_COL = status_column("priority_col", "Priority", {"0": "Low", "1": "High"})


def _item(item_id: str, group: dict | None, status_text: str, priority_text: str = "") -> dict:
    return {
        "id": item_id,
        "name": f"item-{item_id}",
        "state": "active",
        "group": group,
        "column_values": [
            {"id": "status_col", "text": status_text, "type": "status"},
            {"id": "priority_col", "text": priority_text, "type": "status"},
        ],
    }


GROUP_A = {"id": "group_a", "title": "In Progress"}
GROUP_B = {"id": "group_b", "title": "Backlog"}

ITEMS = [
    _item("1", GROUP_A, "Done", "High"),
    _item("2", GROUP_A, "Stuck", "Low"),
    _item("3", GROUP_B, "Done", "Low"),
    _item("4", GROUP_A, "", "High"),  # unset status
]


_GROUPS = [GROUP_A, GROUP_B]


def _single_status_client() -> FakeClient:
    return FakeClient(board_items=[dict(i) for i in ITEMS], columns=[STATUS_COL], groups=_GROUPS)


def _two_status_client() -> FakeClient:
    return FakeClient(
        board_items=[dict(i) for i in ITEMS],
        columns=[STATUS_COL, PRIORITY_COL],
        groups=_GROUPS,
    )


def test_single_status_column_filters_case_insensitive(runner, use_client) -> None:
    use_client(_single_status_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--status", "done"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert sorted(i["id"] for i in data["items"]) == ["1", "3"]
    assert data["status_filter"] == "done"
    assert data["status_column"] == "Status"


def test_unset_status_excluded_from_match(runner, use_client) -> None:
    use_client(_single_status_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--status", "Done"])
    data = json.loads(result.stdout)
    assert "4" not in [i["id"] for i in data["items"]]


def test_multiple_status_columns_requires_status_column(runner, use_client) -> None:
    use_client(_two_status_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--status", "Done"])
    assert result.exit_code == 1
    # FR-0008: errors go to stderr, stdout stays clean JSON-only.
    assert "Status" in result.stderr and "Priority" in result.stderr
    assert "--status-column" in result.stderr


def test_status_column_selects_priority(runner, use_client) -> None:
    use_client(_two_status_client())
    result = runner.invoke(
        app,
        ["items", "list", "--board-id", "1", "--status", "High", "--status-column", "Priority"],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert sorted(i["id"] for i in data["items"]) == ["1", "4"]
    assert data["status_column"] == "Priority"


def test_non_status_column_is_teaching_error(runner, use_client) -> None:
    use_client(_two_status_client())
    result = runner.invoke(
        app,
        ["items", "list", "--board-id", "1", "--status", "High", "--status-column", "Nonexistent"],
    )
    assert result.exit_code == 1
    assert "Available status columns" in result.stderr


def test_bad_label_lists_chosen_column_labels(runner, use_client) -> None:
    use_client(_single_status_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--status", "Nope"])
    assert result.exit_code == 1
    assert "Available statuses" in result.stderr
    assert "Done" in result.stderr and "Stuck" in result.stderr


def test_valid_label_zero_matches_returns_empty_exit_0(runner, use_client) -> None:
    # "Not Started" is a valid label but no item has it -> items: [], exit 0.
    use_client(_single_status_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--status", "Not Started"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["items"] == []
    assert data["status_filter"] == "Not Started"


def test_status_and_group_compose_as_and(runner, use_client) -> None:
    use_client(_single_status_client())
    result = runner.invoke(
        app,
        ["items", "list", "--board-id", "1", "--status", "Done", "--group", "In Progress"],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    # Only item 1 is Done AND in "In Progress" (item 3 is Done but in Backlog).
    assert [i["id"] for i in data["items"]] == ["1"]
    assert data["group_filter"] == "In Progress"
    assert data["status_filter"] == "Done"
    assert data["status_column"] == "Status"
