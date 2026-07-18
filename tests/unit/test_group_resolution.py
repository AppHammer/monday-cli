"""FR-0009 Epic B / B1-B2 (#57): -g accepts title OR id + distinguishable errors.

Covers the shared ``resolve_group_ref`` precedence table and the ``items list``
behaviour: ``-g <id>`` returns exactly what ``--group-id <id>`` returns (the
core bug fix), ``-g <title>`` still works, an unknown group is a teaching error
(exit 1) and a valid-but-empty group returns ``items: []`` (exit 0) — the two
outcomes are programmatically distinguishable.
"""

from __future__ import annotations

import json

from monday_cli.cli import app
from monday_cli.utils.resolve import resolve_group_ref

from .conftest import FakeClient

GROUPS = [
    {"id": "topics", "title": "Topics"},
    {"id": "group_abc", "title": "In Progress"},
]

ITEMS = [
    {
        "id": "1",
        "name": "A",
        "state": "active",
        "group": {"id": "topics", "title": "Topics"},
        "column_values": [],
    },
    {
        "id": "2",
        "name": "B",
        "state": "active",
        "group": {"id": "group_abc", "title": "In Progress"},
        "column_values": [],
    },
]


def _client() -> FakeClient:
    return FakeClient(board_items=[dict(i) for i in ITEMS], groups=GROUPS)


# --- resolver precedence table (pure) ---------------------------------------


def test_resolver_prefixed_value_is_id_path() -> None:
    resolved, _ = resolve_group_ref(_client(), "1", "group_abc")
    assert resolved is not None and resolved["id"] == "group_abc"


def test_resolver_bare_id_equal_to_real_group_id_is_id_path() -> None:
    # `topics` has no group_ prefix but is a real id -> rule 1b.
    resolved, _ = resolve_group_ref(_client(), "1", "topics")
    assert resolved is not None and resolved["id"] == "topics"


def test_resolver_title_case_insensitive() -> None:
    resolved, _ = resolve_group_ref(_client(), "1", "in progress")
    assert resolved is not None and resolved["id"] == "group_abc"


def test_resolver_unknown_returns_none_with_group_list() -> None:
    resolved, groups = resolve_group_ref(_client(), "1", "does-not-exist")
    assert resolved is None
    assert {g["id"] for g in groups} == {"topics", "group_abc"}


def test_resolver_prefixed_but_unknown_is_none() -> None:
    resolved, _ = resolve_group_ref(_client(), "1", "group_missing")
    assert resolved is None


# --- items list -g behaviour ------------------------------------------------


def test_g_by_id_equals_group_id_option(runner, use_client) -> None:
    """B1 core: -g <id> yields the SAME item set as --group-id <same id>."""
    use_client(_client())
    by_g = runner.invoke(app, ["items", "list", "--board-id", "1", "-g", "group_abc"])
    use_client(_client())
    by_group_id = runner.invoke(
        app, ["items", "list", "--board-id", "1", "--group-id", "group_abc"]
    )

    assert by_g.exit_code == 0 and by_group_id.exit_code == 0
    g_ids = [i["id"] for i in json.loads(by_g.stdout)["items"]]
    gid_ids = [i["id"] for i in json.loads(by_group_id.stdout)["items"]]
    assert g_ids == gid_ids == ["2"]


def test_g_by_title_filters(runner, use_client) -> None:
    use_client(_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "-g", "In Progress"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [i["id"] for i in data["items"]] == ["2"]
    assert data["group_filter"] == "In Progress"


def test_unknown_group_is_teaching_error_exit_1(runner, use_client) -> None:
    use_client(_client())
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "-g", "bogus"])
    assert result.exit_code == 1
    # Teaching error lists available groups as id + title.
    assert "Topics" in result.stdout and "topics" in result.stdout
    assert "In Progress" in result.stdout and "group_abc" in result.stdout


def test_valid_but_empty_group_returns_empty_list_exit_0(runner, use_client) -> None:
    # A real group with no items after filtering: distinguishable from unknown.
    empty = FakeClient(board_items=[dict(ITEMS[0])], groups=GROUPS)  # only a `topics` item
    use_client(empty)
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "-g", "In Progress"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["items"] == []
    assert data["items_count"] == 0
    assert data["group_filter"] == "In Progress"


def test_empty_and_unknown_are_distinguishable(runner, use_client) -> None:
    use_client(FakeClient(board_items=[dict(ITEMS[0])], groups=GROUPS))
    empty = runner.invoke(app, ["items", "list", "--board-id", "1", "-g", "In Progress"])
    use_client(FakeClient(board_items=[dict(ITEMS[0])], groups=GROUPS))
    unknown = runner.invoke(app, ["items", "list", "--board-id", "1", "-g", "nope"])
    assert empty.exit_code == 0
    assert unknown.exit_code == 1
    assert empty.exit_code != unknown.exit_code


def test_group_and_group_id_mutually_exclusive(runner, use_client) -> None:
    use_client(_client())
    result = runner.invoke(
        app, ["items", "list", "--board-id", "1", "-g", "topics", "--group-id", "topics"]
    )
    assert result.exit_code == 1
    assert "Cannot use both" in result.stdout
