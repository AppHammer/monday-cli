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
import time
import warnings
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from tests.integration.helpers import run_cli, run_cli_until

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


_TEARDOWN_MAX_ATTEMPTS = 3
_TEARDOWN_BACKOFF_SECONDS = 1.5


def _swallow_not_found(
    *args: str,
    max_attempts: int = _TEARDOWN_MAX_ATTEMPTS,
    backoff_seconds: float = _TEARDOWN_BACKOFF_SECONDS,
    confirm_absent: Callable[[], bool] | None = None,
) -> None:
    """Run a delete command, tolerating an artifact that's already gone --
    but never silently swallowing a REAL teardown failure.

    Delete commands in this CLI exit 1 with a "not found" message when the
    target no longer exists; that specific case is expected and idempotent
    (the test body may have already deleted the artifact, or errored after
    partially cleaning up), so it is swallowed unconditionally.

    Any OTHER outcome -- a transient blip (rate limit, network hiccup) or a
    genuine API error -- is retried a bounded number of times with a short
    backoff, since a single `expect_error=True` attempt can't tell "already
    gone" apart from "delete failed" and previously discarded both the same
    way, silently leaking artifacts on the shared TEST board. If the artifact
    still can't be confirmed deleted after all attempts, this surfaces a
    `pytest.warns`-visible warning (never an exception -- teardown must not
    raise, or it would abort every other fixture's teardown in the same
    test's stack) so a real leak shows up in the test run instead of
    vanishing.

    FR-0013 #70 (AC-2): the delete RESPONSE alone is not always trustworthy --
    `groups delete` reports `deleted: false` even on a genuine removal on this
    account (see test_groups.py), so a JSON response can't prove absence. When
    a ``confirm_absent`` callable is supplied, it is invoked after a
    successful-looking delete to verify the artifact is actually gone (a
    bounded list poll, tolerant of eventual consistency); if it still can't
    confirm absence -- or itself errors -- a warning is surfaced rather than
    trusting the delete blindly. Resources with a trustworthy `deleted: true`
    signal (items/subitems) omit it and keep a single delete call.
    """
    last_output: Any = None
    last_exc: BaseException | None = None
    deleted = False

    for attempt in range(1, max_attempts + 1):
        try:
            last_output = run_cli(*args, expect_error=True)
            last_exc = None
        except Exception as exc:  # pragma: no cover - defensive; teardown must not raise
            last_exc = exc
            last_output = None

        if last_exc is None:
            if isinstance(last_output, str) and "not found" in last_output.lower():
                return  # Genuinely already gone -- expected, idempotent teardown.
            if not isinstance(last_output, str):
                deleted = True  # `run_cli` returned parsed JSON -- delete exited 0.
                break

        if attempt < max_attempts:
            time.sleep(backoff_seconds * attempt)

    if not deleted:
        detail = repr(last_exc) if last_exc is not None else last_output
        warnings.warn(
            "Integration teardown could not confirm deletion after "
            f"{max_attempts} attempts: monday {' '.join(args)}\n"
            f"Last output: {detail}\n"
            "This artifact may still exist on the shared TEST board and require "
            "manual cleanup.",
            stacklevel=2,
        )
        return

    # Delete reported success -- optionally verify the artifact is really gone.
    if confirm_absent is None:
        return
    try:
        confirmed = confirm_absent()
    except Exception as exc:  # defensive: confirmation must not abort teardown
        confirmed = False
        warnings.warn(
            f"Integration teardown could not verify deletion (confirmation errored) for: "
            f"monday {' '.join(args)}\nError: {exc!r}",
            stacklevel=2,
        )
        return
    if not confirmed:
        warnings.warn(
            "Integration teardown deleted an artifact but could not confirm its "
            f"absence via a follow-up list: monday {' '.join(args)}\n"
            "This artifact may still exist on the shared TEST board and require "
            "manual cleanup.",
            stacklevel=2,
        )


# --- Run-scoped isolation + backstop sweep (FR-0013 #70) ---------------------
#
# The suite runs on a SHARED test board that overlapping CI runs mutate
# concurrently. Two mechanisms keep it deterministic and leak-free:
#   1. Per-run namespacing: every artifact is named `<run_id>-...` (see
#      `run_id`), so a run's absence-assertions can be scoped to its own slice
#      and a foreign/leaked artifact can never satisfy or break them.
#   2. A session-scoped backstop sweep (`_backstop_sweep`) that removes STALE
#      `it-*` items left behind by a previously-crashed run -- age-guarded via
#      each item's `created_at` so it can NEVER delete a concurrently-running
#      run's fresh artifacts. Groups carry no `created_at` in Monday's API and
#      so cannot be age-guarded; they are cleaned at source by the failure-safe
#      factory teardown (with `confirm_absent` above) rather than swept.

SWEEP_NAME_PREFIX = "it-"
_DEFAULT_SWEEP_MAX_AGE_SECONDS = 3600.0


def _sweep_max_age_seconds(env: Mapping[str, str]) -> float:
    """How old (seconds) an `it-*` item must be before the backstop sweeps it.

    Env-tunable via ``MONDAY_IT_SWEEP_MAX_AGE_SECONDS``. The default (1h) is
    comfortably longer than any single integration run, which is what makes the
    age guard safe under concurrency: a live run's artifacts are always younger
    than the threshold and therefore never selected.
    """
    raw = env.get("MONDAY_IT_SWEEP_MAX_AGE_SECONDS")
    if raw is None:
        return _DEFAULT_SWEEP_MAX_AGE_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_SWEEP_MAX_AGE_SECONDS
    return value if value > 0 else _DEFAULT_SWEEP_MAX_AGE_SECONDS


def _parse_created_at(value: Any) -> datetime | None:
    """Parse a Monday `created_at` ISO-8601 string to an aware UTC datetime.

    Returns None for anything unparseable/absent -- the caller treats that as
    "cannot age-guard", i.e. leaves the item alone (never sweeps it).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _select_stale_item_ids(
    items: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    max_age_seconds: float,
    prefix: str = SWEEP_NAME_PREFIX,
) -> list[str]:
    """Pure selection for the backstop sweep (unit-tested, no API).

    Returns the ids of items that BOTH (a) carry the integration naming
    ``prefix`` and (b) are at least ``max_age_seconds`` old per their
    ``created_at``. Items whose ``created_at`` can't be parsed are treated as
    too-young and NOT selected -- deleting a concurrent live run's artifact is
    far worse than leaving an old leak for the next session's sweep.
    """
    stale: list[str] = []
    for item in items:
        name = str(item.get("name", ""))
        if not name.startswith(prefix):
            continue
        created = _parse_created_at(item.get("created_at"))
        if created is None:
            continue
        if (now - created).total_seconds() >= max_age_seconds:
            item_id = item.get("id")
            if item_id is not None:
                stale.append(str(item_id))
    return stale


def _group_absent(board_id: str, title: str) -> bool:
    """Bounded-poll confirmation that a group `title` no longer exists.

    Reuses the FR-0013 #69 poll helper so a delete that is genuinely done but
    briefly lags on the `groups list` read still confirms rather than warning
    spuriously. Returns True once the title is gone; False if it is still
    present after the bounded poll.
    """
    data = run_cli_until(
        lambda d: isinstance(d, dict)
        and title not in {g.get("title") for g in d.get("groups", [])},
        "groups",
        "list",
        "--board-id",
        board_id,
    )
    if not isinstance(data, dict):
        return False
    return title not in {g.get("title") for g in data.get("groups", [])}


def _run_backstop_sweep(board_id: str, phase: str) -> None:
    """List the test board and delete stale `it-*` items (age-guarded).

    Best-effort and defensive: any failure is warned, never raised, so a sweep
    problem can't abort the session. Only ever touches the resolved test board
    (never the PM board -- `test_board_id` hard-fails on it) and only `it-*`
    prefixed items, so foreign board content is never at risk.
    """
    if not os.environ.get("MONDAY_API_TOKEN"):
        return
    try:
        data = run_cli("items", "list", "--board-id", board_id, "--all", "--limit", "500")
    except Exception as exc:  # defensive: a sweep must not break the session
        warnings.warn(f"Backstop sweep ({phase}) could not list the board: {exc!r}", stacklevel=2)
        return
    items = data.get("items", []) if isinstance(data, dict) else []
    stale = _select_stale_item_ids(
        items,
        now=datetime.now(UTC),
        max_age_seconds=_sweep_max_age_seconds(os.environ),
    )
    if not stale:
        return
    warnings.warn(
        f"Backstop sweep ({phase}) removing {len(stale)} stale it-* item(s) left by a "
        f"prior crashed run: {', '.join(stale)}",
        stacklevel=2,
    )
    for item_id in stale:
        _swallow_not_found("items", "delete", "--item-id", item_id, "--force")


@pytest.fixture(scope="session", autouse=True)
def _backstop_sweep(test_board_id: str) -> Iterator[None]:
    """Sweep stale `it-*` leaks at session start AND end (age-guarded).

    Autouse + session-scoped: runs once around the whole integration session.
    Skips cleanly when no token is configured. The start sweep clears leaks
    from earlier crashed runs before this session begins; the end sweep is the
    final backstop. Neither can touch a concurrently-running run's artifacts,
    which are always younger than the age threshold.
    """
    _run_backstop_sweep(test_board_id, "session start")
    yield
    _run_backstop_sweep(test_board_id, "session end")


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
            "groups",
            "delete",
            "--title",
            title,
            "--board-id",
            test_board_id,
            "--confirm",
            confirm_absent=lambda t=title: _group_absent(test_board_id, t),
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
