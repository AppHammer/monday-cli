#!/usr/bin/env python3
"""Build script for creating Linux binary using PyInstaller."""

import re
import sys
from pathlib import Path

import PyInstaller.__main__


def build() -> None:
    """Build the Monday CLI binary."""
    project_root = Path(__file__).parent.parent
    src_path = project_root / "src"
    entry_point = src_path / "monday_cli" / "__main__.py"

    # Ensure entry point exists
    if not entry_point.exists():
        print(f"Error: Entry point not found: {entry_point}")
        sys.exit(1)

    print("Building Monday CLI binary...")
    print(f"Project root: {project_root}")
    print(f"Entry point: {entry_point}")
    print()

    PyInstaller.__main__.run(
        [
            str(entry_point),
            "--name=monday",
            "--onefile",  # Single executable
            "--clean",
            "--noconfirm",
            # Include hidden imports
            "--hidden-import=typer",
            "--hidden-import=httpx",
            "--hidden-import=pydantic",
            "--hidden-import=pydantic_settings",
            "--hidden-import=tenacity",
            "--hidden-import=ratelimit",
            "--hidden-import=rich",
            # Rich resolves Unicode cell-width tables via a dynamic import in
            # rich/_unicode_data/__init__.py at runtime (using importlib.import_module
            # with the active Unicode version, e.g. "rich._unicode_data.unicode17-0-0").
            # PyInstaller's static analysis cannot see this import, so without this
            # flag the frozen binary crashes with ModuleNotFoundError on any --table
            # command whose output contains non-ASCII characters.
            # --collect-submodules bundles ALL rich._unicode_data sub-modules (one per
            # Unicode version), making the fix forward-compatible: a future unicode18-0-0
            # is collected automatically without requiring a build-script change.
            "--collect-submodules=rich._unicode_data",
            # Ensure package metadata is included for version detection
            "--copy-metadata=monday-cli",
            # Optimize
            "--strip",  # Strip symbols (Linux)
            # -O (level 1) not -OO (level 2): level 2 strips docstrings, which
            # Typer/Click derive command help from, leaving `monday guide` help blank.
            "--optimize=1",  # Python optimization level (keep docstrings for help text)
            # Output directories
            f"--distpath={project_root / 'dist'}",
            f"--workpath={project_root / 'build' / 'temp'}",
            f"--specpath={project_root / 'build'}",
            # Additional options
            "--console",  # Console application
            "--noupx",  # Don't use UPX compression
        ]
    )

    binary_path = project_root / "dist" / "monday"
    if binary_path.exists():
        _assert_rich_unicode_data_bundled(project_root)
        print()
        print("=" * 60)
        print("✓ Build successful!")
        print(f"Binary location: {binary_path}")
        print(f"Binary size: {binary_path.stat().st_size / (1024 * 1024):.2f} MB")
        print()
        print("To install:")
        print(f"  sudo cp {binary_path} /usr/local/bin/")
        print()
        print("To test:")
        print(f"  {binary_path} --help")
        print("=" * 60)
    else:
        print("Error: Binary not created")
        sys.exit(1)


def _assert_rich_unicode_data_bundled(project_root: Path) -> None:
    """Assert that rich._unicode_data version modules are present in the frozen build.

    This hermetic guard catches accidental removal of the --collect-submodules=rich._unicode_data
    flag without requiring a live API token or a running binary.  It inspects PyInstaller's
    PYZ Table-of-Contents file (build/temp/monday/PYZ-00.toc) for at least one
    rich._unicode_data.unicodeXX-Y-Z entry and exits non-zero if none are found.

    The TOC is written by PyInstaller during the build phase and lists every module
    bundled into the frozen archive, one per line in the form:
        ('rich._unicode_data.unicode17-0-0', '/path/to/module.pyc', 'PYMODULE')
    """
    toc_path = project_root / "build" / "temp" / "monday" / "PYZ-00.toc"
    if not toc_path.exists():
        # TOC file may not exist on all PyInstaller versions; skip gracefully.
        print("  (packaging guard: PYZ-00.toc not found — skipping rich._unicode_data check)")
        return

    toc_text = toc_path.read_text(encoding="utf-8")
    # Look for at least one versioned unicode data module, e.g. rich._unicode_data.unicode17-0-0
    matches = re.findall(r"rich\._unicode_data\.unicode\d+", toc_text)
    if not matches:
        print()
        print("=" * 60)
        print("ERROR: Packaging guard failed!")
        print("  No 'rich._unicode_data.unicodeXX' modules found in the PyInstaller bundle.")
        print("  The --collect-submodules=rich._unicode_data flag may have been removed.")
        print("  Without it, '--table' commands will crash with ModuleNotFoundError on")
        print("  any output containing non-ASCII characters.")
        print()
        print("  Fix: ensure build/build_binary.py passes")
        print("       '--collect-submodules=rich._unicode_data' to PyInstaller.")
        print("=" * 60)
        sys.exit(1)

    print(
        f"  ✓ Packaging guard passed: {len(matches)} rich._unicode_data version module(s) bundled"
        f" (e.g. {matches[0]})"
    )


if __name__ == "__main__":
    build()
