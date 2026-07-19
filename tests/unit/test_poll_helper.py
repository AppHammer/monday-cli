"""[FR-0013 #69] Unit tests for the consolidated bounded-poll read helper.

`run_cli_until` (and its `run_cli_until_item_present` convenience) is the single
CI-tuned poll every read-after-mutate integration assertion now shares, replacing
the three near-identical private copies that used to live in `test_items.py`,
`test_items_move.py` and `test_items_status.py`.

Its retry / give-up / env-tuning logic is pure, so it is exercised here with a
faked `run_cli` and no real sleeps -- these are `tests/unit` (no API token, never
skipped by the integration gate), mirroring `test_teardown_hardening.py`.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration import helpers


def _patch_run_cli(monkeypatch: pytest.MonkeyPatch, results: list[Any]) -> list[int]:
    """Fake `helpers.run_cli` to yield `results` in order; return a call counter.

    Also stubs `helpers.time.sleep` so the bounded backoff never actually waits.
    The counter is a one-element list so callers can assert the exact attempt
    count after the poll returns.
    """
    calls = [0]

    def _fake_run_cli(*args: str, **kwargs: Any) -> Any:
        idx = calls[0]
        calls[0] += 1
        # Clamp to the last result so an over-long poll keeps seeing it.
        return results[min(idx, len(results) - 1)]

    monkeypatch.setattr(helpers, "run_cli", _fake_run_cli)
    monkeypatch.setattr(helpers.time, "sleep", lambda _seconds: None)
    return calls


def test_returns_as_soon_as_predicate_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    # Flips true on the 3rd read; polling must stop there, not run all 6.
    calls = _patch_run_cli(monkeypatch, [{"ok": False}, {"ok": False}, {"ok": True}])

    result = helpers.run_cli_until(lambda d: d["ok"], "items", "list")

    assert result == {"ok": True}
    assert calls[0] == 3


def test_gives_up_after_bounded_attempts_and_returns_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Predicate never holds -> exactly `attempts` reads, then the last result is
    # returned so the caller's own assertion produces a meaningful message.
    calls = _patch_run_cli(monkeypatch, [{"ok": False}])

    result = helpers.run_cli_until(lambda d: d["ok"], "items", "list", attempts=4, delay=0)

    assert result == {"ok": False}
    assert calls[0] == 4


def test_single_attempt_never_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(helpers, "run_cli", lambda *a, **k: {"ok": False})
    monkeypatch.setattr(helpers.time, "sleep", lambda s: slept.append(s))

    helpers.run_cli_until(lambda d: d["ok"], "items", "list", attempts=1)

    assert slept == []  # no backoff before a give-up on the final attempt


def test_attempts_and_delay_resolve_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONDAY_IT_POLL_ATTEMPTS", "9")
    monkeypatch.setenv("MONDAY_IT_POLL_DELAY", "0.25")
    assert helpers.poll_attempts() == 9
    assert helpers.poll_delay() == 0.25


def test_env_defaults_used_when_unset_or_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONDAY_IT_POLL_ATTEMPTS", raising=False)
    monkeypatch.delenv("MONDAY_IT_POLL_DELAY", raising=False)
    assert helpers.poll_attempts() == helpers._DEFAULT_POLL_ATTEMPTS
    assert helpers.poll_delay() == helpers._DEFAULT_POLL_DELAY

    # Non-numeric / non-positive values fall back to the defaults rather than
    # crashing a poll mid-teardown.
    monkeypatch.setenv("MONDAY_IT_POLL_ATTEMPTS", "not-a-number")
    monkeypatch.setenv("MONDAY_IT_POLL_DELAY", "-1")
    assert helpers.poll_attempts() == helpers._DEFAULT_POLL_ATTEMPTS
    assert helpers.poll_delay() == helpers._DEFAULT_POLL_DELAY


def test_env_attempts_drives_actual_poll_count(monkeypatch: pytest.MonkeyPatch) -> None:
    # With attempts unset in the call, the env value must govern the loop.
    calls = _patch_run_cli(monkeypatch, [{"ok": False}])
    monkeypatch.setenv("MONDAY_IT_POLL_ATTEMPTS", "2")
    monkeypatch.setenv("MONDAY_IT_POLL_DELAY", "0")

    helpers.run_cli_until(lambda d: d["ok"], "items", "list")

    assert calls[0] == 2


def test_item_present_convenience_matches_on_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_run_cli(
        monkeypatch,
        [
            {"items": [{"id": "111"}]},
            {"items": [{"id": "111"}, {"id": "222"}]},
        ],
    )

    result = helpers.run_cli_until_item_present("222", "items", "list", delay=0)

    assert {str(i["id"]) for i in result["items"]} == {"111", "222"}
    assert calls[0] == 2


def test_item_present_convenience_tolerates_missing_items_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty/late payload must not raise -- it just fails the predicate and
    # polls again (this is the exact eventual-consistency case in CI).
    calls = _patch_run_cli(monkeypatch, [{}])

    result = helpers.run_cli_until_item_present("999", "items", "list", attempts=3, delay=0)

    assert result == {}
    assert calls[0] == 3
