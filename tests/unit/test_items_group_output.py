"""FR-0009 Epic D (#56): guarantee group{id,title} in item output + table id.

Regression-locks the ``group { id title }`` selection in the item queries and
verifies ``items list --table`` surfaces the group id (with a null-safe
placeholder for items that have no group). Pure unit tests — no network.
"""

from __future__ import annotations

import json
import re

from monday_cli.cli import app
from monday_cli.client.queries import GET_BOARD_ITEMS, GET_ITEM_BY_ID, GET_NEXT_ITEMS_PAGE

from .conftest import FakeClient

_GROUP_BLOCK = re.compile(r"group\s*\{\s*id\s*title\s*\}")


def test_board_items_query_selects_group_id_and_title() -> None:
    assert _GROUP_BLOCK.search(GET_BOARD_ITEMS), "GET_BOARD_ITEMS must select group { id title }"


def test_next_items_page_query_selects_group_id_and_title() -> None:
    assert _GROUP_BLOCK.search(
        GET_NEXT_ITEMS_PAGE
    ), "GET_NEXT_ITEMS_PAGE must select group { id title }"


def test_item_by_id_query_selects_group_id_and_title() -> None:
    assert _GROUP_BLOCK.search(GET_ITEM_BY_ID), "GET_ITEM_BY_ID must select group { id title }"


def test_list_json_preserves_group_id_and_title(runner, use_client) -> None:
    use_client(
        FakeClient(
            board_items=[
                {
                    "id": "1",
                    "name": "A",
                    "state": "active",
                    "group": {"id": "group_abc", "title": "In Progress"},
                    "column_values": [],
                }
            ]
        )
    )
    result = runner.invoke(app, ["items", "list", "--board-id", "1"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["items"][0]["group"] == {"id": "group_abc", "title": "In Progress"}


def test_list_json_null_group_is_safe(runner, use_client) -> None:
    use_client(
        FakeClient(
            board_items=[
                {
                    "id": "2",
                    "name": "NoGroup",
                    "state": "active",
                    "group": None,
                    "column_values": [],
                }
            ]
        )
    )
    result = runner.invoke(app, ["items", "list", "--board-id", "1"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["items"][0]["group"] is None


def test_get_json_preserves_group_id_and_title(runner, use_client) -> None:
    """Command-level counterpart to `test_list_json_preserves_group_id_and_title`."""
    use_client(
        FakeClient(
            item_by_id={
                "id": "1",
                "name": "A",
                "state": "active",
                "group": {"id": "group_abc", "title": "In Progress"},
                "board": {"id": "1", "name": "Test Board"},
            }
        )
    )
    result = runner.invoke(app, ["items", "get", "--item-id", "1"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["group"] == {"id": "group_abc", "title": "In Progress"}


def test_get_json_null_group_is_safe(runner, use_client) -> None:
    """Command-level counterpart to `test_list_json_null_group_is_safe`."""
    use_client(
        FakeClient(
            item_by_id={
                "id": "2",
                "name": "NoGroup",
                "state": "active",
                "group": None,
                "board": {"id": "1", "name": "Test Board"},
            }
        )
    )
    result = runner.invoke(app, ["items", "get", "--item-id", "2"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["group"] is None


def test_table_renders_group_id_and_placeholder(runner, use_client) -> None:
    use_client(
        FakeClient(
            board_items=[
                {
                    "id": "1",
                    "name": "A",
                    "state": "active",
                    "group": {"id": "group_abc", "title": "In Progress"},
                    "column_values": [],
                },
                {
                    "id": "2",
                    "name": "B",
                    "state": "active",
                    "group": None,
                    "column_values": [],
                },
            ]
        )
    )
    result = runner.invoke(app, ["items", "list", "--board-id", "1", "--table"])
    assert result.exit_code == 0
    # Rich may wrap/truncate; assert the id token is present and the header exists.
    assert "Group ID" in result.stdout
    assert "group_abc" in result.stdout
    # No-group row renders a safe placeholder.
    assert "N/A" in result.stdout
