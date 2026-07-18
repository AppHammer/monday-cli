"""Read-coverage integration tests for `monday boards list` (US-0002-02).

Boards has no create/delete surface exercised here, so this suite is
purely read-only: it proves `boards list` returns parseable JSON against the
live API and confirms the shared scratch test board is discoverable through
it, exercises the `--state`, `--workspace-name`, and `--workspace-id`
filters, and smoke-checks `--table` rendering. Nothing is created or deleted
on any board.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.helpers import run_cli


def _board_ids(data: dict[str, Any]) -> set[str]:
    return {str(board["id"]) for board in data.get("boards", [])}


@pytest.mark.integration
def test_list_active_boards_includes_test_board(test_board_id: str) -> None:
    data = run_cli("boards", "list", "--state", "active")

    assert isinstance(data, dict)
    assert isinstance(data.get("boards"), list)
    assert "total_count" in data
    assert data["total_count"] == len(data["boards"])
    assert test_board_id in _board_ids(data)


@pytest.mark.integration
def test_list_state_all_still_includes_test_board(test_board_id: str) -> None:
    data = run_cli("boards", "list", "--state", "all")

    assert isinstance(data, dict)
    assert test_board_id in _board_ids(data)


@pytest.mark.integration
def test_list_filters_by_workspace_id_when_determinable(test_board_id: str) -> None:
    # Discover the test board's own workspace id from the unfiltered
    # listing, then confirm filtering by it still surfaces the board.
    all_boards = run_cli("boards", "list", "--state", "all")
    test_board = next(
        (b for b in all_boards["boards"] if str(b["id"]) == test_board_id),
        None,
    )
    assert test_board is not None, "test board must be present in the unfiltered listing"

    workspace = test_board.get("workspace")
    if not workspace or not workspace.get("id"):
        pytest.skip("Test board has no workspace id; cannot exercise --workspace-id")

    workspace_id = str(workspace["id"])

    data = run_cli(
        "boards",
        "list",
        "--state",
        "all",
        "--workspace-id",
        workspace_id,
    )

    assert isinstance(data, dict)
    assert data.get("workspace_id_filter") == int(workspace_id)
    assert test_board_id in _board_ids(data)


@pytest.mark.integration
def test_list_filters_by_workspace_name_when_determinable(test_board_id: str) -> None:
    all_boards = run_cli("boards", "list", "--state", "all")
    test_board = next(
        (b for b in all_boards["boards"] if str(b["id"]) == test_board_id),
        None,
    )
    assert test_board is not None, "test board must be present in the unfiltered listing"

    workspace = test_board.get("workspace")
    if not workspace or not workspace.get("name"):
        pytest.skip("Test board has no workspace name; cannot exercise --workspace-name")

    workspace_name = workspace["name"]

    data = run_cli(
        "boards",
        "list",
        "--state",
        "all",
        "--workspace-name",
        workspace_name,
    )

    assert isinstance(data, dict)
    assert data.get("workspace_name_filter") == workspace_name
    assert test_board_id in _board_ids(data)


@pytest.mark.integration
def test_list_table_output_renders_without_error() -> None:
    output = run_cli("boards", "list", "--state", "all", "--table", raw=True)

    assert output.strip() != ""
