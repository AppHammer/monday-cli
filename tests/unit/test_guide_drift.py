"""Drift-guard: every registered command must appear in the discovery outputs.

Fails if any registered command/group is missing from `monday guide` or
`monday guide --json`, so the discovery outputs can never silently fall out of
sync with the real command surface (US-0001-05, FRD AC-6).

The command inventory is enumerated from the live-app introspection model, so
adding a new command requires no edit to the guide — it is picked up
automatically, and removing it from the output would fail this test.
"""

import json

from typer.testing import CliRunner

from monday_cli.cli import app
from monday_cli.utils.introspection import build_app_model

runner = CliRunner()


def _guide_prose() -> str:
    result = runner.invoke(app, ["guide"])
    assert result.exit_code == 0
    return result.stdout


def _guide_json() -> dict:
    result = runner.invoke(app, ["guide", "--json"])
    assert result.exit_code == 0
    return json.loads(result.stdout)


def test_every_command_appears_in_guide_prose() -> None:
    model = build_app_model()
    out = _guide_prose()

    # Top-level meta-commands.
    for command in model.commands:
        assert f"monday {command.name}" in out, f"missing top-level '{command.name}' in guide"

    # Resource groups and their sub-commands.
    for group in model.groups:
        assert group.name in out, f"missing group '{group.name}' in guide"
        for command in group.commands:
            expected = f"monday {group.name} {command.name}"
            assert expected in out, f"missing '{expected}' in guide"


def test_every_command_appears_in_guide_json() -> None:
    model = build_app_model()
    data = _guide_json()

    json_top = {c["name"] for c in data["commands"]}
    for command in model.commands:
        assert command.name in json_top, f"missing top-level '{command.name}' in guide --json"

    json_groups = {g["name"]: g for g in data["groups"]}
    for group in model.groups:
        assert group.name in json_groups, f"missing group '{group.name}' in guide --json"
        json_cmds = {c["name"] for c in json_groups[group.name]["commands"]}
        for command in group.commands:
            assert (
                command.name in json_cmds
            ), f"missing '{group.name} {command.name}' in guide --json"
