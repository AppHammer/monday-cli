"""Items CRUD + pagination + group filtering + list-columns tests (US-0002-04).

Covers `monday items create` / `get` / `update` / `list` / `list-columns` /
`delete` end-to-end against the scratch test board (18422673411), using the
run-scoped `created_group` / `created_item` factory fixtures from the shared
harness (US-0002-01) so every group and item this suite touches is torn
down -- even on assertion failure -- and never collides with a parallel run.

Items are the largest command surface and the primary regression guard for
two previous bug classes: pagination (`--limit`/`--cursor`/`--all`) and
group filtering (`--group-id`). Both are asserted against the exact JSON
keys `commands/items.py` emits: `items`/`cursor`/`has_more`/`items_count` on
the non-`--all` path, and `items`/`total_items` (no `cursor` key) when
`--all` is used. Group/`--all` filtering is client-side and applied AFTER
the full item set is fetched, so those calls pass `--limit 500` to keep the
underlying page count -- and API call budget -- low on a shared board that
may already carry items from other runs.

The status label used in the update round-trip is discovered at runtime
from `items list-columns`' `status_options` rather than hardcoded, so the
suite stays portable if the test board's status column/labels change; if no
status column with a usable label exists, that sub-case skips instead of
failing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tests.integration.helpers import run_cli, run_cli_until


@pytest.mark.integration
def test_create_returns_id_and_name_then_get_returns_full_shape(
    test_board_id: str, run_id: str
) -> None:
    # Created directly (not via the `created_item` factory) so the raw
    # `create_item` payload -- id + name -- can be asserted before `get` is
    # exercised; cleaned up manually in a try/finally.
    name = f"{run_id}-create-get"
    created = run_cli("items", "create", "--board-id", test_board_id, "--name", name)

    try:
        assert isinstance(created, dict)
        assert created.get("id")
        assert created.get("name") == name

        item_id = str(created["id"])
        fetched = run_cli("items", "get", "--item-id", item_id)

        assert isinstance(fetched, dict)
        assert fetched.get("name") == name
        assert "board" in fetched
        assert str(fetched["board"].get("id")) == test_board_id
        assert isinstance(fetched.get("column_values"), list)
    finally:
        run_cli("items", "delete", "--item-id", str(created["id"]), "--force", expect_error=True)


@pytest.mark.integration
def test_list_columns_returns_types_and_options(created_item: Callable[..., str]) -> None:
    item_id = created_item("list-columns")

    data = run_cli("items", "list-columns", "--item-id", item_id)

    assert isinstance(data, dict)
    assert data.get("item_id") == item_id
    assert "board_id" in data
    assert "board_name" in data
    columns = data.get("columns", [])
    assert isinstance(columns, list)
    assert len(columns) > 0, "test board must expose at least one column"
    for column in columns:
        assert "column_id" in column
        assert "title" in column
        assert "type" in column


@pytest.mark.integration
def test_update_status_round_trips_via_get(created_item: Callable[..., str]) -> None:
    item_id = created_item("status-update")

    # Discover a real status column/label from list-columns rather than
    # hardcoding one -- skip cleanly if the test board has none usable.
    columns = run_cli("items", "list-columns", "--item-id", item_id)["columns"]
    status_columns = [
        col for col in columns if col.get("type") == "status" and col.get("status_options")
    ]
    if not status_columns:
        pytest.skip("No status column with options found on the test board")

    status_column = status_columns[0]
    labeled_options = [
        opt for opt in status_column["status_options"] if opt.get("label", "").strip()
    ]
    if not labeled_options:
        pytest.skip(f"Status column '{status_column['title']}' has no non-blank labels")

    column_title = status_column["title"]
    column_id = status_column["column_id"]
    label = labeled_options[0]["label"]

    run_cli("items", "update", "--item-id", item_id, "--title", column_title, "--value", label)

    fetched = run_cli("items", "get", "--item-id", item_id)
    matches = [cv for cv in fetched["column_values"] if cv.get("id") == column_id]
    assert len(matches) == 1
    assert matches[0].get("text") == label


@pytest.mark.integration
def test_list_pagination_contract_and_all_pages(
    created_item: Callable[..., str], test_board_id: str
) -> None:
    # Ensure at least two items exist on the board so a --limit 1 page is
    # guaranteed to report more are available.
    first_id = created_item("page-a")
    second_id = created_item("page-b")

    page_1 = run_cli("items", "list", "--board-id", test_board_id, "--limit", "1")

    assert isinstance(page_1, dict)
    for key in ("items", "cursor", "has_more", "items_count"):
        assert key in page_1
    assert page_1["items_count"] == 1
    assert len(page_1["items"]) == 1
    assert page_1["has_more"] is True
    assert page_1["cursor"]

    page_2 = run_cli(
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--limit",
        "1",
        "--cursor",
        page_1["cursor"],
    )

    assert isinstance(page_2, dict)
    for key in ("items", "cursor", "has_more", "items_count"):
        assert key in page_2
    assert page_2["items_count"] == 1
    assert page_2["items"][0]["id"] != page_1["items"][0]["id"]

    # Bounded poll: both items were just created, and an `--all` read can
    # briefly lag behind on the board's items_page (eventual consistency),
    # so retry until both are visible rather than asserting on one shot.
    all_data = run_cli_until(
        lambda d: isinstance(d, dict)
        and {first_id, second_id} <= {str(item["id"]) for item in d.get("items", [])},
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--all",
        "--limit",
        "500",
    )

    assert isinstance(all_data, dict)
    assert "items" in all_data
    assert "total_items" in all_data
    assert "cursor" not in all_data  # --all's contract has no cursor key
    assert all_data["total_items"] == len(all_data["items"])
    all_ids = {str(item["id"]) for item in all_data["items"]}
    assert first_id in all_ids
    assert second_id in all_ids


@pytest.mark.integration
def test_group_filtering_returns_only_matching_group(
    created_group: Callable[..., str], created_item: Callable[..., str], test_board_id: str
) -> None:
    group_a = created_group("group-a")
    group_b = created_group("group-b")

    item_a = created_item("in-group-a", group_id=group_a)
    created_item("in-group-b", group_id=group_b)

    # Bounded poll: item_a was just created into group_a, and a group-filtered
    # `--all` read can briefly lag behind on eventual consistency, so retry
    # until it's visible rather than asserting on one shot.
    data = run_cli_until(
        lambda d: isinstance(d, dict) and any(str(i["id"]) == item_a for i in d.get("items", [])),
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--group-id",
        group_a,
        "--all",
        "--limit",
        "500",
    )

    assert isinstance(data, dict)
    assert data.get("group_id_filter") == group_a
    assert data.get("total_items") == 1
    items = data["items"]
    assert str(items[0]["id"]) == item_a
    assert items[0]["group"]["id"] == group_a


@pytest.mark.integration
def test_g_by_id_equals_group_id_and_title_path(
    created_group: Callable[..., str], created_item: Callable[..., str], test_board_id: str
) -> None:
    """FR-0009 B1: `-g <id>` == `--group-id <id>`, and `-g <title>` matches too."""
    group_a = created_group("g-parity-a")
    group_b = created_group("g-parity-b")
    item_a = created_item("parity-a", group_id=group_a)
    created_item("parity-b", group_id=group_b)

    common = ["items", "list", "--board-id", test_board_id, "--all", "--limit", "500"]

    # Bounded poll: item_a was just created into group_a, and a group-filtered
    # `--all` read can briefly lag behind on eventual consistency, so retry
    # until it's visible rather than asserting on one shot.
    def _has_item_a(d: Any) -> bool:
        return isinstance(d, dict) and any(str(i["id"]) == item_a for i in d.get("items", []))

    by_group_id = run_cli_until(_has_item_a, *common, "--group-id", group_a)
    by_g_id = run_cli_until(_has_item_a, *common, "-g", group_a)

    ids_group_id = sorted(str(i["id"]) for i in by_group_id["items"])
    ids_g_id = sorted(str(i["id"]) for i in by_g_id["items"])
    assert ids_group_id == ids_g_id == [item_a]

    # Title path resolves to the same group.
    title_a = run_cli("items", "get", "--item-id", item_a)["group"]["title"]
    by_g_title = run_cli_until(_has_item_a, *common, "-g", title_a)
    assert sorted(str(i["id"]) for i in by_g_title["items"]) == [item_a]


@pytest.mark.integration
def test_unknown_group_is_teaching_error(test_board_id: str) -> None:
    """FR-0009 B2: an unknown `-g` value exits non-zero and lists groups.

    Post-FR-0008 the teaching error is emitted on stderr (stdout stays clean),
    so assert against the captured stderr stream.
    """
    stdout, stderr = run_cli(
        "items",
        "list",
        "--board-id",
        test_board_id,
        "-g",
        "definitely-not-a-real-group-xyz",
        expect_error=True,
        capture_stderr=True,
    )
    assert "Available groups" in stderr
    assert stdout.strip() == ""  # FR-0008: stdout stays clean on error


@pytest.mark.integration
def test_list_table_output_renders_group_id(
    created_group: Callable[..., str], created_item: Callable[..., str], test_board_id: str
) -> None:
    """FR-0009 D2: `--table` renders the group id, and JSON carries group{id,title}."""
    group = created_group("table-groupid")
    item_id = created_item("table-item", group_id=group)

    # Bounded poll: a read right after create can briefly lag on eventual
    # consistency (observed flake), so retry rather than assert on one shot.
    output = run_cli_until(
        lambda out: group in out,
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--table",
        raw=True,
    )
    assert output.strip() != ""
    assert group in output  # the group id token appears in the table

    # D1: every listed item carries group{id,title}; the created one matches.
    data = run_cli_until(
        lambda d: any(str(i["id"]) == item_id for i in d["items"]),
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--all",
        "--limit",
        "500",
    )
    for item in data["items"]:
        if item.get("group") is not None:
            assert "id" in item["group"] and "title" in item["group"]
    match = [i for i in data["items"] if str(i["id"]) == item_id]
    assert match and match[0]["group"]["id"] == group


@pytest.mark.integration
def test_delete_removes_item_and_list_confirms_removal(
    created_group: Callable[..., str], test_board_id: str, run_id: str
) -> None:
    group_id = created_group("delete-check")
    name = f"{run_id}-delete-item"
    created = run_cli(
        "items", "create", "--board-id", test_board_id, "--name", name, "--group-id", group_id
    )
    item_id = str(created["id"])

    delete_data = run_cli("items", "delete", "--item-id", item_id, "--force")

    assert isinstance(delete_data, dict)
    assert delete_data.get("item_id") == item_id
    assert delete_data.get("deleted") is True

    # With the group now empty, `items list --group-id` exits 0 and returns a
    # JSON payload with an empty `items` list (a valid-but-empty group is
    # distinguishable from an unknown group after FR-0009 Epic B). This is a
    # clean, silent empty result -- no human-readable "not found" message is
    # printed for a valid-but-empty group (only an unknown one is an error).
    #
    # Bounded poll: a read right after delete can briefly lag on eventual
    # consistency -- the deleted item can still appear on the board's
    # items_page for a moment -- so retry rather than assert on one shot.
    list_data = run_cli_until(
        lambda d: isinstance(d, dict) and d.get("items") == [],
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--group-id",
        group_id,
    )
    assert isinstance(list_data, dict)
    assert list_data.get("items") == []
    assert list_data.get("items_count") == 0
    assert list_data.get("group_id_filter") == group_id

    # Idempotent re-delete must not raise -- confirms teardown safety.
    run_cli("items", "delete", "--item-id", item_id, "--force", expect_error=True)
