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


# ---------------------------------------------------------------------------
# columns delete — issue #88 / AC1 + AC2 + AC4
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_create_then_delete_removes_column(
    test_board_id: str,
    created_column: Callable[..., str],
) -> None:
    """AC2: a column deleted with --force is no longer present in columns list.

    Creates a throwaway text column, deletes it with --force, then polls
    columns list to verify the column has actually been removed (not just
    that the delete response said so).
    """
    column_id = created_column("del-test", "text")

    # Verify it exists before deleting
    before_data = run_cli("columns", "list", "--board-id", test_board_id)
    assert isinstance(before_data, dict)
    before_ids = [c.get("column_id") for c in before_data.get("columns", [])]
    assert column_id in before_ids, (
        f"Newly created column {column_id} not found before delete attempt. "
        f"Present columns: {before_ids}"
    )

    # Delete with --force (no prompt)
    delete_data = run_cli(
        "columns",
        "delete",
        "--board-id",
        test_board_id,
        "--column-id",
        column_id,
        "--force",
        is_mutation=True,
    )
    assert isinstance(delete_data, dict)
    assert delete_data.get("deleted") is True
    assert delete_data.get("column_id") == column_id

    # Verify the column is gone from columns list (bounded poll for eventual consistency)
    from tests.integration.helpers import run_cli_until

    after_data = run_cli_until(
        lambda d: isinstance(d, dict)
        and column_id not in [c.get("column_id") for c in d.get("columns", [])],
        "columns",
        "list",
        "--board-id",
        test_board_id,
    )
    assert isinstance(after_data, dict)
    after_ids = [c.get("column_id") for c in after_data.get("columns", [])]
    assert column_id not in after_ids, (
        f"Column {column_id} still appears in columns list after deletion. "
        f"Present columns: {after_ids}"
    )


# ---------------------------------------------------------------------------
# columns update — issue #87 / AC1 + AC2 + AC3
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_update_column_title_is_verifiable_via_list(
    test_board_id: str,
    created_column: Callable[..., str],
    run_id: str,
) -> None:
    """AC1: renaming a column's title is verifiable via columns list.

    Creates a throwaway text column, updates its title via `columns update
    --title`, then polls `columns list` to confirm the new title appears.
    """
    column_id = created_column("upd-title", "text")
    new_title = f"{run_id}-renamed"

    update_data = run_cli(
        "columns",
        "update",
        "--board-id",
        test_board_id,
        "--column-id",
        column_id,
        "--title",
        new_title,
        is_mutation=True,
    )
    assert isinstance(update_data, dict)
    assert update_data.get("title") == new_title
    assert update_data.get("column_id") == column_id

    # Verify the new title is visible in columns list (bounded poll for consistency).
    from tests.integration.helpers import run_cli_until

    after_data = run_cli_until(
        lambda d: isinstance(d, dict)
        and any(
            c.get("column_id") == column_id and c.get("title") == new_title
            for c in d.get("columns", [])
        ),
        "columns",
        "list",
        "--board-id",
        test_board_id,
    )
    assert isinstance(after_data, dict)
    col = next(
        (c for c in after_data.get("columns", []) if c.get("column_id") == column_id),
        None,
    )
    assert col is not None, f"Column {column_id} not found after title update"
    assert col.get("title") == new_title, f"Expected title {new_title!r}, got {col.get('title')!r}"


@pytest.mark.integration
def test_add_label_to_status_column_is_verifiable(
    test_board_id: str,
    created_column: Callable[..., str],
) -> None:
    """AC2: --add-label adds a label to a status column, verifiable via columns list.

    Creates a throwaway status column with initial labels, then adds 'Blocked'
    via `columns update --add-label`, and confirms it appears in columns list.
    Note: --add-label requires a board item to write to. Board 18422673411 has
    pre-existing items, so this succeeds without creating a temporary item.
    """
    column_id = created_column("upd-label", "status", labels="Low,High")

    update_data = run_cli(
        "columns",
        "update",
        "--board-id",
        test_board_id,
        "--column-id",
        column_id,
        "--add-label",
        "Blocked",
        is_mutation=True,
    )
    assert isinstance(update_data, dict)
    assert "labels_changed" in update_data
    assert "Blocked" in update_data["labels_changed"].get("labels_added", [])

    # Verify the new label appears in columns list (bounded poll for consistency).
    from tests.integration.helpers import run_cli_until

    after_data = run_cli_until(
        lambda d: isinstance(d, dict)
        and any(
            c.get("column_id") == column_id
            and any(lbl.get("label") == "Blocked" for lbl in c.get("labels", []))
            for c in d.get("columns", [])
        ),
        "columns",
        "list",
        "--board-id",
        test_board_id,
    )
    assert isinstance(after_data, dict)
    col = next(
        (c for c in after_data.get("columns", []) if c.get("column_id") == column_id),
        None,
    )
    assert col is not None, f"Column {column_id} not found after add-label"
    label_texts = [lbl.get("label") for lbl in col.get("labels", [])]
    assert (
        "Blocked" in label_texts
    ), f"Expected 'Blocked' in labels after --add-label, got: {label_texts}"


@pytest.mark.integration
def test_rename_label_exits_1_with_clear_api_limitation_message(
    test_board_id: str,
    created_column: Callable[..., str],
) -> None:
    """AC3 (API-limited path): --rename-label exits 1 with a clear teaching error.

    The Monday.com public API does not expose an index-preserving label rename.
    This test asserts the command exits 1 with a message explaining the
    limitation, so the contract is locked and any future change in behaviour
    (e.g. if a rename path becomes available) is detected.
    """
    column_id = created_column("upd-rename", "status", labels="Todo,In Progress,Done")

    result_raw, stderr = run_cli(
        "columns",
        "update",
        "--board-id",
        test_board_id,
        "--column-id",
        column_id,
        "--rename-label",
        "Todo=Pending",
        expect_error=True,
        capture_stderr=True,
    )

    # Command must exit 1 — not silently succeed.
    # (run_cli with expect_error=True returns (stdout_str, stderr_str) on non-zero exit)
    assert isinstance(stderr, str), "Expected string stderr when capture_stderr=True"
    stderr_lower = stderr.lower()
    assert (
        "rename" in stderr_lower or "not supported" in stderr_lower
    ), f"Expected rename-limitation message in stderr: {stderr!r}"


@pytest.mark.integration
def test_delete_unknown_column_id_exits_1(
    test_board_id: str,
) -> None:
    """AC4: deleting a non-existent column id exits 1 with a teaching error.

    Verifies the CLI surfaces the "not found" teaching error (including the
    tip to run columns list) without making a delete API call, and that the
    board's column count is unchanged.
    """
    # Record board state before the attempted delete
    before_data = run_cli("columns", "list", "--board-id", test_board_id)
    assert isinstance(before_data, dict)
    before_count = before_data.get("total_count", 0)

    # Attempt to delete a column id that does not exist
    result, stderr = run_cli(
        "columns",
        "delete",
        "--board-id",
        test_board_id,
        "--column-id",
        "this_column_id_does_not_exist_xyz",
        "--force",
        expect_error=True,
        capture_stderr=True,
    )

    # Teaching error + tip must appear on stderr
    assert "not found" in stderr.lower(), f"Expected 'not found' in stderr: {stderr!r}"
    assert "columns list" in stderr, f"Expected tip in stderr: {stderr!r}"

    # Board must be unchanged (column count is same)
    after_data = run_cli("columns", "list", "--board-id", test_board_id)
    assert isinstance(after_data, dict)
    after_count = after_data.get("total_count", 0)
    assert (
        after_count == before_count
    ), f"Column count changed after failed delete: was {before_count}, now {after_count}"
