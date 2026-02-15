"""Monday CLI package."""

try:
    from importlib.metadata import version
    __version__ = version("monday-cli")
except Exception:
    __version__ = "unknown"
