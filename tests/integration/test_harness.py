"""Meta-tests for the shared integration harness itself (US-0002-01).

These don't test Monday.com resource commands directly -- they prove the
harness's own contracts hold: the board guard refuses the PM board, factory
fixtures clean up even when a test fails, and `run_cli` returns parsed JSON
vs. raw text on request. Every resource suite (#16-#21) depends on these
contracts being correct.

FR-0013: The residue-check pair (``test_created_item_teardown_runs_on_
forced_failure`` + ``test_created_item_leaves_no_residue_after_forced_
failure``) retains a deliberate ordering constraint because the teardown
that is being verified runs BETWEEN those two tests and cannot be captured
any other way. This is the ONLY permitted ordering dependency in the
integration suite; all other tests are fully independent.

The dependency is documented here and enforced by the ``_teardown_residue``
session fixture below, which stores state in a mutable dict rather than a
bare module-level variable so the dependency is explicit and inspectable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tests.integration.conftest import DEFAULT_TEST_BOARD_ID, PM_BOARD_ID, _resolve_test_board_id
from tests.integration.helpers import run_cli

# ---------------------------------------------------------------------------
# Shared state for the residue-check pair (see module docstring).
# ---------------------------------------------------------------------------

# This dict is populated by ``test_created_item_teardown_runs_on_forced_failure``
# (the xfail test) and read by ``test_created_item_leaves_no_residue_after_forced_failure``.
# If the xfail test did not run first (e.g. due to pytest -k filtering), the
# residue-check test skips instead of failing with a confusing AssertionError.
_teardown_residue: dict[str, Any] = {}


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

    FR-0013: The teardown state is stored in ``_teardown_residue`` (a module-
    level dict) rather than a local variable so the residue-check test below
    can read it. This is the ONLY ordering dependency permitted in the suite.
    """
    item_id = created_item("residue-check")
    _teardown_residue["item_id"] = item_id
    _teardown_residue["board_id"] = test_board_id
    raise AssertionError("Intentional failure to prove factory teardown is failure-safe")


@pytest.mark.integration
def test_created_item_leaves_no_residue_after_forced_failure() -> None:
    """Confirms the item from the previous (intentionally-failing) test is gone.

    Relies on running immediately after ``test_created_item_teardown_runs_on_
    forced_failure`` in file order (no test-randomization plugin is installed
    in this project). Uses ``--all`` to paginate the full board regardless of
    its size, so the absence check can't produce a false negative just
    because the item happens to fall past a bounded page.

    FR-0013: Skips gracefully with an explanatory message if the preceding
    xfail test did not populate ``_teardown_residue`` (e.g. because pytest
    was run with ``-k`` filtering that excluded the xfail test). This prevents
    a confusing bare ``AssertionError`` that looks like a real harness failure.
    """
    if not _teardown_residue:
        pytest.skip(
            "Skipping residue check: ``test_created_item_teardown_runs_on_forced_failure`` "
            "did not run before this test (e.g. excluded by -k filtering). "
            "Run the full test_harness.py module to exercise both halves of the pair."
        )
    output = run_cli(
        "items", "list", "--board-id", _teardown_residue["board_id"], "--all", raw=True
    )
    assert _teardown_residue["item_id"] not in output


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
