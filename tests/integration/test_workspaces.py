"""Read-coverage integration tests for `monday workspaces list` (US-0002-02).

Workspaces has no create/delete surface in this CLI, so this suite is purely
read-only: it proves `workspaces list` returns parseable JSON against the
live API, exercises its `--membership-kind` and `--workspace-ids` filters,
and smoke-checks `--table` rendering. Nothing is created or deleted on any
board.
"""

from __future__ import annotations

import pytest

from tests.integration.helpers import run_cli


@pytest.mark.integration
def test_list_returns_workspaces_payload() -> None:
    data = run_cli("workspaces", "list")

    assert isinstance(data, dict)
    assert "workspaces" in data
    assert isinstance(data["workspaces"], list)
    assert "total_count" in data
    assert data["total_count"] == len(data["workspaces"])


@pytest.mark.integration
def test_list_filters_by_membership_kind_member() -> None:
    data = run_cli("workspaces", "list", "--membership-kind", "member")

    assert isinstance(data, dict)
    assert isinstance(data.get("workspaces"), list)
    assert data.get("membership_kind_filter") == "member"


@pytest.mark.integration
def test_list_filters_by_workspace_ids_when_determinable() -> None:
    # Discover a real workspace id from the unfiltered listing first --
    # workspace ids are account-specific, so we can't hardcode one.
    all_workspaces = run_cli("workspaces", "list")["workspaces"]
    if not all_workspaces:
        pytest.skip("No workspaces visible to this account; cannot exercise --workspace-ids")

    workspace_id = str(all_workspaces[0]["id"])

    data = run_cli("workspaces", "list", "--workspace-ids", workspace_id)

    assert isinstance(data, dict)
    assert data.get("workspace_ids_filter") == workspace_id
    returned_ids = {str(ws["id"]) for ws in data.get("workspaces", [])}
    assert workspace_id in returned_ids


@pytest.mark.integration
def test_list_table_output_renders_without_error() -> None:
    output = run_cli("workspaces", "list", "--table", raw=True)

    assert output.strip() != ""
