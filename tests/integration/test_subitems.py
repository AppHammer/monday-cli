"""Subitems CRUD + list-columns + list-statuses integration tests (US-0002-05).

Covers `monday subitems create` / `get` / `list` / `list-columns` /
`list-statuses` / `update` / `delete` end-to-end against the scratch test
board (18422673411), using the run-scoped `created_item` / `created_subitem`
factory fixtures from the shared harness (US-0002-01) so every parent item
and subitem this suite touches is torn down -- even on assertion failure --
and never collides with a parallel run.

Subitems live on an auto-created "Subitems of <board>" sub-board with their
own column schema, distinct from the parent board. That sub-board id is
never hardcoded here: `subitems get --subitem-id <id>` returns `board.id` /
`board.name` for the subitem's OWN board (see `GET_ITEM_BY_ID` in
src/monday_cli/client/queries.py, reused by `subitems get`), and that board
IS the subitems sub-board -- so it is discovered at runtime from a subitem
we already created, then used to exercise `subitems list --board-id`'s
pagination path.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.integration.helpers import poll_until, run_cli


@pytest.mark.integration
def test_create_returns_subitem_id_and_name(created_item: Callable[..., str], run_id: str) -> None:
    parent_id = created_item("create-parent")
    name = f"{run_id}-create-child"

    data = run_cli("subitems", "create", "--parent-item-id", parent_id, "--name", name)

    try:
        assert isinstance(data, dict)
        assert data.get("id")
        assert data.get("name") == name
    finally:
        run_cli("subitems", "delete", "--subitem-id", str(data["id"]), "--force", expect_error=True)


@pytest.mark.integration
def test_get_returns_subitem_shape(
    created_item: Callable[..., str], created_subitem: Callable[..., str], run_id: str
) -> None:
    parent_id = created_item("get-parent")
    subitem_id = created_subitem(parent_id, "get-child")
    expected_name = f"{run_id}-get-child"

    data = run_cli("subitems", "get", "--subitem-id", subitem_id)

    assert isinstance(data, dict)
    assert str(data.get("id")) == subitem_id
    assert data.get("name") == expected_name
    assert "board" in data
    assert data["board"].get("id")
    assert data["board"].get("name")
    assert isinstance(data.get("column_values"), list)


@pytest.mark.integration
def test_list_by_item_id_returns_subitem(
    created_item: Callable[..., str], created_subitem: Callable[..., str], run_id: str
) -> None:
    parent_id = created_item("list-item-parent")
    subitem_id = created_subitem(parent_id, "list-item-child")

    # Bounded poll: the subitems list can briefly lag after creation.
    data = poll_until(
        lambda d: isinstance(d, dict)
        and any(str(s.get("id")) == subitem_id for s in d.get("subitems", [])),
        ("subitems", "list", "--item-id", parent_id),
    )

    assert isinstance(data, dict)
    assert data.get("parent_item_id") == parent_id
    subitems = data.get("subitems", [])
    matches = [s for s in subitems if str(s.get("id")) == subitem_id]
    assert len(matches) == 1
    assert matches[0].get("name") == f"{run_id}-list-item-child"


@pytest.mark.integration
def test_list_table_output_renders_without_error(
    created_item: Callable[..., str], created_subitem: Callable[..., str]
) -> None:
    parent_id = created_item("table-parent")
    created_subitem(parent_id, "table-child")

    output = run_cli("subitems", "list", "--item-id", parent_id, "--table", raw=True)

    assert output.strip() != ""


@pytest.mark.integration
def test_list_by_board_id_exercises_pagination(
    created_item: Callable[..., str], created_subitem: Callable[..., str]
) -> None:
    """Exercises the board-level ``subitems list --board-id`` pagination path.

    FR-0013: Scoped assertions:
    - Pagination CONTRACT (has_more, cursor, board_id keys) is verified
      immediately since these depend only on the board's existing index state,
      not on the newly-created subitem being propagated.
    - The presence of the new subitem in ``--all`` is verified via a
      bounded poll to absorb the subitems board's potentially long eventual-
      consistency window (observed > 12 s in practice).
    """
    parent_id = created_item("board-list-parent")
    subitem_id = created_subitem(parent_id, "board-list-child")

    # Discover the subitems sub-board id at runtime -- never hardcoded. The
    # subitem's own `board` (as returned by `subitems get`, backed by
    # GET_ITEM_BY_ID) IS the "Subitems of <board>" sub-board.
    subitem_data = run_cli("subitems", "get", "--subitem-id", subitem_id)
    subitems_board_id = str(subitem_data["board"]["id"])
    assert "subitems of" in subitem_data["board"]["name"].lower()

    page = run_cli("subitems", "list", "--board-id", subitems_board_id, "--limit", "1")

    assert isinstance(page, dict)
    assert page.get("board_id") == subitems_board_id
    assert "subitems of" in page.get("board_name", "").lower()
    assert isinstance(page.get("subitems"), list)
    assert "has_more" in page
    assert "cursor" in page

    # Only exercise an explicit --cursor hop if the board actually has more
    # than one page behind --limit 1 -- avoids flakiness on a board that
    # happens to have exactly one subitem at test time.
    if page.get("has_more") and page.get("cursor"):
        next_page = run_cli(
            "subitems",
            "list",
            "--board-id",
            subitems_board_id,
            "--limit",
            "1",
            "--cursor",
            page["cursor"],
        )
        assert isinstance(next_page, dict)
        assert isinstance(next_page.get("subitems"), list)

    # Bounded poll: the subitems board's items_page index can lag significantly
    # after a new subitem is created (observed: >12 s). Poll up to 60 s before
    # asserting the subitem appears in the full board listing.
    all_data = poll_until(
        lambda d: isinstance(d, dict)
        and subitem_id in {str(s.get("id")) for s in d.get("subitems", [])},
        ("subitems", "list", "--board-id", subitems_board_id, "--all"),
        attempts=20,
        delay=3.0,
    )

    assert isinstance(all_data, dict)
    assert "pages_fetched" in all_data
    all_ids = {str(s.get("id")) for s in all_data.get("subitems", [])}
    assert subitem_id in all_ids


@pytest.mark.integration
def test_list_columns_returns_subitem_columns(
    created_item: Callable[..., str], created_subitem: Callable[..., str]
) -> None:
    parent_id = created_item("columns-parent")
    subitem_id = created_subitem(parent_id, "columns-child")

    data = run_cli("subitems", "list-columns", "--subitem-id", subitem_id)

    assert isinstance(data, dict)
    assert data.get("subitem_id") == subitem_id
    assert "board_id" in data
    columns = data.get("columns", [])
    assert isinstance(columns, list)
    assert len(columns) > 0, "subitems board must expose at least one column"
    for column in columns:
        assert "column_id" in column
        assert "title" in column
        assert "type" in column


@pytest.mark.integration
def test_list_statuses_returns_status_columns_with_labels(
    created_item: Callable[..., str], created_subitem: Callable[..., str]
) -> None:
    parent_id = created_item("statuses-parent")
    subitem_id = created_subitem(parent_id, "statuses-child")

    data = run_cli("subitems", "list-statuses", "--subitem-id", subitem_id)

    assert isinstance(data, dict)
    assert data.get("subitem_id") == subitem_id
    status_columns = data.get("status_columns", [])
    assert isinstance(status_columns, list)
    assert len(status_columns) > 0, "subitems board must have at least one status column"

    for column in status_columns:
        assert "column_id" in column
        assert "column_title" in column
        assert isinstance(column["statuses"], list)
        for status in column["statuses"]:
            assert "index" in status
            assert "label" in status


@pytest.mark.integration
def test_update_status_round_trips_via_get(
    created_item: Callable[..., str], created_subitem: Callable[..., str]
) -> None:
    parent_id = created_item("update-parent")
    subitem_id = created_subitem(parent_id, "update-child")

    # Discover a real status column/label from list-statuses rather than
    # hardcoding one -- skip cleanly if the subitems board has none.
    statuses_data = run_cli("subitems", "list-statuses", "--subitem-id", subitem_id)
    status_columns = statuses_data.get("status_columns", [])
    if not status_columns:
        pytest.skip("No status columns on the subitems board; skipping update round-trip")

    column = status_columns[0]
    options = column.get("statuses", [])
    if not options:
        pytest.skip(
            f"Status column '{column.get('column_title')}' has no label options; "
            "skipping update round-trip"
        )

    column_title = column["column_title"]
    column_id = column["column_id"]
    label = options[0]["label"]

    update_data = run_cli(
        "subitems", "update", "--subitem-id", subitem_id, "--title", column_title, "--value", label
    )
    assert isinstance(update_data, dict)

    # ``subitems get`` by ID is strongly consistent, but poll briefly to absorb
    # any transient propagation delay before asserting the column value.
    def _has_label(d: object) -> bool:
        if not isinstance(d, dict):
            return False
        matches = [c for c in d.get("column_values", []) if c.get("id") == column_id]
        return len(matches) == 1 and matches[0].get("text") == label

    get_data = poll_until(_has_label, ("subitems", "get", "--subitem-id", subitem_id))
    column_values = get_data.get("column_values", [])
    matches = [c for c in column_values if c.get("id") == column_id]
    assert len(matches) == 1
    assert matches[0].get("text") == label


@pytest.mark.integration
def test_delete_removes_subitem_and_list_confirms_removal(
    created_item: Callable[..., str], run_id: str
) -> None:
    parent_id = created_item("delete-parent")
    name = f"{run_id}-delete-child"
    created = run_cli("subitems", "create", "--parent-item-id", parent_id, "--name", name)
    subitem_id = str(created["id"])

    delete_data = run_cli("subitems", "delete", "--subitem-id", subitem_id, "--force")

    assert isinstance(delete_data, dict)
    assert delete_data.get("subitem_id") == subitem_id
    assert delete_data.get("deleted") is True

    # With the only subitem gone, `subitems list --item-id` exits non-zero
    # with a "no subitems found" message rather than an empty JSON payload.
    list_output = run_cli("subitems", "list", "--item-id", parent_id, expect_error=True)
    assert subitem_id not in list_output

    # Idempotent re-delete must not raise -- confirms teardown safety.
    run_cli("subitems", "delete", "--subitem-id", subitem_id, "--force", expect_error=True)
