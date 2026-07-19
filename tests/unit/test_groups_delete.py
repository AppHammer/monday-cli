"""FR-0014: `groups delete` reports a trustworthy `deleted` signal.

These in-process unit tests exercise ``monday groups delete`` with a fake client
(zero network traffic) to lock in the FR-0014 contract:

  * AC-1/AC-2: a successful deletion emits ``"deleted": true`` on stdout, the
    ``✓`` on stderr, and exit 0 -- all mutually consistent -- **even when
    Monday's synchronous ``delete_group.deleted`` field comes back ``false``**
    (the eventual-consistency artifact the command must no longer forward).
  * AC-3: a group that is *verifiably still present* after the attempt reports
    ``"deleted": false`` on stdout, an error on stderr, and a non-zero exit --
    no false-positive successes.
  * AC-4: stdout stays clean, machine-readable JSON; the ``✓`` never leaks onto
    stdout (FR-0008 contract).

The command routes both ``DELETE_GROUP`` and ``GET_BOARD_GROUPS`` through
``client.execute_query`` (see ``commands/groups.py``), so the fake dispatches on
distinctive tokens in the operation string and can serve a *different* group
list for the initial title lookup versus the post-delete verification re-query.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from monday_cli.cli import app

runner = CliRunner()


class FakeGroupsClient:
    """Fake ``MondayGraphQLClient`` for the groups-delete command surface.

    ``groups_before`` is returned for the first ``GET_BOARD_GROUPS`` (the
    title->id lookup); ``groups_after`` is returned for every subsequent
    ``GET_BOARD_GROUPS`` (the FR-0014 verification re-query).  ``delete_response``
    is returned for the ``DELETE_GROUP`` mutation (or raised, if an Exception).
    """

    def __init__(
        self,
        *,
        groups_before: list[dict[str, Any]],
        delete_response: Any,
        groups_after: list[dict[str, Any]] | None = None,
    ) -> None:
        self.groups_before = groups_before
        self.delete_response = delete_response
        self.groups_after = groups_after if groups_after is not None else []
        self.group_query_count = 0
        self.delete_calls = 0

    def execute_query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if "delete_group(" in query:
            self.delete_calls += 1
            if isinstance(self.delete_response, Exception):
                raise self.delete_response
            return self.delete_response
        if "groups {" in query:
            self.group_query_count += 1
            groups = self.groups_before if self.group_query_count == 1 else self.groups_after
            return {"boards": [{"id": "1", "name": "Test Board", "groups": groups}]}
        raise AssertionError(f"Unexpected query dispatched:\n{query[:120]}")


def _group(group_id: str = "123", title: str = "Temp Group") -> dict[str, Any]:
    return {"id": group_id, "title": title, "color": "#ff642e", "position": "1"}


@pytest.fixture
def use_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch ``groups.get_client`` to return the supplied fake, and no-op sleep."""

    # The verification re-query sleeps between bounded attempts; keep unit tests
    # instant by neutralising the delay.
    monkeypatch.setattr("monday_cli.commands.groups.time.sleep", lambda _s: None)

    def _use(client: FakeGroupsClient) -> FakeGroupsClient:
        monkeypatch.setattr("monday_cli.commands.groups.get_client", lambda: client)
        return client

    return _use


def _delete(title: str = "Temp Group") -> Any:
    return runner.invoke(
        app,
        ["groups", "delete", "--title", title, "--board-id", "1", "--confirm"],
    )


# --- AC-1 / AC-2: stale `deleted: false` must not defeat a genuine success ---


def test_reports_deleted_true_even_when_api_deleted_false(use_client: Any) -> None:
    """The core FR-0014 bug: API says deleted=false, group is genuinely gone."""
    use_client(
        FakeGroupsClient(
            groups_before=[_group()],
            delete_response={"delete_group": {"id": "123", "deleted": False}},
            groups_after=[],  # verification confirms the group is gone
        )
    )

    result = _delete()

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["deleted"] is True
    assert data["group_id"] == "123"
    assert data["title"] == "Temp Group"


def test_success_message_on_stderr_and_stdout_is_clean_json(use_client: Any) -> None:
    """AC-4: ✓ goes to stderr; stdout is a single clean JSON document."""
    use_client(
        FakeGroupsClient(
            groups_before=[_group()],
            delete_response={"delete_group": {"id": "123", "deleted": False}},
            groups_after=[],
        )
    )

    result = _delete()

    assert result.exit_code == 0
    # stdout parses as ONE JSON doc with nothing else around it.
    assert json.loads(result.stdout)["deleted"] is True
    # The success marker is on stderr, never stdout.
    assert "✓" in result.stderr
    assert "✓" not in result.stdout


def test_api_confirmed_delete_skips_verification_requery(use_client: Any) -> None:
    """When the API itself confirms deleted=true, no extra re-query is spent."""
    client = use_client(
        FakeGroupsClient(
            groups_before=[_group()],
            delete_response={"delete_group": {"id": "123", "deleted": True}},
            groups_after=[_group()],  # would (wrongly) look present if consulted
        )
    )

    result = _delete()

    assert result.exit_code == 0
    assert json.loads(result.stdout)["deleted"] is True
    # Exactly one GET_BOARD_GROUPS call: the title lookup. No verification call.
    assert client.group_query_count == 1


# --- AC-3: a verifiably still-present group is a genuine failure -------------


def test_still_present_reports_deleted_false_and_nonzero_exit(use_client: Any) -> None:
    use_client(
        FakeGroupsClient(
            groups_before=[_group()],
            delete_response={"delete_group": {"id": "123", "deleted": False}},
            groups_after=[_group()],  # still there across every verification attempt
        )
    )

    result = _delete()

    assert result.exit_code != 0
    data = json.loads(result.stdout)
    assert data["deleted"] is False
    assert data["group_id"] == "123"
    assert "still present" in result.stderr.lower()


def test_null_delete_group_result_errors_nonzero(use_client: Any) -> None:
    """A null `delete_group` payload remains a hard error (no false positive)."""
    use_client(
        FakeGroupsClient(
            groups_before=[_group()],
            delete_response={"delete_group": None},
        )
    )

    result = _delete()

    assert result.exit_code != 0
    assert result.stdout.strip() == ""  # no JSON emitted on this failure path
    assert "failed to delete" in result.stderr.lower()


def test_missing_group_by_title_is_teaching_error_exit_1(use_client: Any) -> None:
    """AC-5: the not-found-by-title path is unchanged (exit 1, never touches API delete)."""
    client = use_client(
        FakeGroupsClient(
            groups_before=[_group(title="Something Else")],
            delete_response={"delete_group": {"id": "123", "deleted": True}},
        )
    )

    result = _delete(title="No Such Group")

    assert result.exit_code == 1
    assert client.delete_calls == 0
    assert "not found" in result.stderr.lower()
