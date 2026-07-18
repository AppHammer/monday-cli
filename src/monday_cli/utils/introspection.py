"""Introspection of the live Typer/Click app into a structured command model.

This module walks the fully-assembled root Typer application and produces an
in-memory model of its command surface: resource groups -> commands -> parameters,
plus the top-level meta-commands (``version``, ``guide``, ``skill.md``).

All three agent-discovery outputs (``monday guide``, ``monday guide --json``,
``monday skill.md``) derive their command inventory from this model so they can
never drift from the commands the binary actually exposes.

The routine is pure: it inspects the Click command tree, executes no command,
and makes no network calls. It uses structural (duck-typed) access rather than
``isinstance`` checks so it is robust across Typer versions that vendor their
own copy of Click.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import typer
import typer.main


@dataclass
class ParamModel:
    """A single command parameter (option or argument)."""

    name: str
    kind: str  # "option" | "argument"
    type: str
    required: bool
    default: Any
    help: str | None
    opts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "name": self.name,
            "kind": self.kind,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "help": self.help,
            "opts": self.opts,
        }


@dataclass
class CommandModel:
    """A single command (a leaf in the command tree)."""

    name: str
    help: str | None
    params: list[ParamModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "name": self.name,
            "help": self.help,
            "params": [p.to_dict() for p in self.params],
        }


@dataclass
class GroupModel:
    """A resource command group (e.g. ``items``, ``boards``)."""

    name: str
    help: str | None
    commands: list[CommandModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "name": self.name,
            "help": self.help,
            "commands": [c.to_dict() for c in self.commands],
        }


@dataclass
class AppModel:
    """The full application model: top-level meta-commands plus resource groups."""

    name: str
    help: str | None
    commands: list[CommandModel] = field(default_factory=list)
    groups: list[GroupModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "name": self.name,
            "help": self.help,
            "commands": [c.to_dict() for c in self.commands],
            "groups": [g.to_dict() for g in self.groups],
        }

    def command_names(self) -> list[str]:
        """Return every registered name.

        Includes top-level meta-command names, resource group names, and each
        resource sub-command rendered as ``group command``.
        """
        names: list[str] = []
        for command in self.commands:
            names.append(command.name)
        for group in self.groups:
            names.append(group.name)
            for command in group.commands:
                names.append(f"{group.name} {command.name}")
        return names


def _clean_help(text: str | None) -> str | None:
    """Collapse a Click help string to a single trimmed line."""
    if not text:
        return None
    return " ".join(text.split()).strip() or None


def _is_group(node: Any) -> bool:
    """Duck-typed check: a group exposes a ``commands`` mapping."""
    commands = getattr(node, "commands", None)
    return isinstance(commands, dict)


def _is_help_flag(param: Any) -> bool:
    """Detect the auto-injected ``--help`` eager flag so we can skip it."""
    return bool(
        getattr(param, "name", None) == "help"
        and getattr(param, "is_eager", False)
        and not getattr(param, "expose_value", True)
    )


def _command_help(command: Any) -> str | None:
    """Best-effort help string for a command."""
    return _clean_help(getattr(command, "help", None) or getattr(command, "short_help", None))


def _build_param(param: Any) -> ParamModel:
    """Convert a Click parameter into a ParamModel."""
    default = param.default
    # Normalize non-JSON-safe defaults (e.g. callables) to None.
    if callable(default):
        default = None

    param_type = getattr(param, "type", None)
    type_name = getattr(param_type, "name", "text") if param_type is not None else "text"

    return ParamModel(
        name=param.name or "",
        kind=getattr(param, "param_type_name", "option"),  # "option" | "argument"
        type=type_name,
        required=bool(getattr(param, "required", False)),
        default=default,
        help=_clean_help(getattr(param, "help", None)),
        opts=list(getattr(param, "opts", []) or []),
    )


def _build_command(name: str, command: Any) -> CommandModel:
    """Convert a Click command into a CommandModel."""
    params = [_build_param(p) for p in getattr(command, "params", []) if not _is_help_flag(p)]
    return CommandModel(name=name, help=_command_help(command), params=params)


def _build_group(name: str, group: Any) -> GroupModel:
    """Convert a Click group into a GroupModel."""
    commands: list[CommandModel] = []
    for cmd_name in sorted(group.commands):
        commands.append(_build_command(cmd_name, group.commands[cmd_name]))
    return GroupModel(name=name, help=_command_help(group), commands=commands)


def build_app_model(app: typer.Typer | None = None) -> AppModel:
    """Introspect the live Typer app into a structured :class:`AppModel`.

    Args:
        app: Optional Typer app to introspect. Defaults to the fully-assembled
            root ``monday_cli.cli.app`` (imported lazily so this module stays
            importable during CLI registration).

    Returns:
        The structured command model.
    """
    if app is None:
        # Lazy import: command modules are registered at the bottom of cli.py,
        # so importing here (at call time) guarantees the fully-assembled app.
        from monday_cli.cli import app as root_app

        app = root_app

    root: Any = typer.main.get_command(app)

    top_commands: list[CommandModel] = []
    groups: list[GroupModel] = []

    members: dict[str, Any] = getattr(root, "commands", {}) or {}
    for name in sorted(members):
        member = members[name]
        if _is_group(member):
            groups.append(_build_group(name, member))
        else:
            top_commands.append(_build_command(name, member))

    return AppModel(
        name=getattr(root, "name", None) or "monday",
        help=_clean_help(getattr(root, "help", None)),
        commands=top_commands,
        groups=groups,
    )
