"""Unit tests for `monday columns create` (issue #86 / FR-0018).

Exercises the columns create command with a FakeClient (zero network traffic)
to lock in the output contract:

  * AC1: JSON stdout has column_id, title, type, board_id.
  * AC2: status columns pass the correct verified defaults shape.
  * AC2: dropdown columns pass the correct verified defaults shape.
  * AC3: unsupported type → exit 1 + teaching error, no mutation call.
  * AC4: --labels on non-label type → exit 1 + teaching error, no mutation call.
  * AC5: ✓ success marker goes to stderr; stdout is clean JSON.
  * null payload guard: create_column returns None → exit 1.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from monday_cli.cli import app
from tests.unit.conftest import FakeClient

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    *,
    col_id: str = "text_abc123",
    title: str = "My Column",
    col_type: str = "text",
    settings_str: str = "{}",
    null_result: bool = False,
) -> FakeClient:
    """Return a FakeClient whose create_column_result matches the given column."""
    result: dict[str, Any] | None = (
        None
        if null_result
        else {
            "id": col_id,
            "title": title,
            "type": col_type,
            "description": None,
            "settings_str": settings_str,
        }
    )
    return FakeClient(create_column_result=result)


def _invoke(*args: str) -> Any:
    return runner.invoke(app, list(args))


def _use(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> FakeClient:
    monkeypatch.setattr("monday_cli.commands.columns.get_client", lambda: client)
    return client


# ---------------------------------------------------------------------------
# AC1: creates a text column — no defaults sent, JSON has expected keys
# ---------------------------------------------------------------------------


def test_create_text_column_no_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: text column creation sends columnType='text', no defaults; JSON has column_id."""
    client = _use(
        monkeypatch,
        _make_client(col_id="text_abc123", title="Notes", col_type="text"),
    )

    result = _invoke("columns", "create", "--board-id", "999", "--title", "Notes", "--type", "text")

    assert result.exit_code == 0, result.output
    # Exactly one mutation must have been dispatched
    assert len(client.mutations) == 1
    _mutation_str, variables = client.mutations[0]
    assert variables is not None
    assert variables["boardId"] == "999"
    assert variables["title"] == "Notes"
    assert variables["columnType"] == "text"
    assert "defaults" not in variables, "text column must not include defaults"

    # Stdout must be valid JSON with all required keys
    data = json.loads(result.stdout)
    assert data["column_id"] == "text_abc123"
    assert data["title"] == "Notes"
    assert data["type"] == "text"
    assert data["board_id"] == "999"


# ---------------------------------------------------------------------------
# AC2: creates a status column with labels — correct verified defaults shape
# ---------------------------------------------------------------------------


def test_create_status_column_with_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: status column sends verified defaults shape {"labels": {"1": ..., "2": ...}}."""
    settings_str = json.dumps({"labels": {"1": "Low", "2": "High"}})
    client = _use(
        monkeypatch,
        _make_client(
            col_id="color_xyz",
            title="Priority",
            col_type="status",
            settings_str=settings_str,
        ),
    )

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "123",
        "--title",
        "Priority",
        "--type",
        "status",
        "--labels",
        "Low,High",
    )

    assert result.exit_code == 0, result.output
    assert len(client.mutations) == 1
    _mutation_str, variables = client.mutations[0]
    assert variables is not None
    assert variables["columnType"] == "status"

    # defaults must be the VERIFIED shape: index→label map starting at 1
    defaults_raw = variables.get("defaults")
    assert defaults_raw is not None, "status column with labels must include defaults"
    defaults = json.loads(defaults_raw)
    assert defaults == {"labels": {"1": "Low", "2": "High"}}

    data = json.loads(result.stdout)
    assert data["column_id"] == "color_xyz"
    assert data["type"] == "status"


# ---------------------------------------------------------------------------
# AC2: creates a dropdown column with labels — correct verified defaults shape
# ---------------------------------------------------------------------------


def test_create_dropdown_column_with_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: dropdown column sends verified defaults shape nested under 'settings'."""
    settings_str = json.dumps({"labels": [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}]})
    client = _use(
        monkeypatch,
        _make_client(
            col_id="dropdown_def",
            title="Category",
            col_type="dropdown",
            settings_str=settings_str,
        ),
    )

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "456",
        "--title",
        "Category",
        "--type",
        "dropdown",
        "--labels",
        "Alpha,Beta",
    )

    assert result.exit_code == 0, result.output
    assert len(client.mutations) == 1
    _mutation_str, variables = client.mutations[0]
    assert variables is not None
    assert variables["columnType"] == "dropdown"

    # defaults must be the VERIFIED shape: nested under "settings", key is "label" on WRITE
    defaults_raw = variables.get("defaults")
    assert defaults_raw is not None, "dropdown column with labels must include defaults"
    defaults = json.loads(defaults_raw)
    assert defaults == {
        "settings": {
            "labels": [
                {"id": 1, "label": "Alpha"},
                {"id": 2, "label": "Beta"},
            ]
        }
    }

    data = json.loads(result.stdout)
    assert data["column_id"] == "dropdown_def"
    assert data["type"] == "dropdown"


# ---------------------------------------------------------------------------
# AC3: unsupported type → exit 1, teaching error, NO mutation
# ---------------------------------------------------------------------------


def test_unsupported_type_exits_1_no_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3: an invalid column type exits 1, lists supported types, makes no API call."""
    client = _use(monkeypatch, _make_client())

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "1",
        "--title",
        "X",
        "--type",
        "mirror",
    )

    assert result.exit_code == 1
    assert len(client.mutations) == 0, "no mutation should be called for unsupported type"
    # Stderr must mention the bad type and list of supported types
    stderr = result.stderr
    assert "mirror" in stderr.lower() or "unsupported" in stderr.lower()
    # At least one of the known supported types must appear in the teaching error
    assert "status" in stderr or "text" in stderr


# ---------------------------------------------------------------------------
# AC4: --labels on non-label type (text) → exit 1, teaching error, NO mutation
# ---------------------------------------------------------------------------


def test_labels_on_text_type_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: passing --labels with a non-label type exits 1 with a teaching error; no mutation."""
    client = _use(monkeypatch, _make_client())

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "1",
        "--title",
        "Notes",
        "--type",
        "text",
        "--labels",
        "A,B",
    )

    assert result.exit_code == 1
    assert len(client.mutations) == 0, "no mutation should be called when labels rejected"
    stderr = result.stderr
    # Must explain that labels only apply to certain column types
    assert "label" in stderr.lower()
    assert "text" in stderr.lower()


# ---------------------------------------------------------------------------
# AC5: ✓ on stderr, stdout is clean JSON (separation of concerns)
# ---------------------------------------------------------------------------


def test_success_marker_on_stderr_stdout_is_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC5: the ✓ success marker appears on stderr only; stdout is a valid JSON doc."""
    _use(
        monkeypatch,
        _make_client(col_id="chk_1", title="Done?", col_type="checkbox"),
    )

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "7",
        "--title",
        "Done?",
        "--type",
        "checkbox",
    )

    assert result.exit_code == 0, result.output
    # ✓ must appear on stderr, NOT stdout
    assert "✓" in result.stderr
    assert "✓" not in result.stdout
    # stdout must be valid JSON
    data = json.loads(result.stdout)
    assert "column_id" in data
    assert "title" in data
    assert "type" in data
    assert "board_id" in data


# ---------------------------------------------------------------------------
# Null payload guard: API returns None for create_column → exit 1
# ---------------------------------------------------------------------------


def test_null_api_payload_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the API returns null for create_column, exit 1 with a teaching error."""
    _use(monkeypatch, _make_client(null_result=True))

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "1",
        "--title",
        "Broken",
        "--type",
        "text",
    )

    assert result.exit_code == 1
    assert result.stdout.strip() == "", "stdout must be empty on null payload error"
    assert "failed" in result.stderr.lower() or "no data" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Optional flags: --column-id and --description are passed through
# ---------------------------------------------------------------------------


def test_optional_flags_forwarded_to_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """--column-id and --description are included in variables when supplied."""
    client = _use(
        monkeypatch,
        _make_client(col_id="my_custom_id", title="Custom", col_type="numbers"),
    )

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "2",
        "--title",
        "Custom",
        "--type",
        "numbers",
        "--column-id",
        "my_custom_id",
        "--description",
        "A description",
    )

    assert result.exit_code == 0, result.output
    assert len(client.mutations) == 1
    _mutation_str, variables = client.mutations[0]
    assert variables is not None
    assert variables.get("columnId") == "my_custom_id"
    assert variables.get("description") == "A description"


# ---------------------------------------------------------------------------
# Type is lower-cased before the API call (normalisation)
# ---------------------------------------------------------------------------


def test_type_is_lower_cased(monkeypatch: pytest.MonkeyPatch) -> None:
    """Column type is normalized to lower-case before being sent to the API."""
    client = _use(monkeypatch, _make_client(col_type="date"))

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "3",
        "--title",
        "Due Date",
        "--type",
        "DATE",  # upper-case input
    )

    assert result.exit_code == 0, result.output
    _mutation_str, variables = client.mutations[0]
    assert variables is not None
    assert variables["columnType"] == "date"


# ---------------------------------------------------------------------------
# Fix 4 (code-review nit): no --labels on a labelled type → _build_defaults
# returns None; no defaults variable in the mutation call.
# ---------------------------------------------------------------------------


def test_status_without_labels_sends_no_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix 4: creating a status column WITHOUT --labels sends no defaults variable."""
    client = _use(
        monkeypatch,
        _make_client(col_id="color_nolabels", title="State", col_type="status"),
    )

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "5",
        "--title",
        "State",
        "--type",
        "status",
        # intentionally NO --labels flag
    )

    assert result.exit_code == 0, result.output
    assert len(client.mutations) == 1
    _mutation_str, variables = client.mutations[0]
    assert variables is not None
    assert variables["columnType"] == "status"
    # _build_defaults returns None when no labels are passed → key must be absent.
    assert (
        "defaults" not in variables
    ), "status column with no labels must not include 'defaults' in the mutation call"


def test_dropdown_without_labels_sends_no_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix 4: creating a dropdown column WITHOUT --labels sends no defaults variable."""
    client = _use(
        monkeypatch,
        _make_client(col_id="dropdown_nolabels", title="Category", col_type="dropdown"),
    )

    result = _invoke(
        "columns",
        "create",
        "--board-id",
        "6",
        "--title",
        "Category",
        "--type",
        "dropdown",
        # intentionally NO --labels flag
    )

    assert result.exit_code == 0, result.output
    assert len(client.mutations) == 1
    _mutation_str, variables = client.mutations[0]
    assert variables is not None
    assert variables["columnType"] == "dropdown"
    assert (
        "defaults" not in variables
    ), "dropdown column with no labels must not include 'defaults' in the mutation call"
