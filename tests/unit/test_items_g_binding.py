"""FR-0009 B3/A: -g binds to the SAME logical option across items subcommands.

`-g` must mean `--group` (title-or-id) on `items list`, `items create`, and
`items move` — never `--group-id`. This introspects the live Click commands so
the guarantee can't silently drift.
"""

from __future__ import annotations

import click
import typer

from monday_cli.cli import app


def _command(*path: str) -> click.Command:
    cmd: click.Command = typer.main.get_command(app)
    for name in path:
        cmd = cmd.commands[name]  # type: ignore[attr-defined]
    return cmd


def _param_for_opt(cmd: click.Command, opt: str) -> click.Parameter:
    for param in cmd.params:
        if opt in getattr(param, "opts", []) or opt in getattr(param, "secondary_opts", []):
            return param
    raise AssertionError(f"option {opt} not found on {cmd.name}")


def test_dash_g_binds_to_group_across_subcommands() -> None:
    for path in (("items", "list"), ("items", "create"), ("items", "move")):
        cmd = _command(*path)
        param = _param_for_opt(cmd, "-g")
        assert param.name == "group", f"-g must bind to `group` on {' '.join(path)}"
        assert "--group" in param.opts, f"-g must alias --group on {' '.join(path)}"


def test_group_id_is_long_only_across_subcommands() -> None:
    for path in (("items", "list"), ("items", "create"), ("items", "move")):
        cmd = _command(*path)
        param = _param_for_opt(cmd, "--group-id")
        assert param.name == "group_id"
        # --group-id must NOT carry the -g short alias anywhere.
        assert "-g" not in param.opts and "-g" not in param.secondary_opts
