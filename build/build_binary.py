#!/usr/bin/env python3
"""Build script for creating Linux binary using PyInstaller."""

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

    PyInstaller.__main__.run([
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
        # Ensure package metadata is included for version detection
        "--copy-metadata=monday-cli",
        # Optimize
        "--strip",  # Strip symbols (Linux)
        "--optimize=2",  # Python optimization level
        # Output directories
        f"--distpath={project_root / 'dist'}",
        f"--workpath={project_root / 'build' / 'temp'}",
        f"--specpath={project_root / 'build'}",
        # Additional options
        "--console",  # Console application
        "--noupx",  # Don't use UPX compression
    ])

    binary_path = project_root / "dist" / "monday"
    if binary_path.exists():
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


if __name__ == "__main__":
    build()
