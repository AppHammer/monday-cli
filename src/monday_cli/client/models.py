"""Pydantic models for Monday.com API responses."""

from typing import Any

from pydantic import BaseModel


class Board(BaseModel):
    """Board information."""

    id: str
    name: str


class Group(BaseModel):
    """Group information."""

    id: str
    title: str


class ColumnValue(BaseModel):
    """Column value information."""

    id: str
    text: str | None = None
    value: str | None = None
    type: str | None = None


class Asset(BaseModel):
    """Asset (file) information."""

    id: str
    name: str
    url: str
    file_extension: str | None = None
    file_size: int | None = None
    created_at: str | None = None


class Update(BaseModel):
    """Update information."""

    id: str
    body: str
    created_at: str
    creator_id: str | None = None
    assets: list[Asset] | None = None


class Subitem(BaseModel):
    """Subitem information."""

    id: str
    name: str
    column_values: list[ColumnValue] | None = None


class Item(BaseModel):
    """Item information."""

    id: str
    name: str
    state: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    creator_id: str | None = None
    board: Board | None = None
    group: Group | None = None
    column_values: list[ColumnValue] | None = None
    assets: list[Asset] | None = None
    updates: list[Update] | None = None
    subitems: list[Subitem] | None = None


class Complexity(BaseModel):
    """API complexity information."""

    before: int | None = None
    after: int | None = None
    query: int | None = None
    reset_in_x_seconds: int | None = None


class GraphQLResponse(BaseModel):
    """GraphQL API response."""

    data: dict[str, Any] | None = None
    errors: list[dict[str, Any]] | None = None
    complexity: Complexity | None = None
    account_id: int | None = None
