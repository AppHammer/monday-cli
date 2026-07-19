"""Updates create/read integration tests (US-0002-06).

Covers `monday updates create` on both an item and a subitem (subitems are
items under the hood, so the same `--item-id` targets either), and the
`monday updates get` read-back round trip, against the scratch test board
(18422673411).

There is no standalone update-delete command in this CLI (see
`src/monday_cli/commands/updates.py`); cleanup relies entirely on the
run-scoped `created_item` / `created_subitem` factory fixtures deleting
their parent item/subitem at teardown, which removes any updates posted to
them -- no extra teardown is needed here.

FR-0013: ``test_get_updates_round_trips_posted_body`` uses ``poll_until`` to
tolerate Monday's eventual-consistency lag between posting an update and the
update appearing in the ``updates get`` list read.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.integration.helpers import poll_until, run_cli


@pytest.mark.integration
def test_create_update_on_item_returns_update_id(
    created_item: Callable[..., str], run_id: str
) -> None:
    item_id = created_item("update-on-item")
    body = f"update-{run_id}"

    data = run_cli("updates", "create", "--item-id", item_id, "--body", body)

    assert isinstance(data, dict)
    assert data.get("id")
    assert data.get("body") == body


@pytest.mark.integration
def test_create_update_on_subitem_returns_update_id(
    created_item: Callable[..., str],
    created_subitem: Callable[..., str],
    run_id: str,
) -> None:
    parent_id = created_item("update-on-subitem-parent")
    subitem_id = created_subitem(parent_id)
    body = f"update-{run_id}"

    # Subitems are items under the hood, so the same `--item-id` option
    # targets a subitem id here.
    data = run_cli("updates", "create", "--item-id", subitem_id, "--body", body)

    assert isinstance(data, dict)
    assert data.get("id")
    assert data.get("body") == body


@pytest.mark.integration
def test_get_updates_round_trips_posted_body(created_item: Callable[..., str], run_id: str) -> None:
    item_id = created_item("update-roundtrip")
    body = f"update-{run_id}"

    created = run_cli("updates", "create", "--item-id", item_id, "--body", body)
    assert created.get("id")

    # FR-0013: updates get can briefly lag after a create on the board's
    # activity feed, so poll until the new update body appears.
    data = poll_until(
        lambda d: isinstance(d, dict) and body in [u.get("body") for u in d.get("updates", [])],
        ("updates", "get", "--item-id", item_id),
    )

    assert isinstance(data, dict)
    assert str(data.get("id")) == item_id
    updates = data.get("updates", [])
    bodies = [u.get("body") for u in updates]
    assert body in bodies
