"""[FR-0013 #70] Unit tests for the backstop stale-artifact sweep selection.

The sweep's *selection* (which board items are stale enough to delete) is pure
logic, so it is exercised here with a faked board listing and a fixed `now` --
no API token, never skipped by the integration gate (mirrors
`test_teardown_hardening.py`). The age guard is the safety-critical property:
an item younger than the threshold (i.e. possibly a concurrently-running run's
fresh artifact) must NEVER be selected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.integration.conftest import (
    _DEFAULT_SWEEP_MAX_AGE_SECONDS,
    _parse_created_at,
    _select_stale_item_ids,
    _sweep_max_age_seconds,
)

_NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)


def _item(item_id: str, name: str, *, age_seconds: float | None) -> dict:
    created = None if age_seconds is None else (_NOW - timedelta(seconds=age_seconds)).isoformat()
    return {"id": item_id, "name": name, "created_at": created}


def test_selects_old_prefixed_items_only() -> None:
    items = [
        _item("1", "it-old-1", age_seconds=7200),  # it-, old      -> select
        _item("2", "it-old-2", age_seconds=3600),  # it-, exactly threshold -> select
        _item("3", "it-fresh", age_seconds=60),  # it-, fresh     -> keep (live run!)
        _item("4", "real-work-item", age_seconds=99999),  # not it-  -> keep
    ]
    stale = _select_stale_item_ids(items, now=_NOW, max_age_seconds=3600)
    assert stale == ["1", "2"]


def test_fresh_prefixed_item_is_never_selected() -> None:
    # The concurrency-safety guarantee: a just-created it-* item (a live run's
    # artifact) is younger than the threshold and must be left alone.
    items = [_item("live", "it-99999-abcdef-item-1", age_seconds=5)]
    assert _select_stale_item_ids(items, now=_NOW, max_age_seconds=3600) == []


def test_unparseable_or_missing_created_at_is_not_selected() -> None:
    items = [
        _item("a", "it-no-date", age_seconds=None),  # created_at is None
        {"id": "b", "name": "it-garbage-date", "created_at": "not-a-date"},
        {"id": "c", "name": "it-no-field"},  # created_at key absent entirely
    ]
    assert _select_stale_item_ids(items, now=_NOW, max_age_seconds=1) == []


def test_custom_prefix_is_respected() -> None:
    items = [
        _item("1", "it-old", age_seconds=7200),
        _item("2", "other-old", age_seconds=7200),
    ]
    assert _select_stale_item_ids(items, now=_NOW, max_age_seconds=1, prefix="other-") == ["2"]


def test_parse_created_at_handles_z_suffix_offset_and_naive() -> None:
    z = _parse_created_at("2026-07-19T05:23:00Z")
    assert z is not None and z.tzinfo is not None and z.hour == 5

    offset = _parse_created_at("2026-07-19T05:23:00+02:00")
    assert offset is not None and offset.astimezone(UTC).hour == 3

    naive = _parse_created_at("2026-07-19T05:23:00")  # assumed UTC
    assert naive is not None and naive.tzinfo == UTC


@pytest.mark.parametrize("bad", [None, "", "   ", "nonsense", 12345])
def test_parse_created_at_returns_none_for_bad_input(bad: object) -> None:
    assert _parse_created_at(bad) is None


def test_sweep_max_age_env_override_default_and_invalid() -> None:
    assert _sweep_max_age_seconds({}) == _DEFAULT_SWEEP_MAX_AGE_SECONDS
    assert _sweep_max_age_seconds({"MONDAY_IT_SWEEP_MAX_AGE_SECONDS": "120"}) == 120.0
    # Non-numeric / non-positive -> fall back to the safe default.
    assert _sweep_max_age_seconds({"MONDAY_IT_SWEEP_MAX_AGE_SECONDS": "oops"}) == (
        _DEFAULT_SWEEP_MAX_AGE_SECONDS
    )
    assert _sweep_max_age_seconds({"MONDAY_IT_SWEEP_MAX_AGE_SECONDS": "0"}) == (
        _DEFAULT_SWEEP_MAX_AGE_SECONDS
    )
