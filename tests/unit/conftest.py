"""Shared fixtures for in-process unit tests of the `items` command surface.

`FakeClient` stands in for `MondayGraphQLClient`: it dispatches on distinctive
tokens in the GraphQL operation string and returns canned data, so command
logic (group/status resolution, filtering, teaching errors, the move command)
can be exercised with `typer.testing.CliRunner` and zero network traffic.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

# Sentinel used so FakeClient can distinguish "explicitly None" from "not provided".
_UNSET: Any = object()

_DEFAULT_CREATE_COLUMN_RESULT: dict[str, Any] = {
    "id": "text_abc123",
    "title": "My Column",
    "type": "text",
    "description": None,
    "settings_str": "{}",
}


class FakeClient:
    """Minimal fake of ``MondayGraphQLClient`` for command-level unit tests."""

    def __init__(
        self,
        *,
        board_items: list[dict[str, Any]] | None = None,
        board_name: str = "Test Board",
        initial_cursor: str | None = None,
        next_pages: list[tuple[list[dict[str, Any]], str | None]] | None = None,
        groups: list[dict[str, Any]] | None = None,
        columns: list[dict[str, Any]] | None = None,
        item_by_id: dict[str, Any] | None = None,
        move_result: Any = None,
        create_result: dict[str, Any] | None = None,
        create_column_result: dict[str, Any] | None = _UNSET,
    ) -> None:
        self.board_items = board_items or []
        self.board_name = board_name
        self.initial_cursor = initial_cursor
        self.next_pages = list(next_pages or [])
        self.groups = groups or []
        self.columns = columns or []
        self.item_by_id = item_by_id
        self.move_result = move_result
        self.create_result = create_result or {"id": "1", "name": "x", "created_at": "t"}
        # Allow None to be passed explicitly (null API payload tests) while
        # still defaulting to a sensible column dict when omitted.
        self.create_column_result: dict[str, Any] | None = (
            _DEFAULT_CREATE_COLUMN_RESULT
            if create_column_result is _UNSET
            else create_column_result
        )
        self.queries: list[tuple[str, dict[str, Any] | None]] = []
        self.mutations: list[tuple[str, dict[str, Any] | None]] = []

    def execute_query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.queries.append((query, variables))
        if "next_items_page" in query:
            items, cursor = self.next_pages.pop(0)
            return {"next_items_page": {"cursor": cursor, "items": items}}
        if "items_page" in query:
            board_id = (variables or {}).get("boardIds", ["1"])[0]
            return {
                "boards": [
                    {
                        "id": board_id,
                        "name": self.board_name,
                        "items_page": {"cursor": self.initial_cursor, "items": self.board_items},
                    }
                ]
            }
        if "groups {" in query:
            return {"boards": [{"id": "1", "name": self.board_name, "groups": self.groups}]}
        if "columns {" in query:
            return {"boards": [{"id": "1", "name": self.board_name, "columns": self.columns}]}
        # GET_ITEM_BY_ID (has a `subitems {` selection).
        if "subitems {" in query:
            return {"items": [self.item_by_id] if self.item_by_id else []}
        raise AssertionError(f"Unexpected query dispatched:\n{query[:120]}")

    def execute_mutation(
        self, mutation: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.mutations.append((mutation, variables))
        if "move_item_to_group" in mutation:
            if isinstance(self.move_result, Exception):
                raise self.move_result
            return {"move_item_to_group": self.move_result}
        if "create_item" in mutation:
            return {"create_item": self.create_result}
        if "create_column" in mutation:
            return {"create_column": self.create_column_result}
        raise AssertionError(f"Unexpected mutation dispatched:\n{mutation[:120]}")


def status_column(col_id: str, title: str, labels: dict[str, str]) -> dict[str, Any]:
    """Build a status-type board column with a ``settings_str`` labels blob."""
    return {
        "id": col_id,
        "title": title,
        "type": "status",
        "settings_str": json.dumps({"labels": labels}),
    }


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def use_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch ``items.get_client`` to return the supplied FakeClient."""

    def _use(client: FakeClient) -> FakeClient:
        monkeypatch.setattr("monday_cli.commands.items.get_client", lambda: client)
        return client

    return _use
