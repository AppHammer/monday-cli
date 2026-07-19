"""Code-review fixes for `items list` filter + pagination interaction.

Covers three findings on FR-0009's PR #61:

1. [code-review] A group/status filter must scan the WHOLE board internally
   (even without --all), so a non-empty group whose matching items live on
   page 2+ is never mistaken for an empty group. When a filter forces this
   scan, `cursor`/`has_more` must be coherent (null/false), not a misleading
   mid-stream cursor.
2. [code-review] An unknown `--group-id` must be a teaching error (exit 1),
   symmetric with the existing `-g`/`--group` teaching error -- not a silent
   `items: []` exit 0.
3. [QA] The resolved group id must always be echoed under the single stable
   `group_id_filter` JSON key, regardless of whether `-g`/`--group` or
   `--group-id` was used, without removing the existing `group_filter` key.

Round-2 findings on the same PR:

4. [code-review] A supplied `--cursor` combined with an active group/status
   filter must be IGNORED -- the forced full-board scan always starts from
   the beginning, so a non-empty group/status whose matches precede the
   caller's cursor is never mistaken for empty.
5. [code-review] An invalid `--group-id`/`-g`/`--status` must fail fast,
   BEFORE the (expensive) multi-page scan -- not after burning the full
   pagination budget on a request whose result is discarded anyway.
"""

from __future__ import annotations

import json

from monday_cli.cli import app

from .conftest import FakeClient

GROUP_A = {"id": "group_a", "title": "Alpha"}
GROUP_B = {"id": "group_b", "title": "Beta"}
GROUPS = [GROUP_A, GROUP_B]


def _item(item_id: str, group: dict) -> dict:
    return {
        "id": item_id,
        "name": f"item-{item_id}",
        "state": "active",
        "group": group,
        "column_values": [],
    }


def _paginated_client() -> FakeClient:
    """Page 1 has only Beta items; the Alpha item lives on page 2."""
    return FakeClient(
        board_items=[_item("1", GROUP_B), _item("2", GROUP_B)],
        initial_cursor="cursor-to-page-2",
        next_pages=[([_item("3", GROUP_A)], None)],
        groups=GROUPS,
    )


def test_group_id_filter_finds_item_beyond_page_1_without_all(runner, use_client) -> None:
    """A non-empty group filter must never report items: [] just because its
    matches live beyond the first page -- even when --all wasn't passed."""
    use_client(_paginated_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--group-id", "group_a"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [i["id"] for i in data["items"]] == ["3"]


def test_dash_g_filter_finds_item_beyond_page_1_without_all(runner, use_client) -> None:
    """Same guarantee via -g/--group (title, resolved internally)."""
    use_client(_paginated_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--group", "Alpha"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [i["id"] for i in data["items"]] == ["3"]


def test_status_filter_finds_item_beyond_page_1_without_all(runner, use_client) -> None:
    """Same guarantee for --status: forces a full scan too."""
    status_col = {
        "id": "status_col",
        "title": "Status",
        "type": "status",
        "settings_str": json.dumps({"labels": {"0": "Done", "1": "Stuck"}}),
    }

    def _status_item(item_id: str, text: str) -> dict:
        return {
            "id": item_id,
            "name": f"item-{item_id}",
            "state": "active",
            "group": GROUP_A,
            "column_values": [{"id": "status_col", "text": text, "type": "status"}],
        }

    client = FakeClient(
        board_items=[_status_item("1", "Stuck")],
        initial_cursor="cursor-to-page-2",
        next_pages=[([_status_item("2", "Done")], None)],
        columns=[status_col],
        groups=GROUPS,
    )
    use_client(client)
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--status", "Done"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [i["id"] for i in data["items"]] == ["2"]


def test_filtered_scan_reports_coherent_cursor_and_has_more(runner, use_client) -> None:
    """When a filter forces a full scan, cursor/has_more must reflect that
    pagination is exhausted -- not echo the pre-filter, mid-stream cursor."""
    use_client(_paginated_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--group-id", "group_a"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["cursor"] is None
    assert data["has_more"] is False


def test_unfiltered_list_keeps_normal_single_page_pagination(runner, use_client) -> None:
    """Without any filter, a single page is fetched and its real cursor is
    echoed -- the forced-full-scan behavior must not leak into the plain path."""
    use_client(_paginated_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [i["id"] for i in data["items"]] == ["1", "2"]
    assert data["cursor"] == "cursor-to-page-2"
    assert data["has_more"] is True


def test_unknown_group_id_is_teaching_error_exit_1(runner, use_client) -> None:
    use_client(FakeClient(board_items=[_item("1", GROUP_A)], groups=GROUPS))
    result = runner.invoke(
        app, ["items", "list", "--board-id", "1", "--group-id", "definitely-not-a-group"]
    )
    assert result.exit_code == 1
    assert "Available groups" in result.stdout


def test_valid_but_empty_group_id_is_exit_0_empty_items(runner, use_client) -> None:
    """A REAL, valid group with no matching items is still items: [] exit 0 --
    the teaching error must fire only for an unknown id, never a valid-but-empty
    one."""
    use_client(FakeClient(board_items=[_item("1", GROUP_A)], groups=GROUPS))
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--group-id", "group_b"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["items"] == []


def test_group_id_filter_echoes_resolved_id_under_stable_key(runner, use_client) -> None:
    use_client(FakeClient(board_items=[_item("1", GROUP_A)], groups=GROUPS))
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--group-id", "group_a"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["group_id_filter"] == "group_a"


def test_dash_g_filter_also_echoes_resolved_id_under_stable_key(runner, use_client) -> None:
    """-g <title> must ALSO surface the resolved id under `group_id_filter`,
    the same stable key --group-id uses, in addition to the existing raw
    `group_filter` key (backward compatible: nothing removed, only added)."""
    use_client(FakeClient(board_items=[_item("1", GROUP_A)], groups=GROUPS))
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--group", "Alpha"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["group_filter"] == "Alpha"
    assert data["group_id_filter"] == "group_a"


def test_dash_g_by_id_also_echoes_resolved_id_under_stable_key(runner, use_client) -> None:
    use_client(FakeClient(board_items=[_item("1", GROUP_A)], groups=GROUPS))
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--group", "group_a"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["group_id_filter"] == "group_a"


def test_cursor_ignored_when_group_filter_active(runner, use_client) -> None:
    """A caller-supplied --cursor must be ignored whenever a group filter is
    active: the scan always starts from page 1, so the Alpha item on page 2
    is still found even though a (bogus, mid-stream) cursor was passed."""
    client = _paginated_client()
    use_client(client)
    result = runner.invoke(
        app,
        [
            "items",
            "list",
            "--board-id",
            "1",
            "--group-id",
            "group_a",
            "--cursor",
            "caller-supplied-cursor",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [i["id"] for i in data["items"]] == ["3"]
    # The first (board items) query must never carry the caller's cursor.
    first_query, first_variables = client.queries[0]
    assert "items_page" in first_query
    assert "cursor" not in (first_variables or {})


def test_invalid_group_id_fails_fast_without_full_scan(runner, use_client) -> None:
    """An invalid --group-id must error BEFORE the multi-page scan runs --
    the paginated next-page query must never be dispatched."""
    client = _paginated_client()
    use_client(client)
    result = runner.invoke(
        app, ["items", "list", "--board-id", "1", "--group-id", "not-a-real-group"]
    )
    assert result.exit_code == 1
    assert "Available groups" in result.stdout
    assert not any("next_items_page" in q for q, _ in client.queries)


def test_invalid_status_fails_fast_without_full_scan(runner, use_client) -> None:
    """An invalid --status must also error before the multi-page scan runs."""
    status_col = {
        "id": "status_col",
        "title": "Status",
        "type": "status",
        "settings_str": json.dumps({"labels": {"0": "Done", "1": "Stuck"}}),
    }
    client = FakeClient(
        board_items=[_item("1", GROUP_A)],
        initial_cursor="cursor-to-page-2",
        next_pages=[([_item("2", GROUP_A)], None)],
        columns=[status_col],
        groups=GROUPS,
    )
    use_client(client)
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--status", "Nope"])
    assert result.exit_code == 1
    assert "Available statuses" in result.stdout
    assert not any("next_items_page" in q for q, _ in client.queries)
