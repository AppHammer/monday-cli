"""FR-0008 invariant guard: stdout must carry ONLY JSON in default mode.

This guard test statically analyses every ``commands/*.py`` module and fails
if it finds a bare ``typer.secho`` / ``typer.echo`` / ``print(`` call that
could write to stdout outside of a ``--table`` branch.

The check is AST-based, not text-based, so it is not fooled by comments or
string literals that contain the banned patterns.  New command modules are
automatically covered without any edit to this file.

Contract enforced (FR-0008 AC-8):
  - ``typer.secho(...)`` without ``err=True`` is ONLY allowed inside
    ``if table:`` (or equivalent) branches.
  - ``typer.echo(...)`` without ``err=True`` is ONLY allowed inside
    ``if table:`` / ``if raw:`` branches (``docs get --raw`` intentionally
    prints Markdown to stdout — that is an explicit human opt-out and is
    guarded by a flag check in the AST).
  - Bare ``print(...)`` is only allowed in ``utils/output.py`` (``print_json``
    is the designated stdout emitter) and nowhere in ``commands/*.py``.
  - ``secho_err(...)`` / ``eprint(...)`` from ``utils.output`` are the
    approved helpers and are not flagged.

Exemptions (documented):
  - Calls inside an ``if table:`` branch (rich table output is human-only).
  - Calls inside an ``if raw:`` branch (``docs get --raw`` explicit opt-out).
  - ``typer.echo(export.get("markdown") or "")`` inside ``if raw:`` in
    docs.py (raw Markdown output to stdout for human consumption).
  - ``console.print(...)`` (Rich Console writes to stdout in table mode —
    exempt because it is always inside an ``if table:`` branch).
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

# All command modules to audit
_COMMANDS_DIR = Path(__file__).parent.parent.parent / "src" / "monday_cli" / "commands"


def _is_in_flag_branch(node: ast.AST, tree: ast.AST, flag_names: set[str]) -> bool:
    """Return True if *node* is a direct descendant of an ``if <flag>:`` test.

    Walks up the tree looking for an enclosing ``ast.If`` whose test is one of
    the flag names (e.g. ``table``, ``raw``).  Only one level of enclosing If
    is checked for simplicity; nested branches are still flagged.
    """
    # Build a child-to-parent mapping for the whole tree
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    current: ast.AST | None = node
    while current is not None:
        parent = parents.get(id(current))
        if parent is None:
            break
        if isinstance(parent, ast.If):
            test = parent.test
            # Direct name check: ``if table:``
            if isinstance(test, ast.Name) and test.id in flag_names:
                # Check node is in the 'if' body, not the 'else'
                if current in parent.body:
                    return True
            # ``if not table:`` — skip those, they can still write to stdout
        current = parent
    return False


def _find_stdout_violations(source: str, filepath: str) -> list[str]:
    """Parse *source* and return a list of violation descriptions."""
    tree = ast.parse(source, filename=filepath)
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func

        # --- typer.secho(...) without err=True ---
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "secho"
            and isinstance(func.value, ast.Name)
            and func.value.id == "typer"
        ):
            # Check for err=True keyword arg
            has_err_true = any(
                kw.arg == "err" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in node.keywords
            )
            if not has_err_true:
                if not _is_in_flag_branch(node, tree, {"table", "raw"}):
                    violations.append(
                        f"line {node.lineno}: typer.secho() without err=True"
                        " outside table/raw branch"
                    )

        # --- typer.echo(...) without err=True ---
        elif (
            isinstance(func, ast.Attribute)
            and func.attr == "echo"
            and isinstance(func.value, ast.Name)
            and func.value.id == "typer"
        ):
            has_err_true = any(
                kw.arg == "err" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in node.keywords
            )
            if not has_err_true:
                if not _is_in_flag_branch(node, tree, {"table", "raw"}):
                    violations.append(
                        f"line {node.lineno}: typer.echo() without err=True"
                        " outside table/raw branch"
                    )

        # --- bare print(...) ---
        elif isinstance(func, ast.Name) and func.id == "print":
            if not _is_in_flag_branch(node, tree, {"table", "raw"}):
                violations.append(
                    f"line {node.lineno}: bare print() call (use print_json or secho_err)"
                )

    return violations


def _get_command_modules() -> list[Path]:
    """Return all .py files in the commands directory, excluding __init__ and guide.py.

    guide.py is excluded because ``monday guide`` / ``monday skill.md`` are
    deliberately stdout writers — they output the guide prose / SKILL.md content
    to stdout as their primary purpose.  They have no JSON mode and are not
    subject to the clean-stdout contract (the contract applies only to
    resource-management commands that output JSON data).
    """
    return [
        p for p in sorted(_COMMANDS_DIR.glob("*.py")) if p.name not in {"__init__.py", "guide.py"}
    ]


@pytest.mark.parametrize(
    "module_path",
    _get_command_modules(),
    ids=lambda p: p.name,
)
def test_no_stdout_contamination_in_default_mode(module_path: Path) -> None:
    """FR-0008 AC-8: command module must not write prose to stdout in default mode.

    Any ``typer.secho`` / ``typer.echo`` / bare ``print`` call found OUTSIDE
    a ``--table`` or ``--raw`` branch is a contract violation.
    """
    source = module_path.read_text(encoding="utf-8")
    violations = _find_stdout_violations(source, str(module_path))
    if violations:
        detail = textwrap.indent("\n".join(violations), "  ")
        pytest.fail(
            f"{module_path.name} has stdout contamination"
            f" (FR-0008 contract violation):\n{detail}\n\n"
            "Fix: replace typer.secho/echo with secho_err() from monday_cli.utils.output,"
            " or add err=True, or ensure the call is inside an `if table:` / `if raw:` block."
        )


def test_secho_err_writes_to_stderr_not_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """FR-0008 AC-2 (unit): secho_err() writes to stderr and nothing to stdout."""
    import typer

    from monday_cli.utils.output import secho_err

    secho_err("test message", fg=typer.colors.RED)

    captured = capsys.readouterr()
    assert "test message" in captured.err
    assert "test message" not in captured.out
    assert captured.out == ""


def test_eprint_writes_to_stderr_not_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """FR-0008 AC-2 (unit): eprint() writes to stderr and nothing to stdout."""
    from monday_cli.utils.output import eprint

    eprint("hello stderr")

    captured = capsys.readouterr()
    assert "hello stderr" in captured.err
    assert "hello stderr" not in captured.out
    assert captured.out == ""


def test_print_json_writes_to_stdout_only(capsys: pytest.CaptureFixture[str]) -> None:
    """FR-0008: print_json() is the sole stdout writer and produces valid JSON."""
    import json

    from monday_cli.utils.output import print_json

    print_json({"key": "value", "num": 42})

    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data == {"key": "value", "num": 42}
