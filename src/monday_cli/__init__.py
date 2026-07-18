"""Monday CLI package."""

try:
    from importlib.metadata import version

    __version__ = version("monday-cli")
except Exception:
    # Fallback when package metadata is unavailable (e.g. running from a
    # source checkout without an install). Keep in sync with pyproject.toml.
    __version__ = "0.6.3"
