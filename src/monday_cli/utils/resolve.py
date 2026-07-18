"""Shared board group / status-column resolution helpers for item commands.

These helpers are the single source of truth for FR-0009's "human-readable
inputs resolved internally" behaviour: a caller passes a group *title or id*
(or a status column title / status label) and gets back the concrete board
object, so every ``items`` subcommand resolves ``-g`` and ``--status`` the
same way. The helpers are deliberately pure (no Typer / no I/O beyond the
injected GraphQL client) so they are directly unit-testable with a mocked
client, and so callers own the teaching-error UX.
"""

from __future__ import annotations

import json
from typing import Any

from monday_cli.client.queries import GET_BOARD_COLUMNS, GET_BOARD_GROUPS


def fetch_board_groups(client: Any, board_id: str) -> list[dict[str, Any]]:
    """Return the board's groups (``[{id, title, color, position}, ...]``)."""
    result = client.execute_query(GET_BOARD_GROUPS, {"boardIds": [str(board_id)]})
    boards = result.get("boards", [])
    if not boards:
        return []
    return boards[0].get("groups", []) or []


def resolve_group_ref(
    client: Any, board_id: str, value: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Resolve a group *title or id* to a concrete board group (FR-0009 B1).

    Deterministic, documented precedence:

    1. ``value`` starts with ``group_`` **or** exactly equals a board group id
       (covers the default ``topics`` group, which has no ``group_`` prefix)
       -> treat as an **id** and look it up by id.
    2. else exact case-insensitive **title** match -> that group.
    3. else -> ``None`` (the caller raises a teaching error).

    Returns ``(resolved_group_or_None, all_groups)`` so the caller can both
    filter by the resolved id and build a teaching error that lists every
    available group as ``id + title``.
    """
    groups = fetch_board_groups(client, board_id)
    group_ids = {g.get("id") for g in groups}

    # Rule 1: id path (prefix OR exact id membership).
    if value.startswith("group_") or value in group_ids:
        for group in groups:
            if group.get("id") == value:
                return group, groups
        # Looked like an id but matched no group on this board -> unknown.
        return None, groups

    # Rule 2: exact case-insensitive title match.
    value_lower = value.lower()
    for group in groups:
        if (group.get("title") or "").lower() == value_lower:
            return group, groups

    # Rule 3: unknown.
    return None, groups


def format_groups_for_error(groups: list[dict[str, Any]]) -> str:
    """Render available groups as ``'Title' (id)`` for a teaching error."""
    if not groups:
        return "(none)"
    return ", ".join(f"'{g.get('title')}' ({g.get('id')})" for g in groups)


def get_status_columns(client: Any, board_id: str) -> list[dict[str, Any]]:
    """Return the board's status-type columns.

    Each entry is ``{"id", "title", "labels": {index: label}}`` where
    ``labels`` is parsed from the column's ``settings_str`` exactly the way
    ``monday statuses list`` parses it, so a status filter's "valid labels"
    teaching list is identical to that command's output.
    """
    result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [str(board_id)]})
    boards = result.get("boards", [])
    if not boards:
        return []
    columns = boards[0].get("columns", []) or []

    status_columns: list[dict[str, Any]] = []
    for col in columns:
        if col.get("type") == "status" and col.get("settings_str"):
            try:
                settings = json.loads(col["settings_str"])
                labels = settings.get("labels", {})
            except (json.JSONDecodeError, AttributeError, ValueError):
                continue
            status_columns.append({"id": col["id"], "title": col["title"], "labels": labels})
    return status_columns
