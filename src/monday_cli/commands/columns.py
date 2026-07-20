"""Commands for managing Monday.com board columns (structure).

Verb commands (create/update/delete/list) are registered on columns_app by
the sibling functions below, added in the dependent issues (#86/#87/#88/#89).
"""

from monday_cli.cli import columns_app  # noqa: F401

__all__ = ["columns_app"]
