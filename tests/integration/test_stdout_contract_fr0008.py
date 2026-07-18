"""FR-0008 contract regression tests: clean stdout across all commands.

Asserts the guaranteed output contract:
  - In default (JSON) mode, stdout is EMPTY or a single valid JSON document.
  - ALL human/diagnostic output (progress, tips, warnings, errors) is on stderr.
  - Exit codes are correct (non-zero on failure, 0 on success including empty results).

Tests are organized by acceptance criteria from the FR-0008 FRD:
  - AC-2: multi-page ``items list --all`` emits clean JSON; progress on stderr.
  - AC-3: CLI-wide sweep — every standard verb passes the contract.
  - AC-4: failure paths — exit non-zero, no prose on stdout.
  - AC-5: empty/edge results return valid JSON with correct exit code.

All tests use the TEST board 18422673411.  Tests skip cleanly when
``MONDAY_API_TOKEN`` is not set and tear down every artifact even on failure.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

import pytest

from tests.integration.helpers import run_cli, run_cli_streams


def _skip_if_no_token() -> None:
    if not os.environ.get("MONDAY_API_TOKEN"):
        pytest.skip("MONDAY_API_TOKEN not set")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_clean_stdout(stdout: str, context: str = "") -> None:
    """Assert stdout is either empty or a single valid JSON document."""
    stripped = stdout.strip()
    if stripped:
        try:
            json.loads(stripped)
        except json.JSONDecodeError as exc:
            prefix = f"[{context}] " if context else ""
            pytest.fail(
                f"{prefix}stdout is not clean JSON (FR-0008 violation).\n"
                f"Parse error: {exc}\n"
                f"stdout was:\n{stdout!r}"
            )


# ---------------------------------------------------------------------------
# AC-2: items list --all emits clean JSON; progress goes to stderr
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_items_list_all_stdout_is_clean_json(
    created_item: Callable[..., str], test_board_id: str
) -> None:
    """AC-2: items list --all -- stdout is parseable JSON, progress on stderr."""
    _skip_if_no_token()
    # Ensure at least one item exists
    created_item("ac2-item")

    stdout, stderr, exit_code = run_cli_streams(
        "items", "list", "--board-id", test_board_id, "--all", "--limit", "500"
    )

    assert exit_code == 0, f"Expected exit 0; got {exit_code}\nstdout: {stdout}\nstderr: {stderr}"
    _assert_clean_stdout(stdout, "items list --all")

    data = json.loads(stdout.strip())
    assert "items" in data
    assert "total_items" in data
    # progress lines must be on stderr (not stdout)
    # They may or may not appear depending on whether pagination triggers,
    # but stdout must be clean JSON regardless.
    assert "Fetching page" not in stdout
    assert "Total items so far" not in stdout


# ---------------------------------------------------------------------------
# AC-3: CLI-wide sweep — standard verbs pass the contract
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_boards_list_stdout_is_clean_json() -> None:
    """AC-3: boards list -- stdout is clean JSON."""
    _skip_if_no_token()
    stdout, stderr, exit_code = run_cli_streams("boards", "list")
    assert exit_code == 0
    _assert_clean_stdout(stdout, "boards list")
    data = json.loads(stdout.strip())
    assert "boards" in data


@pytest.mark.integration
def test_workspaces_list_stdout_is_clean_json() -> None:
    """AC-3: workspaces list -- stdout is clean JSON."""
    _skip_if_no_token()
    stdout, stderr, exit_code = run_cli_streams("workspaces", "list")
    assert exit_code == 0
    _assert_clean_stdout(stdout, "workspaces list")
    data = json.loads(stdout.strip())
    assert "workspaces" in data


@pytest.mark.integration
def test_groups_list_stdout_is_clean_json(test_board_id: str) -> None:
    """AC-3: groups list -- stdout is clean JSON."""
    _skip_if_no_token()
    stdout, stderr, exit_code = run_cli_streams("groups", "list", "--board-id", test_board_id)
    assert exit_code == 0
    _assert_clean_stdout(stdout, "groups list")
    data = json.loads(stdout.strip())
    assert "groups" in data


@pytest.mark.integration
def test_statuses_list_stdout_is_clean_json(test_board_id: str) -> None:
    """AC-3: statuses list -- stdout is clean JSON."""
    _skip_if_no_token()
    stdout, stderr, exit_code = run_cli_streams("statuses", "list", "--board-id", test_board_id)
    # May exit 0 with data, or exit 0 with empty JSON — both are valid
    _assert_clean_stdout(stdout, "statuses list")


@pytest.mark.integration
def test_items_get_stdout_is_clean_json(created_item: Callable[..., str]) -> None:
    """AC-3: items get -- stdout is clean JSON."""
    _skip_if_no_token()
    item_id = created_item("ac3-get")
    stdout, stderr, exit_code = run_cli_streams("items", "get", "--item-id", item_id)
    assert exit_code == 0
    _assert_clean_stdout(stdout, "items get")
    data = json.loads(stdout.strip())
    assert data.get("id") == item_id


@pytest.mark.integration
def test_items_create_stdout_is_clean_json(
    test_board_id: str, run_id: str, created_item: Callable[..., str]
) -> None:
    """AC-3: items create -- stdout is clean JSON (no success message on stdout)."""
    _skip_if_no_token()
    name = f"{run_id}-ac3-create"
    stdout, stderr, exit_code = run_cli_streams(
        "items", "create", "--board-id", test_board_id, "--name", name
    )
    assert exit_code == 0, f"stdout: {stdout}\nstderr: {stderr}"
    _assert_clean_stdout(stdout, "items create")
    data = json.loads(stdout.strip())
    item_id = str(data.get("id", ""))
    assert item_id
    # Success message must be on stderr, not stdout
    assert "✓" not in stdout
    assert "✓" in stderr or "created" in stderr.lower()
    # Cleanup
    run_cli("items", "delete", "--item-id", item_id, "--force", expect_error=True)


@pytest.mark.integration
def test_items_delete_stdout_is_clean_json(test_board_id: str, run_id: str) -> None:
    """AC-3: items delete -- stdout is clean JSON (no success/confirm on stdout)."""
    _skip_if_no_token()
    name = f"{run_id}-ac3-delete"
    created = run_cli("items", "create", "--board-id", test_board_id, "--name", name)
    item_id = str(created["id"])

    stdout, stderr, exit_code = run_cli_streams("items", "delete", "--item-id", item_id, "--force")
    assert exit_code == 0, f"stdout: {stdout}\nstderr: {stderr}"
    _assert_clean_stdout(stdout, "items delete")
    data = json.loads(stdout.strip())
    assert data.get("deleted") is True
    # Success message must be on stderr
    assert "deleted" in stderr.lower() or "✓" in stderr


@pytest.mark.integration
def test_subitems_create_stdout_is_clean_json(created_item: Callable[..., str]) -> None:
    """AC-3: subitems create -- stdout is clean JSON."""
    _skip_if_no_token()
    parent_id = created_item("ac3-sub-parent")
    stdout, stderr, exit_code = run_cli_streams(
        "subitems", "create", "--parent-item-id", parent_id, "--name", "ac3-subtask"
    )
    assert exit_code == 0, f"stdout: {stdout}\nstderr: {stderr}"
    _assert_clean_stdout(stdout, "subitems create")
    data = json.loads(stdout.strip())
    assert data.get("id")
    assert "✓" not in stdout


@pytest.mark.integration
def test_updates_create_stdout_is_clean_json(created_item: Callable[..., str]) -> None:
    """AC-3: updates create -- stdout is clean JSON."""
    _skip_if_no_token()
    item_id = created_item("ac3-update")
    stdout, stderr, exit_code = run_cli_streams(
        "updates", "create", "--item-id", item_id, "--body", "FR-0008 test update"
    )
    assert exit_code == 0, f"stdout: {stdout}\nstderr: {stderr}"
    _assert_clean_stdout(stdout, "updates create")
    data = json.loads(stdout.strip())
    assert data.get("id")
    assert "✓" not in stdout


# ---------------------------------------------------------------------------
# AC-4: failure paths — exit non-zero, no prose on stdout
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_bad_item_id_exits_nonzero_with_no_prose_on_stdout() -> None:
    """AC-4: unknown item id -- exit non-zero, stdout empty (not prose)."""
    _skip_if_no_token()
    stdout, stderr, exit_code = run_cli_streams("items", "get", "--item-id", "999999999999")
    assert exit_code != 0, f"Expected non-zero exit; got {exit_code}"
    # stdout must be empty or valid JSON (not a prose error message)
    _assert_clean_stdout(stdout, "items get bad id")
    # The error message must be on stderr
    assert stdout.strip() == "" or json.loads(stdout.strip()) is not None
    assert stderr.strip() != ""


@pytest.mark.integration
def test_bad_board_id_exits_nonzero_with_no_prose_on_stdout() -> None:
    """AC-4: unknown board id -- exit non-zero, stdout empty (not prose)."""
    _skip_if_no_token()
    stdout, stderr, exit_code = run_cli_streams("items", "list", "--board-id", "999999999999")
    assert exit_code != 0
    _assert_clean_stdout(stdout, "items list bad board")
    assert stdout.strip() == ""
    assert stderr.strip() != ""


@pytest.mark.integration
def test_invalid_column_title_exits_nonzero_with_no_prose_on_stdout(
    created_item: Callable[..., str],
) -> None:
    """AC-4: invalid column title -- exit non-zero, stdout empty, error on stderr."""
    _skip_if_no_token()
    item_id = created_item("ac4-bad-col")
    stdout, stderr, exit_code = run_cli_streams(
        "items",
        "update",
        "--item-id",
        item_id,
        "--title",
        "NonExistentColumn_XYZ",
        "--value",
        "whatever",
    )
    assert exit_code != 0
    _assert_clean_stdout(stdout, "items update bad column")
    assert stdout.strip() == ""
    # "Available columns:" teaching output must be on stderr
    assert "Available columns" in stderr or "not found" in stderr.lower()


# ---------------------------------------------------------------------------
# AC-5: empty/edge results return valid JSON + correct exit code
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_empty_group_returns_valid_json_not_prose(
    created_group: Callable[..., str], test_board_id: str
) -> None:
    """AC-5: group with no items returns valid JSON (empty items array), exit 0."""
    _skip_if_no_token()
    group_id = created_group("ac5-empty")
    # Do NOT create any items in this group

    stdout, stderr, exit_code = run_cli_streams(
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--group-id",
        group_id,
    )

    assert exit_code == 0, f"Expected exit 0 for empty result; got {exit_code}\nstderr: {stderr}"
    _assert_clean_stdout(stdout, "items list empty group")
    data = json.loads(stdout.strip())
    assert data.get("items") == []
    assert data.get("items_count") == 0
    assert data.get("group_id_filter") == group_id
    # The human tip must be on stderr, not stdout
    assert "No items found" not in stdout
    assert "No items found" in stderr or "Tip" in stderr


@pytest.mark.integration
def test_items_list_all_empty_group_returns_valid_json(
    created_group: Callable[..., str], test_board_id: str
) -> None:
    """AC-5: items list --all with empty group returns valid JSON, exit 0."""
    _skip_if_no_token()
    group_id = created_group("ac5-all-empty")

    stdout, stderr, exit_code = run_cli_streams(
        "items",
        "list",
        "--board-id",
        test_board_id,
        "--group-id",
        group_id,
        "--all",
    )

    assert exit_code == 0
    _assert_clean_stdout(stdout, "items list --all empty group")
    data = json.loads(stdout.strip())
    assert data.get("items") == []
    assert data.get("total_items") == 0
    assert data.get("pages_fetched") is not None
