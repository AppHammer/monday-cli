"""FR-0009 Epic A (#59): monday items move.

Covers move-by-id (A1), move-by-title (A2), teaching errors (A3: unknown item,
unresolvable group, API rejection), and the idempotent no-op (A4). Subitems and
mutually-exclusive group flags are rejected with teaching errors.
"""

from __future__ import annotations

import json

from monday_cli.cli import app
from monday_cli.utils.error_handler import MondayAPIError

from .conftest import FakeClient


def _json(stdout: str) -> dict:
    """Extract the JSON payload printed after the '✓' success line."""
    lines = stdout.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == "{":
            return json.loads("\n".join(lines[idx:]))
    return json.loads(stdout)


GROUPS = [
    {"id": "group_a", "title": "Group A"},
    {"id": "group_b", "title": "Group B"},
]


def _item(group_id: str = "group_a", board_name: str = "Test Board") -> dict:
    return {
        "id": "100",
        "name": "Movable",
        "board": {"id": "1", "name": board_name},
        "group": {"id": group_id, "title": "Group A" if group_id == "group_a" else "Group B"},
        "column_values": [],
    }


def _moved(group_id: str = "group_b") -> dict:
    return {
        "id": "100",
        "name": "Movable",
        "group": {"id": group_id, "title": "Group B"},
        "board": {"id": "1", "name": "Test Board"},
    }


def test_move_by_id(runner, use_client) -> None:
    client = use_client(
        FakeClient(item_by_id=_item(), groups=GROUPS, move_result=_moved("group_b"))
    )
    result = runner.invoke(app, ["items", "move", "--item-id", "100", "--group-id", "group_b"])
    assert result.exit_code == 0
    data = _json(result.stdout)
    assert data["group"]["id"] == "group_b"
    assert data["moved"] is True
    _, variables = client.mutations[-1]
    assert variables == {"itemId": "100", "groupId": "group_b"}


def test_move_by_title_resolves_id(runner, use_client) -> None:
    client = use_client(
        FakeClient(item_by_id=_item(), groups=GROUPS, move_result=_moved("group_b"))
    )
    result = runner.invoke(app, ["items", "move", "-i", "100", "-g", "Group B"])
    assert result.exit_code == 0
    _, variables = client.mutations[-1]
    assert variables["groupId"] == "group_b"


def test_move_unknown_item_exit_1(runner, use_client) -> None:
    use_client(FakeClient(item_by_id=None, groups=GROUPS))
    result = runner.invoke(app, ["items", "move", "-i", "999", "--group-id", "group_b"])
    assert result.exit_code == 1
    # FR-0008: errors go to stderr, stdout stays clean JSON-only.
    assert "not found" in result.stderr
    assert "Unexpected error" not in result.stderr


def test_move_unresolvable_group_exit_1_lists_groups(runner, use_client) -> None:
    use_client(FakeClient(item_by_id=_item(), groups=GROUPS))
    result = runner.invoke(app, ["items", "move", "-i", "100", "-g", "bogus"])
    assert result.exit_code == 1
    assert "Available groups" in result.stderr
    assert "group_a" in result.stderr and "group_b" in result.stderr


def test_move_api_rejection_is_taught(runner, use_client) -> None:
    use_client(
        FakeClient(
            item_by_id=_item(),
            groups=GROUPS,
            move_result=MondayAPIError("group not on board"),
        )
    )
    result = runner.invoke(app, ["items", "move", "-i", "100", "--group-id", "group_b"])
    assert result.exit_code == 1
    assert "Available groups" in result.stderr


def test_move_noop_when_already_in_target(runner, use_client) -> None:
    client = use_client(FakeClient(item_by_id=_item("group_a"), groups=GROUPS))
    result = runner.invoke(app, ["items", "move", "-i", "100", "--group-id", "group_a"])
    assert result.exit_code == 0
    data = _json(result.stdout)
    assert data["group"]["id"] == "group_a"
    assert data["moved"] is False
    # No mutation issued for an idempotent no-op.
    assert client.mutations == []


def test_move_both_group_flags_rejected(runner, use_client) -> None:
    use_client(FakeClient(item_by_id=_item(), groups=GROUPS))
    result = runner.invoke(
        app, ["items", "move", "-i", "100", "-g", "Group B", "--group-id", "group_b"]
    )
    assert result.exit_code == 1
    assert "Cannot use both" in result.stderr


def test_move_subitem_rejected(runner, use_client) -> None:
    use_client(FakeClient(item_by_id=_item(board_name="Subitems of Test Board"), groups=GROUPS))
    result = runner.invoke(app, ["items", "move", "-i", "100", "--group-id", "group_b"])
    assert result.exit_code == 1
    assert "subitem" in result.stderr.lower()


def test_move_requires_a_group_flag(runner, use_client) -> None:
    use_client(FakeClient(item_by_id=_item(), groups=GROUPS))
    result = runner.invoke(app, ["items", "move", "-i", "100"])
    assert result.exit_code == 1
    assert "destination group is required" in result.stderr.lower()
