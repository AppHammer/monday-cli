"""Shared integration-test harness for the Monday CLI.

Every fixture here drives the `monday` CLI against the LIVE Monday.com API,
pinned to the scratch/test board (18422673411) -- NEVER the
project-management board (18422673287); `test_board_id` hard-fails if it
ever resolves to the latter. Tests are gated behind `MONDAY_API_TOKEN`
(skipped cleanly when absent, e.g. on forked-PR CI) and must all be marked
`@pytest.mark.integration` so the suite can be selected/deselected via
`pytest -m integration`.

Expected API call budget (stay well under the 60 calls/60s rate limit):
    - `test_board_id` / `run_id`: 0 calls -- pure config, no API traffic.
    - `created_group` factory: 1 call to create + 1 call to delete per
      artifact the factory function is invoked for (2 calls/artifact).
    - `created_item` factory: likewise, 2 calls/artifact.
    - `created_subitem` factory: likewise, 2 calls/artifact.
  These fixtures are function-scoped (fresh factory per test, torn down at
  the end of that test) so failure-safety is easy to reason about. Suites
  with many small tests should still call each factory sparingly per test
  and/or share one artifact across assertions to stay under budget; a suite
  that needs a single shared fixture across its whole module (e.g. one
  shared group reused by many item tests) can layer a session-scoped
  fixture of its own on top of these in its own conftest.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Iterator, Mapping

import pytest

from tests.integration.helpers import run_cli

PM_BOARD_ID = "18422673287"
DEFAULT_TEST_BOARD_ID = "18422673411"


def _resolve_test_board_id(env: Mapping[str, str]) -> str:
    """Resolve the board id integration tests are allowed to mutate.

    Defaults to the scratch test board. Honours `MONDAY_TEST_BOARD_ID` for
    an explicit override, but refuses -- unconditionally -- to resolve to
    the project-management board. Factored out of the `test_board_id`
    fixture so the guard itself is directly unit-testable (see
    test_harness.py) without needing a live API call or a nested pytest run.
    """
    board_id = env.get("MONDAY_TEST_BOARD_ID", DEFAULT_TEST_BOARD_ID)
    if board_id == PM_BOARD_ID:
        pytest.fail(
            "Refusing to run integration tests against the project-management "
            f"board ({PM_BOARD_ID}). Integration tests must target the scratch "
            f"test board ({DEFAULT_TEST_BOARD_ID}) only -- never the PM board. "
            "If you intended an override, set MONDAY_TEST_BOARD_ID to a "
            "different scratch/test board id."
        )
    return board_id


@pytest.fixture(scope="session", autouse=True)
def _require_api_token() -> None:
    """Skip the whole integration suite cleanly when no token is configured.

    Autouse within tests/integration, so every test collected here is gated
    without each test file needing to opt in individually. Local runs and
    forked-PR CI (which cannot see repo secrets) skip instead of erroring,
    which keeps `pytest -m integration --collect-only` working everywhere.
    """
    if not os.environ.get("MONDAY_API_TOKEN"):
        pytest.skip("MONDAY_API_TOKEN not set; skipping integration tests")


@pytest.fixture(scope="session")
def api_token() -> str:
    """The Monday.com API token used for this test run.

    Also serves as an explicit skip gate for any fixture/test that wants to
    depend on the token directly rather than relying only on the autouse
    gate above.
    """
    token = os.environ.get("MONDAY_API_TOKEN")
    if not token:
        pytest.skip("MONDAY_API_TOKEN not set; skipping integration tests")
    return token


@pytest.fixture(scope="session")
def test_board_id() -> str:
    """The board id integration tests are allowed to create/mutate/delete on."""
    return _resolve_test_board_id(os.environ)


@pytest.fixture(scope="session")
def run_id() -> str:
    """A short unique suffix appended to every created artifact's name.

    Keeps parallel CI runs on the shared test board from colliding on
    artifact names, e.g. "it-48213-a1b2c3".
    """
    return f"it-{os.getpid()}-{secrets.token_hex(3)}"


def _swallow_not_found(*args: str) -> None:
    """Run a delete command, tolerating an artifact that's already gone.

    Delete commands in this CLI exit 1 with a "not found" message when the
    target no longer exists. Teardown must be idempotent -- if the test body
    already deleted the artifact (or errored after partially cleaning up),
    that must not fail the harness.
    """
    run_cli(*args, expect_error=True)


@pytest.fixture
def created_group(test_board_id: str, run_id: str) -> Iterator[Callable[..., str]]:
    """Factory fixture: create groups on the test board, deleted at teardown.

    Returns a callable; call it once per group you need:

        def test_x(created_group):
            group_id = created_group()                  # auto-named
            other_id = created_group("backlog")          # explicit suffix

    Every group created through the factory is deleted in teardown -- even
    if the test body raises -- because `groups delete` only takes a title
    (not an id), each call's title is remembered alongside its id.
    """
    records: list[tuple[str, str]] = []
    counter = 0

    def _create(title_suffix: str | None = None, color: str | None = None) -> str:
        nonlocal counter
        counter += 1
        title = f"{run_id}-{title_suffix}" if title_suffix else f"{run_id}-group-{counter}"
        args = ["groups", "create", "--title", title, "--board-id", test_board_id]
        if color:
            args += ["--color", color]
        data = run_cli(*args)
        group_id = str(data["group_id"])
        records.append((group_id, title))
        return group_id

    yield _create

    for group_id, title in records:
        _swallow_not_found(
            "groups", "delete", "--title", title, "--board-id", test_board_id, "--confirm"
        )


@pytest.fixture
def created_item(test_board_id: str, run_id: str) -> Iterator[Callable[..., str]]:
    """Factory fixture: create items on the test board, deleted at teardown.

    Returns a callable; call it once per item you need:

        def test_x(created_item):
            item_id = created_item()                          # auto-named
            other_id = created_item("task-a", group_id="new_group")

    Every item created through the factory is deleted (`items delete
    --force`) in teardown, even if the test body raises.
    """
    created_ids: list[str] = []
    counter = 0

    def _create(
        name_suffix: str | None = None,
        group_id: str | None = None,
        column_values: str | None = None,
    ) -> str:
        nonlocal counter
        counter += 1
        name = f"{run_id}-{name_suffix}" if name_suffix else f"{run_id}-item-{counter}"
        args = ["items", "create", "--board-id", test_board_id, "--name", name]
        if group_id:
            args += ["--group-id", group_id]
        if column_values:
            args += ["--column-values", column_values]
        data = run_cli(*args)
        item_id = str(data["id"])
        created_ids.append(item_id)
        return item_id

    yield _create

    for item_id in created_ids:
        _swallow_not_found("items", "delete", "--item-id", item_id, "--force")


@pytest.fixture
def created_subitem(run_id: str) -> Iterator[Callable[..., str]]:
    """Factory fixture: create subitems under a parent item, deleted at teardown.

    Requires a parent item id (create one with `created_item` first):

        def test_x(created_item, created_subitem):
            parent_id = created_item()
            subitem_id = created_subitem(parent_id)
            other_id = created_subitem(parent_id, "subtask-b")

    Every subitem created through the factory is deleted (`subitems delete
    --force`) in teardown, even if the test body raises.
    """
    created_ids: list[str] = []
    counter = 0

    def _create(
        parent_item_id: str,
        name_suffix: str | None = None,
        column_values: str | None = None,
    ) -> str:
        nonlocal counter
        counter += 1
        name = f"{run_id}-{name_suffix}" if name_suffix else f"{run_id}-subitem-{counter}"
        args = [
            "subitems",
            "create",
            "--parent-item-id",
            str(parent_item_id),
            "--name",
            name,
        ]
        if column_values:
            args += ["--column-values", column_values]
        data = run_cli(*args)
        subitem_id = str(data["id"])
        created_ids.append(subitem_id)
        return subitem_id

    yield _create

    for subitem_id in created_ids:
        _swallow_not_found("subitems", "delete", "--subitem-id", subitem_id, "--force")
