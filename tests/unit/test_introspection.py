"""Tests for the Typer app introspection model (US-0001-01)."""

import json

from monday_cli.utils.introspection import AppModel, build_app_model

EXPECTED_GROUPS = {
    "workspaces",
    "boards",
    "groups",
    "items",
    "subitems",
    "statuses",
    "updates",
    "docs",
}


def _get_model() -> AppModel:
    return build_app_model()


def test_model_enumerates_all_eight_groups() -> None:
    model = _get_model()
    group_names = {g.name for g in model.groups}
    assert EXPECTED_GROUPS.issubset(group_names)


def test_model_includes_meta_commands() -> None:
    model = _get_model()
    top_level = {c.name for c in model.commands}
    # version exists today; guide and skill.md are registered by this feature.
    assert {"version", "guide", "skill.md"}.issubset(top_level)


def test_known_subcommands_present() -> None:
    model = _get_model()
    items = next(g for g in model.groups if g.name == "items")
    item_commands = {c.name for c in items.commands}
    assert {"get", "list", "create", "update", "delete"}.issubset(item_commands)


def test_parameter_fields_are_populated() -> None:
    model = _get_model()
    items = next(g for g in model.groups if g.name == "items")
    get_cmd = next(c for c in items.commands if c.name == "get")
    item_id = next(p for p in get_cmd.params if p.name == "item_id")

    assert item_id.kind in {"option", "argument"}
    assert item_id.type  # non-empty type string
    assert isinstance(item_id.required, bool)
    assert "--item-id" in item_id.opts
    assert item_id.help  # help text recorded


def test_help_flag_is_excluded() -> None:
    model = _get_model()
    for group in model.groups:
        for command in group.commands:
            assert all(p.name != "help" for p in command.params)


def test_model_is_json_serializable() -> None:
    model = _get_model()
    payload = json.dumps(model.to_dict())
    assert json.loads(payload)["name"] == "monday"


def test_command_names_include_group_qualified_entries() -> None:
    model = _get_model()
    names = model.command_names()
    assert "items get" in names
    assert "guide" in names
    assert "skill.md" in names
