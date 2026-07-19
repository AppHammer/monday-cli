"""FR-0005 regression integration tests — live API, TEST board 18422673411 only.

These tests reproduce each defect class from FR-0005 and verify the fixes:

  AC-1  (US-0005-01): >200-block / ~40KB put either succeeds OR fails atomically
                       leaving the cell readable + writable, no orphaned doc object.
  AC-2  (US-0005-02): Re-put of a >100-block doc is an exact idempotent replacement,
                       no growth, no tail residue, correct block order.
  AC-3  (US-0005-03): Append-retry idempotency — same content appended twice appears
                       exactly once (dedup by SHA-256 sentinel).
  AC-4  (US-0005-05): `docs clear` recovers a doc column with no web-UI step;
                       a subsequent `docs put` succeeds.
  AC-2b (US-0005-04): Block order is preserved — headings and ordered lists render
                       in source order after a large put.

Scope:
  - TEST board 18422673411 ONLY (conftest.py harness hard-fails on PM board).
  - Every artifact is created through `created_item` and cleaned up on teardown,
    even when the test body raises.
  - Suite skips cleanly when MONDAY_API_TOKEN is absent (forked-PR CI).

Running:
  pytest -m integration tests/integration/test_docs_fr0005.py -v
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.integration.helpers import run_cli

# ---------------------------------------------------------------------------
# Helpers (shared by this suite)
# ---------------------------------------------------------------------------


def _discover_doc_column(item_id: str) -> str | None:
    """Return the title of the first `doc`-type column on the item's board, or None."""
    result = run_cli("items", "list-columns", "--item-id", item_id)
    assert isinstance(result, dict)
    for column in result.get("columns", []):
        if column.get("type") == "doc":
            return str(column["title"])
    return None


def _assert_order(text: str, *tokens: str) -> None:
    """Assert every token appears in text in the given order.

    This is the canonical block-order guard: a corrupted or scrambled doc
    will fail here because a token will be missing or appear before its
    predecessor.
    """
    positions = []
    for token in tokens:
        idx = text.find(token)
        assert idx != -1, f"expected {token!r} in docs get output:\n{text}"
        positions.append(idx)
    assert positions == sorted(
        positions
    ), f"tokens out of order (expected sequence {tokens}) in:\n{text}"


def _get_doc_raw(item_id: str, col: str) -> str:
    """Return `docs get --raw` (markdown) output for the given item+column."""
    return run_cli(  # type: ignore[return-value]
        "docs", "get", "--item-id", item_id, "--column-name", col, "--raw", raw=True
    )


def _put_doc(item_id: str, col: str, content: str) -> dict:
    """Run docs put and return the JSON result."""
    return run_cli("docs", "put", "--item-id", item_id, "--column-name", col, "--content", content)  # type: ignore[return-value]


def _append_doc(item_id: str, col: str, content: str) -> dict:
    """Run docs append and return the JSON result."""
    return run_cli(  # type: ignore[return-value]
        "docs", "append", "--item-id", item_id, "--column-name", col, "--content", content
    )


def _clear_doc(item_id: str, col: str) -> dict:
    """Run docs clear --force and return the JSON result."""
    return run_cli("docs", "clear", "--item-id", item_id, "--column-name", col, "--force")  # type: ignore[return-value]


def _build_large_markdown(run_id: str, num_sections: int = 110) -> str:
    """Build a >100-block markdown document for size/order regression tests.

    Each section contains a heading + a paragraph, so block count ≈ 2 × num_sections.
    With num_sections=110 we get ~220 blocks (well over the ~100-block clear bug threshold).
    """
    lines = []
    for i in range(1, num_sections + 1):
        lines.append(f"## Section {i} — {run_id}")
        lines.append(
            f"This is the paragraph for section {i}. It contains enough text to be a "
            f"meaningful block. Section identifier: {run_id}-sec-{i}."
        )
        lines.append("")  # blank line = block separator
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AC-2 + AC-2b: >100-block put, re-put idempotent replace, block order
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_large_put_replace_and_block_order(created_item: Callable[..., str], run_id: str) -> None:
    """AC-2 (US-0005-02) + AC-2b (US-0005-04): large put, re-put replace, block order.

    Pre-fix behaviour: a re-put of a >100-block doc would GROW the doc (partial
    clear + full re-write). This test asserts exact replacement and correct order.
    """
    item_id = created_item("fr0005-large-put")
    col = _discover_doc_column(item_id)
    if col is None:
        pytest.skip(
            "Test board 18422673411 has no doc-type column. Add a 'Document' column "
            "to the board to enable FR-0005 regression coverage."
        )

    # --- First put: ~220-block document (110 sections × heading + paragraph) ---
    first_content = _build_large_markdown(run_id, num_sections=110)
    result1 = _put_doc(item_id, col, first_content)
    assert isinstance(result1, dict), f"docs put failed: {result1}"
    assert result1.get("doc_id"), "Expected doc_id in put result"

    raw_after_first = _get_doc_raw(item_id, col)

    # Block-order: Section 1 before Section 55 before Section 110
    _assert_order(
        raw_after_first,
        f"Section 1 — {run_id}",
        f"Section 55 — {run_id}",
        f"Section 110 — {run_id}",
    )

    # --- Re-put (different content): must REPLACE, not grow ---
    second_content = _build_large_markdown(f"{run_id}-v2", num_sections=110)
    result2 = _put_doc(item_id, col, second_content)
    assert result2.get("doc_id"), "Expected doc_id in second put result"

    raw_after_second = _get_doc_raw(item_id, col)

    # New content present in order
    _assert_order(
        raw_after_second,
        f"Section 1 — {run_id}-v2",
        f"Section 55 — {run_id}-v2",
        f"Section 110 — {run_id}-v2",
    )
    # Old content completely replaced — no tail residue.
    # Use f"{run_id}-sec-" as the canary: it appears as "{run_id}-sec-{N}" in v1
    # content but NOT in v2 content (which uses "{run_id}-v2-sec-{N}"). This avoids
    # the substring collision where "{run_id}" is a prefix of "{run_id}-v2".
    v1_canary = f"{run_id}-sec-"
    assert v1_canary not in raw_after_second, (
        f"Old tail residue found after re-put — "
        f"_delete_all_doc_blocks did not clear all blocks. "
        f"Canary '{v1_canary}' still present in doc after second put."
    )

    # --- Idempotent re-put: putting the same content twice → consistent result ---
    result3 = _put_doc(item_id, col, second_content)
    assert result3.get("doc_id")
    raw_after_third = _get_doc_raw(item_id, col)
    # Core content must still be present and ordered
    _assert_order(
        raw_after_third,
        f"Section 1 — {run_id}-v2",
        f"Section 55 — {run_id}-v2",
        f"Section 110 — {run_id}-v2",
    )
    # No stale first-put content
    assert v1_canary not in raw_after_third, (
        f"Old v1 content still present after idempotent re-put. " f"Canary '{v1_canary}' found."
    )


# ---------------------------------------------------------------------------
# AC-3: Append idempotency (US-0005-03)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_append_retry_idempotency(created_item: Callable[..., str], run_id: str) -> None:
    """AC-3 (US-0005-03): Append the same content twice; it must appear exactly once.

    Pre-fix behaviour: a retry after a lost ack appended the content a second
    time, doubling it in the doc. The fix embeds a SHA-256 sentinel and skips
    the write if the sentinel is already present.
    """
    item_id = created_item("fr0005-append-dedup")
    col = _discover_doc_column(item_id)
    if col is None:
        pytest.skip("No doc column on test board — cannot run append-retry test.")

    # Set up initial content
    base_content = f"# Base — {run_id}\n\nInitial paragraph."
    _put_doc(item_id, col, base_content)

    # Unique append content
    append_content = f"## Appended Section — {run_id}\n\nThis must appear exactly once."

    # First append (simulates original write)
    _append_doc(item_id, col, append_content)

    # Second append with same content (simulates a lost-ack retry)
    _append_doc(item_id, col, append_content)

    # Verify content appears exactly once
    raw = _get_doc_raw(item_id, col)
    count = raw.count(f"Appended Section — {run_id}")
    assert count == 1, (
        f"Appended section appears {count} times — expected 1. "
        f"Dedup sentinel not working; lost-ack retry duplicated content.\n"
        f"Doc content:\n{raw}"
    )

    # A second (different) append must still land
    second_append = f"## Second Append — {run_id}\n\nDifferent content."
    _append_doc(item_id, col, second_append)
    raw_after = _get_doc_raw(item_id, col)
    assert (
        f"Second Append — {run_id}" in raw_after
    ), "Different-content append did not land — dedup is too aggressive"


# ---------------------------------------------------------------------------
# AC-1: Cell-limit boundary / atomic-fail (US-0005-01)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_large_put_atomic_or_succeeds(created_item: Callable[..., str], run_id: str) -> None:
    """AC-1 (US-0005-01): ~200-block / ~40KB put either succeeds or fails atomically.

    The critical regression: before the fix, a CellLimitExceededException would
    leave an orphaned, unresolvable doc object — subsequent docs get/put/append
    all failed with 'Could not resolve document (object_id=...)'.

    After the fix (chunking strategy), the put should succeed. If it somehow
    still fails (e.g. the API limit changed), the column must still be
    readable and writable afterward — no orphan.
    """
    item_id = created_item("fr0005-cell-limit")
    col = _discover_doc_column(item_id)
    if col is None:
        pytest.skip("No doc column on test board — cannot run cell-limit test.")

    # Build a ~40KB / 200+ block document
    large_content = _build_large_markdown(run_id, num_sections=105)
    content_bytes = len(large_content.encode("utf-8"))

    # Attempt the large put
    outcome = run_cli(
        "docs",
        "put",
        "--item-id",
        item_id,
        "--column-name",
        col,
        "--content",
        large_content,
        expect_error=True,  # may succeed OR fail — we handle both
    )

    if isinstance(outcome, dict) and outcome.get("doc_id"):
        # Put succeeded (chunking worked) — verify content round-trips
        raw = _get_doc_raw(item_id, col)
        _assert_order(
            raw,
            f"Section 1 — {run_id}",
            f"Section 50 — {run_id}",
            f"Section 105 — {run_id}",
        )
    else:
        # Put failed — verify the column is still readable + writable (atomic-fail AC-1)
        # docs get must not raise "Could not resolve document"
        get_result = run_cli(
            "docs",
            "get",
            "--item-id",
            item_id,
            "--column-name",
            col,
            expect_error=True,
        )
        # get_result is either JSON (doc exists and readable) or an error string
        # The critical assertion: the error must NOT be the orphan error
        if isinstance(get_result, str):
            assert "Could not resolve document" not in get_result, (
                f"AC-1 FAILED: after a large-put failure, the column is in an unresolvable "
                f"orphaned state. The fix did not prevent the orphan.\n"
                f"Error: {get_result}\n"
                f"Content size: {content_bytes:,} bytes"
            )

        # A small follow-up put must succeed (column is writable)
        recovery_content = f"# Recovery — {run_id}\n\nSmall doc after failed large put."
        recovery_result = _put_doc(item_id, col, recovery_content)
        assert recovery_result.get("doc_id"), (
            f"AC-1 FAILED: after a large-put failure, a small follow-up put also failed. "
            f"Column is not writable after the large put.\n"
            f"Recovery result: {recovery_result}"
        )


# ---------------------------------------------------------------------------
# AC-4: docs clear / reset (US-0005-05)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_docs_clear_empties_healthy_doc(created_item: Callable[..., str], run_id: str) -> None:
    """AC-4 (US-0005-05): docs clear on a healthy doc empties it, column stays writable."""
    item_id = created_item("fr0005-clear-healthy")
    col = _discover_doc_column(item_id)
    if col is None:
        pytest.skip("No doc column on test board — cannot run docs clear test.")

    # Write some content first
    content = f"# Pre-clear Content — {run_id}\n\nThis will be cleared."
    _put_doc(item_id, col, content)

    # Verify it's there
    raw_before = _get_doc_raw(item_id, col)
    assert f"Pre-clear Content — {run_id}" in raw_before

    # Clear the doc
    clear_result = _clear_doc(item_id, col)
    assert isinstance(clear_result, dict), f"docs clear returned unexpected: {clear_result}"
    assert clear_result.get("cleared") is True
    assert clear_result.get("blocks_deleted", 0) > 0

    # After clearing, a fresh put should succeed (column is writable)
    new_content = f"# Post-clear Content — {run_id}\n\nAfter clear."
    put_result = _put_doc(item_id, col, new_content)
    assert put_result.get("doc_id"), "Expected doc_id after put following clear"

    raw_after = _get_doc_raw(item_id, col)
    assert f"Post-clear Content — {run_id}" in raw_after
    assert f"Pre-clear Content — {run_id}" not in raw_after


@pytest.mark.integration
def test_docs_clear_makes_column_writable_after_put(
    created_item: Callable[..., str], run_id: str
) -> None:
    """AC-4 continued: clear leaves the column in a state where docs put succeeds."""
    item_id = created_item("fr0005-clear-writable")
    col = _discover_doc_column(item_id)
    if col is None:
        pytest.skip("No doc column on test board.")

    # Put some content, then clear, then put again
    _put_doc(item_id, col, f"# Initial — {run_id}")
    _clear_doc(item_id, col)

    final_content = f"# Final — {run_id}\n\nAfter clear path."
    result = _put_doc(item_id, col, final_content)
    assert result.get("doc_id"), "docs put after docs clear must succeed"

    raw = _get_doc_raw(item_id, col)
    assert f"Final — {run_id}" in raw
