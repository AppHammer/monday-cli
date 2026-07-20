"""Unit tests for `monday columns delete` (issue #88).

Exercises the delete_column command via CliRunner + FakeClient without any
network traffic. The FakeClient dispatches on both "columns {" (GET_BOARD_COLUMNS
existence check) and "delete_column" (DELETE_COLUMN mutation).
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from monday_cli.cli import app
from tests.unit.conftest import FakeClient, status_column

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BOARD_ID = "123"
_COLUMN_ID = "status_abc123"
_COLUMN_TITLE = "Status"

_STATUS_COL = status_column(_COLUMN_ID, _COLUMN_TITLE, {"0": "Done", "1": "Working on it"})


def _make_client(**kwargs: object) -> FakeClient:
    """Return a FakeClient pre-loaded with a single column for the existence check."""
    return FakeClient(
        columns=[_STATUS_COL],
        **kwargs,  # type: ignore[arg-type]
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr("monday_cli.commands.columns.get_client", lambda: client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_force_deletes_without_prompt(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: --force skips the confirmation prompt and calls DELETE_COLUMN."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "delete",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _COLUMN_ID,
            "--force",
        ],
    )

    assert result.exit_code == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # Exactly one mutation must have been called (DELETE_COLUMN).
    assert len(client.mutations) == 1
    mutation_str, mutation_vars = client.mutations[0]
    assert "delete_column" in mutation_str
    assert mutation_vars == {"boardId": _BOARD_ID, "columnId": _COLUMN_ID}

    # stdout must be clean JSON with deleted: true
    data = json.loads(result.stdout.strip())
    assert data["deleted"] is True
    assert data["column_id"] == _COLUMN_ID
    assert data["board_id"] == _BOARD_ID
    assert data["title"] == _COLUMN_TITLE


def test_force_success_message_on_stderr(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: The check-mark confirmation goes to stderr; stdout stays clean JSON."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        ["columns", "delete", "--board-id", _BOARD_ID, "--column-id", _COLUMN_ID, "--force"],
    )

    assert result.exit_code == 0
    assert "✓" in result.stderr
    assert "deleted successfully" in result.stderr
    # stdout must be ONLY the JSON payload (FR-0008 contract).
    data = json.loads(result.stdout.strip())
    assert data["deleted"] is True


def test_confirmed_deletes(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: interactive 'y' confirmation triggers the delete."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        ["columns", "delete", "--board-id", _BOARD_ID, "--column-id", _COLUMN_ID],
        input="y\n",
    )

    assert result.exit_code == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # Mutation must have been called.
    assert len(client.mutations) == 1
    assert "delete_column" in client.mutations[0][0]

    # CliRunner echoes stdin back to stdout (the "y") before the JSON payload;
    # extract the JSON portion starting from the first "{".
    stdout = result.stdout
    json_start = stdout.find("{")
    assert json_start != -1, f"No JSON found in stdout: {stdout!r}"
    data = json.loads(stdout[json_start:])
    assert data["deleted"] is True


def test_declined_confirm_aborts_with_exit_0(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: declining the prompt aborts cleanly (exit 0), no delete call, no JSON."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        ["columns", "delete", "--board-id", _BOARD_ID, "--column-id", _COLUMN_ID],
        input="n\n",
    )

    assert result.exit_code == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # No DELETE_COLUMN mutation should have been issued.
    assert len(client.mutations) == 0
    # "cancelled" must appear on stderr.
    assert "cancelled" in result.stderr.lower()
    # stdout must not contain any JSON payload (no JSON emitted on cancel).
    # CliRunner echoes stdin ("n") to stdout; check there is no "{" JSON block.
    assert (
        "{" not in result.stdout
    ), f"No JSON object should appear in stdout on cancel, got: {result.stdout!r}"


def test_unknown_column_id_exits_1_with_teaching_tip(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4: non-existent column id → teaching error + tip, no delete attempt."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "delete",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            "does_not_exist",
            "--force",
        ],
    )

    assert result.exit_code == 1
    # No delete mutation should have been issued.
    assert len(client.mutations) == 0
    # Teaching tip must appear on stderr.
    assert "columns list" in result.stderr


def test_board_not_found_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """boards == [] → exit 1, no delete attempt."""
    client = FakeClient(columns=[])  # execute_query returns boards: []
    # Override so boards list is empty
    original_execute_query = client.execute_query

    def _empty_boards(query: str, variables: object = None) -> dict:
        client.queries.append((query, variables))  # type: ignore[arg-type]
        if "columns {" in query:
            return {"boards": []}
        return original_execute_query(query, variables)  # type: ignore[arg-type]

    client.execute_query = _empty_boards  # type: ignore[method-assign]
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "delete",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _COLUMN_ID,
            "--force",
        ],
    )

    assert result.exit_code == 1
    assert len(client.mutations) == 0
    assert "not found" in result.stderr.lower()


def test_null_api_payload_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_column returning None → exit 1 error message."""
    client = _make_client(delete_column_result=None)
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        ["columns", "delete", "--board-id", _BOARD_ID, "--column-id", _COLUMN_ID, "--force"],
    )

    assert result.exit_code == 1
    assert "failed to delete" in result.stderr.lower()
    # stdout must be empty (no JSON on error).
    assert result.stdout.strip() == ""


def test_stdout_clean_json_on_success(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3/FR-0008: stdout must be ONLY the JSON payload with no extra prose."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        ["columns", "delete", "--board-id", _BOARD_ID, "--column-id", _COLUMN_ID, "--force"],
    )

    assert result.exit_code == 0
    # The entire stdout must parse as JSON (no leading/trailing text allowed).
    data = json.loads(result.stdout.strip())
    assert isinstance(data, dict)
    assert set(data.keys()) >= {"column_id", "title", "deleted", "board_id"}
    assert data["deleted"] is True
