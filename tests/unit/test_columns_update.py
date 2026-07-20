"""Unit tests for `monday columns update` (issue #87).

Exercises the update_column command and _apply_label_changes helper via
CliRunner + FakeClient without any network traffic. Covers:

  - title rename (CHANGE_COLUMN_TITLE called with correct variables)
  - add label to status column (create_labels_if_missing path)
  - rename-label parse/validation/API-limitation error
  - no flags → teaching error (AC5)
  - labels on a text column → teaching error (AC4)
  - unknown column id → teaching tip error
  - rename-label bad format "noequals" → exit 1
  - ✓ on stderr + clean JSON stdout (AC6)
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from monday_cli.cli import app
from tests.unit.conftest import FakeClient, status_column

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_BOARD_ID = "123"
_STATUS_COL_ID = "status_abc"
_STATUS_COL_TITLE = "Priority"
_TEXT_COL_ID = "text_xyz"
_TEXT_COL_TITLE = "Notes"

_STATUS_COL = status_column(
    _STATUS_COL_ID, _STATUS_COL_TITLE, {"0": "Done", "1": "Working on it", "2": "Stuck"}
)
_TEXT_COL = {
    "id": _TEXT_COL_ID,
    "title": _TEXT_COL_TITLE,
    "type": "text",
    "settings_str": "{}",
}


def _make_client(**kwargs: object) -> FakeClient:
    """Return a FakeClient with both test columns loaded."""
    return FakeClient(
        columns=[_STATUS_COL, _TEXT_COL],
        **kwargs,  # type: ignore[arg-type]
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr("monday_cli.commands.columns.get_client", lambda: client)


# ---------------------------------------------------------------------------
# AC5 — no flags → teaching error, no mutation
# ---------------------------------------------------------------------------


def test_no_flags_exits_1_with_teaching_error(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC5: invoking update with no change flags is rejected before any API call."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        ["columns", "update", "--board-id", _BOARD_ID, "--column-id", _STATUS_COL_ID],
    )

    assert result.exit_code == 1
    # No API call should have been made.
    assert len(client.queries) == 0
    assert len(client.mutations) == 0
    # Teaching error must be on stderr.
    assert "nothing to update" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Unknown column id → teaching tip
# ---------------------------------------------------------------------------


def test_unknown_column_id_exits_1_with_tip(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown column id surfaces a teaching error with a columns list tip."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            "does_not_exist",
            "--title",
            "New Title",
        ],
    )

    assert result.exit_code == 1
    assert len(client.mutations) == 0
    # Teaching tip must reference columns list.
    assert "columns list" in result.stderr


# ---------------------------------------------------------------------------
# AC4 — label flags on a non-label column → teaching error
# ---------------------------------------------------------------------------


def test_add_label_on_text_column_exits_1(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4: --add-label on a text column exits 1 before any label mutation."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _TEXT_COL_ID,
            "--add-label",
            "NewLabel",
        ],
    )

    assert result.exit_code == 1
    # No label mutation should have been issued.
    label_mutations = [m for m in client.mutations if "create_labels_if_missing" in m[0]]
    assert len(label_mutations) == 0
    assert "status" in result.stderr.lower() or "dropdown" in result.stderr.lower()


def test_rename_label_on_text_column_exits_1(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4: --rename-label on a text column exits 1 before any label mutation."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _TEXT_COL_ID,
            "--rename-label",
            "Old=New",
        ],
    )

    assert result.exit_code == 1
    label_mutations = [m for m in client.mutations if "create_labels_if_missing" in m[0]]
    assert len(label_mutations) == 0


# ---------------------------------------------------------------------------
# rename-label bad format
# ---------------------------------------------------------------------------


def test_rename_label_bad_format_exits_1(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--rename-label 'noequals' (no '=') exits 1 with a format teaching error."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--rename-label",
            "noequals",
        ],
    )

    assert result.exit_code == 1
    assert len(client.mutations) == 0
    # Error message must mention the expected format.
    assert "old=new" in result.stderr.lower() or "format" in result.stderr.lower()


# ---------------------------------------------------------------------------
# rename-label unknown old label → teaching error listing current labels
# ---------------------------------------------------------------------------


def test_rename_label_unknown_old_exits_1(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--rename-label 'UnknownOld=New' exits 1 with a list of current labels."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--rename-label",
            "UnknownOld=New",
        ],
    )

    assert result.exit_code == 1
    assert len(client.mutations) == 0
    # Must mention that the label was not found.
    assert "not found" in result.stderr.lower()
    # Must list current labels (or at least one of them) to help the user.
    # Current labels are: Done, Working on it, Stuck
    assert any(
        label in result.stderr for label in ["Done", "Working on it", "Stuck"]
    ), f"Expected current labels in stderr: {result.stderr!r}"


# ---------------------------------------------------------------------------
# rename-label valid format → API limitation error (clear teaching message)
# ---------------------------------------------------------------------------


def test_rename_label_surfaces_api_limitation_error(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid rename-label invocation exits 1 with a clear API-limitation message.

    The Monday.com public API does not expose an index-preserving label rename.
    The command resolves the old label (parse + validate), then raises a teaching
    MondayAPIError rather than silently no-op.
    """
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--rename-label",
            "Done=Completed",
        ],
    )

    assert result.exit_code == 1
    assert len(client.mutations) == 0
    # The error must clearly mention the API limitation so the user is not confused.
    stderr_lower = result.stderr.lower()
    assert "rename" in stderr_lower or "api" in stderr_lower


# ---------------------------------------------------------------------------
# AC1 — title rename → CHANGE_COLUMN_TITLE called correctly
# ---------------------------------------------------------------------------


def test_rename_title_calls_change_column_title(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: --title triggers CHANGE_COLUMN_TITLE with the correct variables."""
    client = _make_client()
    _patch_client(monkeypatch, client)
    new_title = "Updated Priority"

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--title",
            new_title,
        ],
    )

    assert result.exit_code == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # Exactly one mutation: CHANGE_COLUMN_TITLE.
    assert len(client.mutations) == 1
    mutation_str, mutation_vars = client.mutations[0]
    assert "change_column_title" in mutation_str
    assert mutation_vars == {
        "boardId": _BOARD_ID,
        "columnId": _STATUS_COL_ID,
        "title": new_title,
    }

    # stdout must be clean JSON reporting the new title.
    data = json.loads(result.stdout.strip())
    assert data["title"] == new_title
    assert data["column_id"] == _STATUS_COL_ID
    assert data["board_id"] == _BOARD_ID


# ---------------------------------------------------------------------------
# AC6 — ✓ on stderr, clean JSON stdout
# ---------------------------------------------------------------------------


def test_success_checkmark_on_stderr_clean_json_stdout(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC6: ✓ message appears on stderr; stdout is a single clean JSON document."""
    client = _make_client()
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--title",
            "NewName",
        ],
    )

    assert result.exit_code == 0
    assert "✓" in result.stderr
    # stdout must be ONLY the JSON payload (FR-0008 contract).
    data = json.loads(result.stdout.strip())
    assert isinstance(data, dict)
    assert "column_id" in data
    assert "board_id" in data


# ---------------------------------------------------------------------------
# AC2 — add label to status column
# ---------------------------------------------------------------------------


def test_add_label_to_status_column(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: --add-label fetches a board item and calls create_labels_if_missing mutation."""
    client = _make_client(first_item_id="item_42")
    _patch_client(monkeypatch, client)
    new_label = "Blocked"

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--add-label",
            new_label,
        ],
    )

    assert result.exit_code == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    # One label-add mutation should have been called.
    label_mutations = [
        (m_str, m_vars) for m_str, m_vars in client.mutations if "create_labels_if_missing" in m_str
    ]
    assert (
        len(label_mutations) == 1
    ), f"Expected 1 create_labels_if_missing mutation, got {len(label_mutations)}"
    _m_str, m_vars = label_mutations[0]
    assert m_vars is not None
    assert m_vars["boardId"] == _BOARD_ID
    assert m_vars["columnId"] == _STATUS_COL_ID
    assert m_vars["itemId"] == "item_42"
    assert json.loads(m_vars["value"]) == {"label": new_label}

    # JSON output must reflect the added label.
    data = json.loads(result.stdout.strip())
    assert "labels_changed" in data
    assert new_label in data["labels_changed"]["labels_added"]


def test_add_multiple_labels_calls_mutation_per_label(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple --add-label flags each trigger their own mutation call."""
    client = _make_client(first_item_id="item_99")
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--add-label",
            "Urgent",
            "--add-label",
            "Deferred",
        ],
    )

    assert result.exit_code == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    label_mutations = [m for m in client.mutations if "create_labels_if_missing" in m[0]]
    assert len(label_mutations) == 2


def test_add_label_board_with_no_items_exits_1(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--add-label on a board with no items exits 1 with a teaching error."""
    # first_item_id=None simulates a board that has no items.
    client = _make_client(first_item_id=None)
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--add-label",
            "NewLabel",
        ],
    )

    assert result.exit_code == 1
    label_mutations = [m for m in client.mutations if "create_labels_if_missing" in m[0]]
    assert len(label_mutations) == 0
    assert "no items" in result.stderr.lower() or "item" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Combined title + add-label in one invocation
# ---------------------------------------------------------------------------


def test_title_and_add_label_together(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """--title and --add-label can be combined; both mutations are called."""
    client = _make_client(first_item_id="item_55")
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--title",
            "State",
            "--add-label",
            "Blocked",
        ],
    )

    assert result.exit_code == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    title_mutations = [m for m in client.mutations if "change_column_title" in m[0]]
    label_mutations = [m for m in client.mutations if "create_labels_if_missing" in m[0]]
    assert len(title_mutations) == 1
    assert len(label_mutations) == 1

    data = json.loads(result.stdout.strip())
    assert data["title"] == "State"
    assert "labels_changed" in data


# ---------------------------------------------------------------------------
# Fix 1 (code-review suggestion): --add-label restore of the item's prior value
# ---------------------------------------------------------------------------


def test_add_label_restores_prior_item_cell_value(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix 1: after --add-label writes to an item's cell, a restore mutation is called.

    The CHANGE_COLUMN_VALUE_CREATE_LABELS write has a side-effect of assigning
    the new label to the target item's cell. After writing, the command must
    call CHANGE_COLUMN_VALUE with the cell's prior value to undo that side-effect.
    """
    prior_value = json.dumps({"index": 0, "post_id": None})
    client = _make_client(
        first_item_id="item_77",
        first_item_column_values=[{"id": _STATUS_COL_ID, "value": prior_value}],
    )
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--add-label",
            "Blocked",
        ],
    )

    assert result.exit_code == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    # One label-add mutation followed by one restore mutation (CHANGE_COLUMN_VALUE).
    label_mutations = [(s, v) for s, v in client.mutations if "create_labels_if_missing" in s]
    restore_mutations = [
        (s, v)
        for s, v in client.mutations
        if "change_column_value" in s and "create_labels_if_missing" not in s
    ]
    assert len(label_mutations) == 1, "expected exactly one label-add mutation"
    assert len(restore_mutations) >= 1, "expected at least one restore mutation after add-label"

    # Restore must write the prior value back to the same item+column.
    _restore_str, restore_vars = restore_mutations[0]
    assert restore_vars is not None
    assert restore_vars["itemId"] == "item_77"
    assert restore_vars["columnId"] == _STATUS_COL_ID
    assert restore_vars["value"] == prior_value


def test_add_label_with_empty_prior_value_restores_null(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix 1: when the item's cell has no prior value (None), restore writes 'null'."""
    # No column_values entry for this column → prior_value is None → restore sends "null".
    client = _make_client(
        first_item_id="item_88",
        first_item_column_values=[],  # column not in column_values — cell is empty
    )
    _patch_client(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "columns",
            "update",
            "--board-id",
            _BOARD_ID,
            "--column-id",
            _STATUS_COL_ID,
            "--add-label",
            "NewTag",
        ],
    )

    assert result.exit_code == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    restore_mutations = [
        (s, v)
        for s, v in client.mutations
        if "change_column_value" in s and "create_labels_if_missing" not in s
    ]
    assert len(restore_mutations) >= 1, "expected a restore mutation even when prior value is None"
    _restore_str, restore_vars = restore_mutations[0]
    assert restore_vars is not None
    # When prior_value is None we pass "null" as the restore value.
    assert restore_vars["value"] == "null"
