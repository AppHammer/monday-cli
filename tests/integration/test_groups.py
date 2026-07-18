"""Groups CRUD integration tests (US-0002-03).

Covers `monday groups create` / `list` / `delete` end-to-end against the
scratch test board (18422673411), using the run-scoped `created_group`
factory fixture from the shared harness so most artifacts this suite
touches are torn down automatically -- even on assertion failure -- and
never collide with a parallel run.

`groups delete` is keyed by `--title`, not id (see the shared harness'
`created_group` fixture), so the two tests that exercise `create`'s full
response shape and `delete`'s residue check create/delete their own group
directly rather than through the factory, wrapping in try/finally for
failure-safe cleanup. Both use a title unique to this test run.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.integration.helpers import run_cli


@pytest.mark.integration
def test_create_returns_group_id_and_echoes_title_and_color(
    test_board_id: str, run_id: str
) -> None:
    title = f"{run_id}-create"

    try:
        data = run_cli(
            "groups",
            "create",
            "--title",
            title,
            "--board-id",
            test_board_id,
            "--color",
            "#ff642e",
        )

        assert isinstance(data, dict)
        assert data.get("group_id")
        assert data.get("title") == title
        assert data.get("color") == "#ff642e"
        assert data.get("board_id") == test_board_id
    finally:
        run_cli(
            "groups",
            "delete",
            "--title",
            title,
            "--board-id",
            test_board_id,
            "--confirm",
            expect_error=True,
        )


@pytest.mark.integration
def test_created_group_appears_in_list(
    created_group: Callable[..., str], test_board_id: str, run_id: str
) -> None:
    group_id = created_group("list-check", color="#037f4c")
    expected_title = f"{run_id}-list-check"

    data = run_cli("groups", "list", "--board-id", test_board_id)

    assert isinstance(data, dict)
    assert data.get("board_id") == test_board_id
    groups = data.get("groups", [])
    matches = [g for g in groups if g.get("title") == expected_title]
    assert len(matches) == 1
    assert str(matches[0].get("id")) == group_id
    assert matches[0].get("color") == "#037f4c"


@pytest.mark.integration
def test_list_table_output_renders_without_error(
    created_group: Callable[..., str], test_board_id: str
) -> None:
    created_group("table-check")

    output = run_cli("groups", "list", "--board-id", test_board_id, "--table", raw=True)

    assert output.strip() != ""


@pytest.mark.integration
def test_delete_removes_group_and_list_confirms_residue(test_board_id: str, run_id: str) -> None:
    title = f"{run_id}-delete-check"

    created = run_cli("groups", "create", "--title", title, "--board-id", test_board_id)
    assert created.get("group_id")

    try:
        delete_data = run_cli(
            "groups",
            "delete",
            "--title",
            title,
            "--board-id",
            test_board_id,
            "--confirm",
        )

        assert isinstance(delete_data, dict)
        assert delete_data.get("group_id")
        assert delete_data.get("title") == title
        # Note: Monday's `delete_group` mutation reports `deleted: false` on
        # this account/board even when the group is genuinely removed, so the
        # residue check below (not this flag) is the authoritative signal.

        list_data = run_cli("groups", "list", "--board-id", test_board_id)
        remaining_titles = {g.get("title") for g in list_data.get("groups", [])}
        assert title not in remaining_titles
    finally:
        # Idempotent cleanup: harmless no-op if the delete above already
        # succeeded, and a safety net if an assertion raised before it did.
        run_cli(
            "groups",
            "delete",
            "--title",
            title,
            "--board-id",
            test_board_id,
            "--confirm",
            expect_error=True,
        )
