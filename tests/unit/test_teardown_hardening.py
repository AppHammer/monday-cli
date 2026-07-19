"""[qa-fix] Meta-tests for `_swallow_not_found`'s hardened teardown (QA Bug 2).

`_swallow_not_found` used to run a delete with `expect_error=True` and
unconditionally discard the result, so a transient API blip (rate limit /
network hiccup) was swallowed identically to "already gone" -- with no
retry -- and a real teardown failure could leak an artifact on the shared
TEST board silently. These tests exercise the retry/backoff/warn logic
directly with a monkeypatched `run_cli`, so they run fast and make ZERO live
API calls.

Deliberately a `tests/unit` module (not `tests/integration`) even though it
imports `tests.integration.conftest` for the function under test: it needs no
`MONDAY_API_TOKEN` and must NOT be skipped by the integration suite's
token-gated, secret-only CI job -- these are pure logic tests and belong in
every `pytest tests/unit` run.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from tests.integration import conftest as integration_conftest


def _patch_run_cli(monkeypatch: pytest.MonkeyPatch, *effects: Any) -> list[int]:
    """Monkeypatch `conftest.run_cli` to return/raise `effects` in sequence.

    Returns a list whose single element is mutated to the call count, so
    tests can assert exactly how many attempts were made.
    """
    calls = [0]
    remaining = list(effects)

    def _fake_run_cli(*args: str, **kwargs: Any) -> Any:
        calls[0] += 1
        effect = remaining.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return effect

    monkeypatch.setattr(integration_conftest, "run_cli", _fake_run_cli)
    return calls


@contextmanager
def _assert_no_warnings() -> Iterator[None]:
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        yield
    assert not records, f"unexpected warnings: {[str(r.message) for r in records]}"


def test_genuinely_not_found_is_swallowed_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_run_cli(monkeypatch, "Item 123 not found")

    with _assert_no_warnings():
        integration_conftest._swallow_not_found("items", "delete", "--item-id", "123", "--force")

    assert calls[0] == 1


def test_successful_delete_json_response_is_accepted_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_run_cli(monkeypatch, {"item_id": "123", "deleted": True})

    with _assert_no_warnings():
        integration_conftest._swallow_not_found("items", "delete", "--item-id", "123", "--force")

    assert calls[0] == 1


def test_transient_failure_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient error text (NOT "not found") must be retried, not swallowed
    on the first attempt -- this is the exact gap QA Bug 2 identified."""
    calls = _patch_run_cli(
        monkeypatch,
        "Error: rate limit exceeded",
        "Error: rate limit exceeded",
        {"item_id": "123", "deleted": True},
    )

    with _assert_no_warnings():
        integration_conftest._swallow_not_found(
            "items", "delete", "--item-id", "123", "--force", backoff_seconds=0.0
        )

    assert calls[0] == 3


def test_persistent_failure_warns_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the artifact still can't be confirmed deleted after every retry, the
    teardown must surface a warning -- never raise (that would abort sibling
    teardowns) and never silently vanish (that's the leak QA Bug 2 found)."""
    calls = _patch_run_cli(
        monkeypatch,
        "Error: internal server error",
        "Error: internal server error",
        "Error: internal server error",
    )

    with pytest.warns(UserWarning, match="could not confirm deletion"):
        integration_conftest._swallow_not_found(
            "items",
            "delete",
            "--item-id",
            "123",
            "--force",
            max_attempts=3,
            backoff_seconds=0.0,
        )

    assert calls[0] == 3


def test_teardown_never_raises_even_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised exception from `run_cli` itself must still end in a warning,
    never propagate -- teardown must not abort sibling fixture teardowns."""
    calls = _patch_run_cli(monkeypatch, RuntimeError("boom"), RuntimeError("boom"))

    with pytest.warns(UserWarning, match="could not confirm deletion"):
        integration_conftest._swallow_not_found(
            "items",
            "delete",
            "--item-id",
            "123",
            "--force",
            max_attempts=2,
            backoff_seconds=0.0,
        )

    assert calls[0] == 2


# --- FR-0013 #70: post-delete absence confirmation ---------------------------


def test_confirm_absent_true_accepts_delete_without_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful delete whose confirmation says "gone" must not warn."""
    _patch_run_cli(monkeypatch, {"group_id": "g1", "deleted": False})
    confirm_calls = [0]

    def _confirm() -> bool:
        confirm_calls[0] += 1
        return True

    with _assert_no_warnings():
        integration_conftest._swallow_not_found(
            "groups", "delete", "--title", "x", "--confirm", confirm_absent=_confirm
        )

    assert confirm_calls[0] == 1  # confirmation actually ran


def test_confirm_absent_false_warns_that_artifact_may_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`groups delete` reports deleted:false even on success, so a JSON response
    alone can't prove absence; if the follow-up confirmation still sees the
    artifact, teardown must surface a leak warning (never trust blindly)."""
    _patch_run_cli(monkeypatch, {"group_id": "g1", "deleted": False})

    with pytest.warns(UserWarning, match="could not confirm its absence"):
        integration_conftest._swallow_not_found(
            "groups", "delete", "--title", "x", "--confirm", confirm_absent=lambda: False
        )


def test_confirm_absent_error_warns_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmation that itself errors must degrade to a warning, not abort
    the surrounding teardown."""
    _patch_run_cli(monkeypatch, {"group_id": "g1", "deleted": False})

    def _boom() -> bool:
        raise RuntimeError("list failed")

    with pytest.warns(UserWarning, match="could not verify deletion"):
        integration_conftest._swallow_not_found(
            "groups", "delete", "--title", "x", "--confirm", confirm_absent=_boom
        )


def test_confirm_absent_skipped_when_artifact_already_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the delete path shows "not found" (already gone), the confirmation
    is irrelevant and must NOT run -- it would spend an extra API call for
    nothing."""
    _patch_run_cli(monkeypatch, "Group x not found")
    confirm_calls = [0]

    def _confirm() -> bool:
        confirm_calls[0] += 1
        return True

    with _assert_no_warnings():
        integration_conftest._swallow_not_found(
            "groups", "delete", "--title", "x", "--confirm", confirm_absent=_confirm
        )

    assert confirm_calls[0] == 0
