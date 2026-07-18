"""Meta-tests for the shared integration harness itself (US-0002-01).

These don't test Monday.com resource commands directly -- they prove the
harness's own contracts hold: the board guard refuses the PM board, factory
fixtures clean up even when a test fails, and `run_cli` returns parsed JSON
vs. raw text on request. Every resource suite (#16-#21) depends on these
contracts being correct.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.integration.conftest import DEFAULT_TEST_BOARD_ID, PM_BOARD_ID, _resolve_test_board_id
from tests.integration.helpers import run_cli

# Shared between the two forced-failure tests below -- see the docstring on
# test_created_item_leaves_no_residue_after_forced_failure for why this has
# to be a second, adjacent test rather than inline assertions.
_residue_state: dict[str, str] = {}


# --- Board guard (AC-4) ------------------------------------------------------


@pytest.mark.integration
def test_test_board_id_resolves_to_the_scratch_board(test_board_id: str) -> None:
    assert test_board_id != PM_BOARD_ID
    assert test_board_id == DEFAULT_TEST_BOARD_ID


@pytest.mark.integration
def test_test_board_id_honours_env_override() -> None:
    assert _resolve_test_board_id({"MONDAY_TEST_BOARD_ID": "999999"}) == "999999"
    assert _resolve_test_board_id({}) == DEFAULT_TEST_BOARD_ID


@pytest.mark.integration
def test_test_board_id_guard_rejects_the_pm_board() -> None:
    with pytest.raises(pytest.fail.Exception):
        _resolve_test_board_id({"MONDAY_TEST_BOARD_ID": PM_BOARD_ID})


# --- Factory teardown is failure-safe (AC-3) ---------------------------------


@pytest.mark.integration
@pytest.mark.xfail(
    strict=True,
    reason="intentionally forces a failure to prove factory teardown runs even then; "
    "strict=True turns the expected AssertionError into a clean XFAIL instead of a "
    "suite failure, and would itself fail if the forced failure stopped firing",
)
def test_created_item_teardown_runs_on_forced_failure(
    created_item: Callable[..., str], test_board_id: str
) -> None:
    """Create an item, then force a failure -- teardown must still delete it.

    The residue check is a separate, adjacent test (below) because this
    fixture's teardown runs during pytest's teardown phase, which happens
    after this test function has already returned/raised -- there is no
    point inside this test where the cleanup has both happened AND we still
    have control to assert on it.
    """
    item_id = created_item("residue-check")
    _residue_state["item_id"] = item_id
    _residue_state["board_id"] = test_board_id
    raise AssertionError("Intentional failure to prove factory teardown is failure-safe")


@pytest.mark.integration
def test_created_item_leaves_no_residue_after_forced_failure() -> None:
    """Confirms the item from the previous (intentionally-failing) test is gone.

    Relies on running immediately after `test_created_item_teardown_runs_on_
    forced_failure` in file order (no test-randomization plugin is installed
    in this project). A single bounded-size listing is enough to prove
    absence: the item was created moments ago by the previous test, so if
    teardown ran it will not appear anywhere in a fresh listing.
    """
    assert _residue_state, "Prior test did not run or did not populate shared state"
    output = run_cli(
        "items", "list", "--board-id", _residue_state["board_id"], "--limit", "500", raw=True
    )
    assert _residue_state["item_id"] not in output


# --- run_cli JSON vs. raw contract --------------------------------------------


@pytest.mark.integration
def test_run_cli_returns_parsed_json_for_a_json_command(test_board_id: str) -> None:
    data = run_cli("items", "list", "--board-id", test_board_id, "--limit", "1")
    assert isinstance(data, dict)
    assert data["board_id"] == test_board_id
    assert "items" in data


@pytest.mark.integration
def test_run_cli_returns_raw_text_when_raw_is_true() -> None:
    # `version` is a local, API-free command that prints plain text via
    # `typer.echo` (not JSON) -- the same shape `docs get` produces for
    # Markdown -- so it's a cheap, deterministic stand-in for exercising the
    # raw=True code path without depending on the test board's doc columns.
    text = run_cli("version", raw=True)
    assert isinstance(text, str)
    assert "monday-cli version" in text

    with pytest.raises(Exception):
        # The same output is not valid JSON, proving raw=True actually
        # bypassed JSON parsing rather than happening to parse anyway.
        import json

        json.loads(text)
