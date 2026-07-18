"""Agent self-discovery meta-commands: ``guide`` and ``skill.md``.

These commands let an autonomous agent learn the whole CLI in one shot instead
of walking ``--help`` across many calls:

- ``monday guide`` — a curated, agent-oriented prose usage guide (PRIMARY).
- ``monday guide --json`` — the full command tree as machine-readable JSON.
- ``monday skill.md`` (also ``monday guide --skill``) — a thin, ready-to-drop-in
  Claude Code ``SKILL.md`` that points back at ``monday guide``.

All three derive their command inventory from the live-app introspection model
(:mod:`monday_cli.utils.introspection`) so they can never drift from the
commands the binary actually exposes.
"""

from __future__ import annotations

import typer

from monday_cli import __version__
from monday_cli.cli import app
from monday_cli.utils.introspection import AppModel, CommandModel, build_app_model
from monday_cli.utils.output import print_json

# --- Authored preamble ------------------------------------------------------

_PREAMBLE = """\
# monday guide

`monday` is a self-contained CLI for driving Monday.com from an autonomous agent.
This guide is the single-shot front door: read it once and you can operate the
whole tool without walking `--help` across many calls. For the authoritative,
always-current options of any command, run `monday <resource> <verb> --help`.

## Command grammar

Every command follows a strict grammar:

    monday <resource> <verb> [OPTIONS]

Resources are the Monday.com objects (`workspaces`, `boards`, `groups`, `items`,
`subitems`, `statuses`, `updates`, `docs`). Verbs are reused consistently across
resources, so once you learn them for one resource you know them for all.

## Standard verbs

- `list`   — enumerate objects (supports `--limit`, `--cursor`, `--all` where paginated)
- `get`    — fetch one object by id
- `create` — create a new object
- `update` — change a field on an existing object
- `delete` — remove an object (pass the skip-confirmation flag for non-interactive use)

Options are always named (e.g. `--item-id 123`), never positional. IDs are passed
as integers on the CLI and converted to strings internally.

## Output: JSON by default, `--table` to opt in

Every command prints clean, machine-readable JSON to stdout by default so you can
parse it without scraping. `list` commands additionally accept `--table` for a
human-readable Rich table — that is a convenience layer, never the default.

## Discovering a board at runtime

You do not need prior knowledge of a board. Learn its schema before acting:

- `monday items list-columns --board-id <ID>`     — the board's columns and ids
- `monday statuses list --board-id <ID>`          — status columns and their labels
- `monday subitems list-columns --board-id <ID>`  — subitem columns
- `monday subitems list-statuses --board-id <ID>` — subitem status labels

Errors are designed to teach the next step: a bad column title prints the
available columns, a bad status label prints the valid labels.

## Gotcha: status labels vs. index

Status columns store a numeric index, but you should pass the human-readable
**label** — the CLI maps it to `{"index": N}` for you (matched case-insensitively).
For example, to move an item to "Done" you pass `--value "Done"`, not `--value 1`.
Use the discovery commands above to see the valid labels for a column.

## End-to-end workflows

Workflow 1 — read an item and update its status:

    monday items get --item-id 1234567890
    monday statuses list --board-id 111 --table
    monday items update --item-id 1234567890 --title "Status" --value "Done"

Workflow 2 — create an item in a group, then comment on it:

    monday groups list --board-id 111
    monday items create --board-id 111 --name "New task" --group-id topics
    monday updates create --item-id 1234567890 --body "Work started"

Workflow 3 — page through every item on a board as JSON:

    monday items list --board-id 111 --all

## Layered discovery

1. `monday guide` — this guide (start here).
2. `monday <resource> <verb> --help` — authoritative per-command options.
3. `monday skill.md` — generate a thin SKILL.md wrapper for skill-aware harnesses.
"""


# --- Rendering helpers ------------------------------------------------------


def _format_command(prefix: str, command: CommandModel) -> str:
    """Render one command line with its help and options for the listing."""
    lines: list[str] = []
    help_text = f" — {command.help}" if command.help else ""
    lines.append(f"  {prefix} {command.name}{help_text}".rstrip())
    for param in command.params:
        if param.kind == "option":
            flag = param.opts[0] if param.opts else f"--{param.name.replace('_', '-')}"
            marker = " (required)" if param.required else ""
        else:
            flag = f"<{param.name}>"
            marker = "" if param.required else " (optional)"
        phelp = f" — {param.help}" if param.help else ""
        lines.append(f"      {flag}{marker}{phelp}".rstrip())
    return "\n".join(lines)


def render_command_listing(model: AppModel) -> str:
    """Generate the command listing section from the introspection model."""
    lines: list[str] = ["## Command reference (generated from the live app)", ""]

    if model.commands:
        lines.append("### Top-level commands")
        lines.append("")
        for command in model.commands:
            lines.append(_format_command("monday", command))
        lines.append("")

    for group in model.groups:
        header = f"### {group.name}"
        if group.help:
            header += f" — {group.help}"
        lines.append(header)
        lines.append("")
        for command in group.commands:
            lines.append(_format_command(f"monday {group.name}", command))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_guide_prose(model: AppModel) -> str:
    """Render the full prose guide: authored preamble + generated listing."""
    return f"{_PREAMBLE}\n{render_command_listing(model)}"


def render_skill_md() -> str:
    """Render a thin Claude Code SKILL.md that points at ``monday guide``.

    Deliberately thin: valid YAML frontmatter (``name`` + ``description``) plus a
    body whose first instruction is to run ``monday guide``. No hand-maintained
    command catalog is embedded — the CLI is the single source of truth.
    """
    description = (
        "Drive Monday.com from the command line with the self-contained `monday` "
        "binary. Run `monday guide` for the full, always-current usage guide."
    )
    return f"""\
---
name: monday-cli
description: {description}
---

# monday-cli

The `monday` CLI is the single source of truth for its own usage. This skill is a
thin pointer: it deliberately does not hand-maintain a command catalog.

## How to use

1. Run `monday guide` for the complete, always-current agent usage guide
   (command grammar, standard verbs, JSON-by-default output, runtime board
   discovery, and end-to-end workflows).
2. Run `monday guide --json` for the full command tree as machine-readable JSON
   when you need to synthesize tool/function definitions.
3. Run `monday <resource> <verb> --help` for authoritative per-command options.

Generated by `monday skill.md` (monday-cli v{__version__}).
"""


# --- Commands ---------------------------------------------------------------


@app.command("guide")
def guide(
    json_output: bool = typer.Option(
        False, "--json", help="Emit the full command tree as machine-readable JSON."
    ),
    skill: bool = typer.Option(
        False, "--skill", help="Emit a thin SKILL.md (alias for `monday skill.md`)."
    ),
) -> None:
    """Print a complete, agent-oriented usage guide for the whole CLI.

    The primary discovery command: one invocation teaches an agent the command
    grammar, standard verbs, output model, runtime board-discovery recipe, and
    end-to-end workflows — no need to walk `--help` across many calls.

    Examples:
        monday guide
        monday guide --json
        monday guide --skill
    """
    if json_output:
        model = build_app_model()
        print_json(model.to_dict())
        return

    if skill:
        typer.echo(render_skill_md())
        return

    model = build_app_model()
    typer.echo(render_guide_prose(model))


@app.command("skill.md")
def skill_md() -> None:
    """Generate a thin Claude Code SKILL.md that points at `monday guide`.

    Emits valid YAML frontmatter plus a body whose first instruction is to run
    `monday guide`. Drop the output into your skills directory; the CLI stays the
    single source of truth, so there is no command catalog to hand-maintain.

    Example:
        monday skill.md > SKILL.md
    """
    typer.echo(render_skill_md())
