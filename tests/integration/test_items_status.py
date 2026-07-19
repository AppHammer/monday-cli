"""FR-0009 Epic C (#60): `items list --status` live integration tests.

Runs status filtering end-to-end against the scratch test board
(18422673411 — never the PM board). Valid status columns and labels are
discovered at runtime via `statuses list` so the suite doesn't drift if the
board's labels change. Skips cleanly when MONDAY_API_TOKEN is unset; all
artifacts are torn down by the shared factory fixtures even on failure.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from tests.integration.helpers import run_cli


def _status_columns(board_id: str) -> list[dict]:
    return run_cli("statuses", "list", "--board-id", board_id)["status_columns"]


def _list_until_present(args: list[str], item_id: str, attempts: int = 6) -> dict:
    """Run a filtered `items list`, retrying until `item_id` appears.

    A status set via `items update` is strongly consistent on `items get`, but
    the board `items_page` read can briefly lag, so a freshly-filtered list is
    polled a few times before asserting to avoid eventual-consistency flakiness.
    """
    data: dict = {}
    for attempt in range(attempts):
        data = run_cli(*args)
        if item_id in [str(i["id"]) for i in data["items"]]:
            return data
        if attempt < attempts - 1:
            time.sleep(1.5)
    return data


@pytest.mark.integration
def test_status_filter_with_explicit_column(
    created_item: Callable[..., str], test_board_id: str
) -> None:
    columns = _status_columns(test_board_id)
    assert columns, "test board is expected to have at least one status column"
    column = columns[0]
    col_title = column["column_title"]
    label = column["statuses"][0]["label"]

    item_id = created_item("status-item")
    run_cli("items", "update", "--item-id", item_id, "--title", col_title, "--value", label)

    data = _list_until_present(
        [
            "items",
            "list",
            "--board-id",
            test_board_id,
            "--status",
            label,
            "--status-column",
            col_title,
            "--all",
            "--limit",
            "500",
        ],
        item_id,
    )
    assert data["status_filter"] == label
    assert data["status_column"] == col_title
    assert item_id in [str(i["id"]) for i in data["items"]]
    # Every returned item actually has that label in the chosen column.
    for item in data["items"]:
        cell = next((c for c in item["column_values"] if c["id"] == column["column_id"]), None)
        assert cell is not None and cell["text"].lower() == label.lower()


@pytest.mark.integration
def test_multiple_status_columns_require_disambiguation(test_board_id: str) -> None:
    """Post-FR-0008 the teaching error is emitted on stderr (stdout stays clean),
    so assert against the captured stderr stream.
    """
    columns = _status_columns(test_board_id)
    if len(columns) < 2:
        pytest.skip("board has a single status column; disambiguation path not exercisable")

    label = columns[0]["statuses"][0]["label"]
    stdout, stderr = run_cli(
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--status",
        label,
        expect_error=True,
        capture_stderr=True,
    )
    # Teaching error names every status column, never guesses.
    for column in columns:
        assert column["column_title"] in stderr
    assert stdout.strip() == ""


@pytest.mark.integration
def test_bad_label_lists_chosen_column_labels(test_board_id: str) -> None:
    """Post-FR-0008 the teaching error is emitted on stderr (stdout stays clean),
    so assert against the captured stderr stream.
    """
    column = _status_columns(test_board_id)[0]
    stdout, stderr = run_cli(
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--status",
        "zzz-not-a-real-label",
        "--status-column",
        column["column_title"],
        expect_error=True,
        capture_stderr=True,
    )
    assert "Available statuses" in stderr
    # The chosen column's real labels are surfaced.
    assert column["statuses"][0]["label"] in stderr
    assert stdout.strip() == ""


@pytest.mark.integration
def test_status_and_group_compose_as_and(
    created_group: Callable[..., str], created_item: Callable[..., str], test_board_id: str
) -> None:
    column = _status_columns(test_board_id)[0]
    col_title = column["column_title"]
    label = column["statuses"][0]["label"]

    group_in = created_group("and-in")
    group_out = created_group("and-out")
    item_in = created_item("and-item-in", group_id=group_in)
    item_out = created_item("and-item-out", group_id=group_out)
    for item_id in (item_in, item_out):
        run_cli("items", "update", "--item-id", item_id, "--title", col_title, "--value", label)

    title_in = next(
        g["title"]
        for g in run_cli("groups", "list", "--board-id", test_board_id)["groups"]
        if g["id"] == group_in
    )
    data = _list_until_present(
        [
            "items",
            "list",
            "--board-id",
            test_board_id,
            "--status",
            label,
            "--status-column",
            col_title,
            "--group",
            title_in,
            "--all",
            "--limit",
            "500",
        ],
        item_in,
    )
    ids = [str(i["id"]) for i in data["items"]]
    assert item_in in ids  # matches status AND group
    assert item_out not in ids  # same status, different group -> excluded
    assert data["group_filter"] == title_in
    assert data["status_filter"] == label
