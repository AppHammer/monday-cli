"""Tests for the guide / skill.md discovery commands (US-0001-02/03/04)."""

import json

from typer.testing import CliRunner

from monday_cli.cli import app

runner = CliRunner()


# --- monday guide (prose) — US-0001-02 --------------------------------------


def test_guide_exits_zero_and_prints() -> None:
    result = runner.invoke(app, ["guide"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_guide_contains_required_sections() -> None:
    result = runner.invoke(app, ["guide"])
    out = result.stdout
    # Grammar + standard verbs.
    assert "monday <resource> <verb>" in out
    for verb in ("list", "get", "create", "update", "delete"):
        assert verb in out
    # JSON-by-default and --table opt-in.
    assert "JSON" in out
    assert "--table" in out
    # The four runtime discovery commands.
    assert "items list-columns" in out
    assert "statuses list" in out
    assert "subitems list-columns" in out
    assert "subitems list-statuses" in out
    # Status label -> index gotcha.
    assert '{"index": N}' in out
    # Workflows section present.
    assert "workflow" in out.lower()


def test_guide_listing_is_generated_from_model() -> None:
    # A command added to the app must appear without editing the prose.
    result = runner.invoke(app, ["guide"])
    out = result.stdout
    assert "monday items get" in out
    assert "monday boards list" in out


# --- monday guide --json — US-0001-03 ---------------------------------------


def test_guide_json_is_valid_and_complete() -> None:
    result = runner.invoke(app, ["guide", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)

    group_names = {g["name"] for g in data["groups"]}
    assert {"items", "boards", "docs", "statuses"}.issubset(group_names)

    top = {c["name"] for c in data["commands"]}
    assert {"version", "guide", "skill.md"}.issubset(top)

    # Options carry type + help metadata.
    items = next(g for g in data["groups"] if g["name"] == "items")
    get_cmd = next(c for c in items["commands"] if c["name"] == "get")
    item_id = next(p for p in get_cmd["params"] if p["name"] == "item_id")
    assert item_id["type"]
    assert item_id["help"]


# --- monday skill.md / guide --skill — US-0001-04 ---------------------------


def test_skill_md_frontmatter_and_body() -> None:
    result = runner.invoke(app, ["skill.md"])
    assert result.exit_code == 0
    out = result.stdout

    # Frontmatter block delimited by ---.
    parts = out.split("---")
    assert len(parts) >= 3
    frontmatter = parts[1]
    assert "name:" in frontmatter
    assert "description:" in frontmatter

    # Body points at monday guide as the source of truth.
    body = "---".join(parts[2:])
    assert "monday guide" in body


def test_guide_skill_alias_matches_skill_md() -> None:
    a = runner.invoke(app, ["guide", "--skill"])
    b = runner.invoke(app, ["skill.md"])
    assert a.exit_code == 0
    assert a.stdout == b.stdout
