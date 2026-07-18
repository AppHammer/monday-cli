"""Docs put/append/get round-trip integration tests (US-0002-07).

Docs are the highest-risk surface in this CLI: the v0.6.1 defect class this
suite exists to guard against is doc corruption / block-order scrambling
(FRD AC-5). `docs put` replaces all content (clearing existing blocks
first), `docs append` adds a block without touching what's already there,
and `docs get` prints raw Markdown via `typer.echo` -- or, when Markdown
export is unsupported for a given doc, falls back to printing the block
JSON instead (see `commands/docs.py::get_doc`). Assertions here are written
against the raw stdout text so they hold under either representation, per
run_cli(raw=True).

The doc column is discovered at runtime via `items list-columns` (filtering
for `type == "doc"`), never hardcoded, because the test board's schema is
not assumed. If the scratch test board has no doc-type column, the suite
skips with an actionable message rather than silently passing -- a doc
round-trip test that never actually touches a doc column would be a false
positive for the exact defect class it's meant to catch.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.integration.helpers import run_cli


def _discover_doc_column(item_id: str) -> str | None:
    """Return the title of the first `doc`-type column on item_id's board.

    Returns None if the board has no doc column at all.
    """
    result = run_cli("items", "list-columns", "--item-id", item_id)
    assert isinstance(result, dict)
    columns = result.get("columns", [])
    for column in columns:
        if column.get("type") == "doc":
            return str(column["title"])
    return None


def _assert_tokens_present_in_order(text: str, *tokens: str) -> None:
    """Assert every token appears in `text`, in the given order.

    This is the explicit block-order guard the suite exists for: a
    corrupted or scrambled doc would show up here as a token missing
    entirely, or present but out of sequence.
    """
    positions = []
    for token in tokens:
        idx = text.find(token)
        assert idx != -1, f"expected {token!r} in docs get output:\n{text}"
        positions.append(idx)
    assert positions == sorted(
        positions
    ), f"tokens out of order (expected {tokens} in this sequence) in docs get output:\n{text}"


@pytest.mark.integration
def test_docs_put_append_put_round_trip_preserves_block_order(
    created_item: Callable[..., str], run_id: str
) -> None:
    """put -> get, append -> get, put (again) -> get, asserting block order throughout.

    Written as one sequential test rather than several independent ones
    because the assertions are inherently stateful: `append` builds on the
    content written by the first `put`, and the second `put` is verified to
    have cleared it. Content is kept deliberately small (two short headings
    plus four one-line list items) since put/append/get are each
    multi-call under the hood (resolve item/column, resolve-or-create the
    doc, clear-then-write or append blocks) and the suite must respect the
    shared rate-limit budget.
    """
    item_id = created_item("docs-roundtrip")

    doc_column = _discover_doc_column(item_id)
    if doc_column is None:
        pytest.skip(
            "Test board 18422673411 has no doc-type column; add one to the "
            "board to enable docs integration coverage (run `monday items "
            f"list-columns --item-id {item_id}` to verify the board's columns)."
        )

    h1 = f"H1-{run_id}"
    item_a, item_b, item_c = f"item-a-{run_id}", f"item-b-{run_id}", f"item-c-{run_id}"
    h2 = f"H2-{run_id}"
    item_d = f"item-d-{run_id}"

    # --- put (replace): writes a heading followed by an ordered list ---
    put_content = f"# {h1}\n\n- {item_a}\n- {item_b}\n- {item_c}"
    put_result = run_cli(
        "docs",
        "put",
        "--item-id",
        item_id,
        "--column-name",
        doc_column,
        "--content",
        put_content,
    )
    assert isinstance(put_result, dict)
    assert put_result.get("doc_id")

    raw_after_put = run_cli(
        "docs", "get", "--item-id", item_id, "--column-name", doc_column, raw=True
    )
    # Explicit block-order assertion: heading, then list items a, b, c in order.
    _assert_tokens_present_in_order(raw_after_put, h1, item_a, item_b, item_c)

    # --- append: adds a new heading + list item, must not disturb the above ---
    append_content = f"## {h2}\n\n- {item_d}"
    append_result = run_cli(
        "docs",
        "append",
        "--item-id",
        item_id,
        "--column-name",
        doc_column,
        "--content",
        append_content,
    )
    assert isinstance(append_result, dict)
    assert append_result.get("doc_id")

    raw_after_append = run_cli(
        "docs", "get", "--item-id", item_id, "--column-name", doc_column, raw=True
    )
    # Original blocks preserved, IN ORDER, with the new block appended after
    # them -- this is the direct guard against block-order scrambling.
    _assert_tokens_present_in_order(raw_after_append, h1, item_a, item_b, item_c, h2, item_d)

    # --- put after append: replace semantics -- all prior content is cleared ---
    h3 = f"H3-replaced-{run_id}"
    item_e = f"item-e-{run_id}"
    replacement_content = f"# {h3}\n\n- {item_e}"
    put_again_result = run_cli(
        "docs",
        "put",
        "--item-id",
        item_id,
        "--column-name",
        doc_column,
        "--content",
        replacement_content,
    )
    assert isinstance(put_again_result, dict)
    assert put_again_result.get("doc_id")

    raw_after_second_put = run_cli(
        "docs", "get", "--item-id", item_id, "--column-name", doc_column, raw=True
    )
    # New content is present...
    _assert_tokens_present_in_order(raw_after_second_put, h3, item_e)
    # ...and every block from both the original put and the append is gone.
    for stale_token in (h1, item_a, item_b, item_c, h2, item_d):
        assert stale_token not in raw_after_second_put, (
            f"expected {stale_token!r} to have been cleared by the second "
            f"`docs put` (replace semantics), but it is still present:\n"
            f"{raw_after_second_put}"
        )
