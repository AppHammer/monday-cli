"""FR-0009 Epic A (#59): `monday items move` live integration tests.

Runs the move command end-to-end against the scratch test board
(18422673411 — never the PM board; the shared harness hard-fails on it).
Every group/item is created via the run-scoped factory fixtures and torn down
even on assertion failure. Skips cleanly when MONDAY_API_TOKEN is unset.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from tests.integration.helpers import run_cli


def _run_cli_until(
    predicate: Any, *args: str, attempts: int = 6, delay: float = 1.5, **kwargs: Any
) -> Any:
    """Retry a `run_cli` call until `predicate(result)` is true, or give up.

    A group move can briefly lag behind on an `items get` read (eventual
    consistency), so a read right after a move needs a bounded poll rather
    than a single shot -- mirrors `_run_cli_until` in test_items.py.
    """
    result: Any = None
    for attempt in range(attempts):
        result = run_cli(*args, **kwargs)
        if predicate(result):
            return result
        if attempt < attempts - 1:
            time.sleep(delay)
    return result


@pytest.mark.integration
def test_move_between_groups_by_id_then_back_by_title(
    created_group: Callable[..., str], created_item: Callable[..., str], test_board_id: str
) -> None:
    group_a = created_group("move-a")
    group_b = created_group("move-b")
    item_id = created_item("mover", group_id=group_a)

    # Move A -> B by id.
    moved = run_cli("items", "move", "--item-id", item_id, "--group-id", group_b)
    assert moved["group"]["id"] == group_b
    assert moved["moved"] is True

    # Confirm via items get. Bounded poll: the moved group can briefly lag
    # behind on a read right after the move (eventual consistency).
    confirmed = _run_cli_until(
        lambda d: isinstance(d, dict) and d.get("group", {}).get("id") == group_b,
        "items",
        "get",
        "--item-id",
        item_id,
    )
    assert confirmed["group"]["id"] == group_b

    # Move back to A by title.
    title_a = next(
        g["title"]
        for g in run_cli("groups", "list", "--board-id", test_board_id)["groups"]
        if g["id"] == group_a
    )
    back = run_cli("items", "move", "--item-id", item_id, "--group", title_a)
    assert back["group"]["id"] == group_a


@pytest.mark.integration
def test_move_noop_when_already_in_target(
    created_group: Callable[..., str], created_item: Callable[..., str]
) -> None:
    group_a = created_group("noop-a")
    item_id = created_item("noop-item", group_id=group_a)

    result = run_cli("items", "move", "--item-id", item_id, "--group-id", group_a)
    assert result["group"]["id"] == group_a
    assert result["moved"] is False


@pytest.mark.integration
def test_move_unknown_group_is_teaching_error(
    created_item: Callable[..., str],
) -> None:
    """Post-FR-0008 the teaching error is emitted on stderr (stdout stays clean),
    so assert against the captured stderr stream.
    """
    item_id = created_item("bad-move")
    stdout, stderr = run_cli(
        "items",
        "move",
        "--item-id",
        item_id,
        "-g",
        "no-such-group-xyz",
        expect_error=True,
        capture_stderr=True,
    )
    assert "Available groups" in stderr
    assert stdout.strip() == ""
