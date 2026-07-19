"""FR-0009 Epic B / B3 (#58): items create -g widened to title-or-id.

The deliberate behavior change: ``items create -g`` now binds to ``--group``
(title OR id, auto-detected) instead of the old id-only ``--group-id``. Ids
still work (backward compatible); titles resolve to ids; ``--group-id`` remains
an id-only long option.
"""

from __future__ import annotations

from monday_cli.cli import app

from .conftest import FakeClient

GROUPS = [
    {"id": "topics", "title": "Topics"},
    {"id": "group_abc", "title": "In Progress"},
]


def test_create_g_accepts_title_resolves_to_id(runner, use_client) -> None:
    client = use_client(FakeClient(groups=GROUPS))
    result = runner.invoke(
        app, ["items", "create", "--board-id", "1", "--name", "T", "-g", "In Progress"]
    )
    assert result.exit_code == 0
    # The resolved id (not the title) is sent to create_item.
    _, variables = client.mutations[-1]
    assert variables["groupId"] == "group_abc"


def test_create_g_accepts_id_backward_compatible(runner, use_client) -> None:
    client = use_client(FakeClient(groups=GROUPS))
    result = runner.invoke(
        app, ["items", "create", "--board-id", "1", "--name", "T", "-g", "group_abc"]
    )
    assert result.exit_code == 0
    _, variables = client.mutations[-1]
    assert variables["groupId"] == "group_abc"


def test_create_group_id_still_works_id_only(runner, use_client) -> None:
    client = use_client(FakeClient(groups=GROUPS))
    result = runner.invoke(
        app, ["items", "create", "--board-id", "1", "--name", "T", "--group-id", "topics"]
    )
    assert result.exit_code == 0
    _, variables = client.mutations[-1]
    assert variables["groupId"] == "topics"


def test_create_unknown_group_is_teaching_error(runner, use_client) -> None:
    use_client(FakeClient(groups=GROUPS))
    result = runner.invoke(
        app, ["items", "create", "--board-id", "1", "--name", "T", "-g", "bogus"]
    )
    assert result.exit_code == 1
    # FR-0008: errors go to stderr, stdout stays clean JSON-only.
    assert "Available groups" in result.stderr
    assert "group_abc" in result.stderr
    # Clean teaching error — no spurious "Unexpected error" line.
    assert "Unexpected error" not in result.stderr
    assert result.stdout.strip() == ""


def test_create_group_and_group_id_mutually_exclusive(runner, use_client) -> None:
    use_client(FakeClient(groups=GROUPS))
    result = runner.invoke(
        app,
        ["items", "create", "--board-id", "1", "--name", "T", "-g", "topics", "--group-id", "x"],
    )
    assert result.exit_code == 1
    assert "Cannot use both" in result.stderr
