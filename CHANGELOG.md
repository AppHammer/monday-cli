# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — FR-0004

> **Maintainer note:** The `docs get` default output change (Markdown → JSON) is a
> **breaking change** that justifies at least a **minor version bump** pre-1.0
> (i.e. 0.5.0 → 0.6.0). Please confirm the version number before tagging a release.

### BREAKING CHANGE

- **`monday docs get` default output changed from Markdown to JSON.**
  The command now emits a deterministic, lossless JSON object
  `{"markdown": <string|null>, "blocks": [...]}` on stdout by default, parseable by
  any downstream tool without special-casing.
  - **Migration path:** users who relied on the previous bare-Markdown default output
    should add `--raw` (or the alias `--markdown`) to their invocations:
    ```bash
    # Before (0.5.x and earlier)
    monday docs get --item-id 123 --column-name "Notes"
    # After (0.6.0+) — same Markdown output on stdout
    monday docs get --item-id 123 --column-name "Notes" --raw
    ```
  - The silent Markdown-vs-JSON shape switch (depending on whether Markdown export
    was supported by the document) has been removed. The new default is always a
    single JSON object regardless of export support (`markdown` key is `null` when
    export is unavailable, `blocks` key is always populated).

### Added

- `monday docs get --raw` / `--markdown` flag: prints rendered Markdown directly to
  stdout for human consumption. `--raw` is the canonical spelling; `--markdown` is a
  discoverable alias. Errors loudly to stderr and exits non-zero when Markdown export
  is unavailable (no silent fallback to block JSON).

### Changed

- `monday docs get` default output is now a deterministic JSON object
  `{"markdown": <str|null>, "blocks": [...]}` emitted via `print_json()`.
  Both keys are always present: `markdown` is the rendered Markdown string when export
  succeeds, or `null` when unsupported; `blocks` is always the raw block JSON so the
  payload is lossless even without Markdown export support.

## [0.5.0] - 2026-02-17

### Added
- Update replies now included in `monday items get` output
- `monday updates get` command to retrieve updates and replies for an item (without column values)
- `Reply` model for update replies
- `GET_ITEM_UPDATES` lightweight GraphQL query for fetching item updates

## [0.4.0] - 2026-02-17

### Added
- `monday docs put` command to replace document content with Markdown (clears existing content, then writes new)
- `monday docs get` now returns document content as Markdown (with block JSON fallback)
- `mondday docs append` command to add Markdown content to existing document without clearing
- DELETE_DOC_BLOCK mutation for clearing individual document blocks
- Paginated block fetching for reliable content clearing on large documents

### Changed
- Renamed `monday docs set` to `monday docs append` for clarity
- Overhauled `monday docs get` to use markdown export instead of raw block JSON

## [0.3.0] - 2026-02-15

### Added
- Delete command for items: `monday items delete --item-id <id>`
- Delete command for subitems: `monday subitems delete --subitem-id <id>`
- Confirmation prompts for delete operations (can be bypassed with --force flag)
- Deletion verification to handle Monday.com API authorization quirks

## [0.2.0] - 2026-02-15

### Added
- GitHub Actions workflow for automated binary releases
- CHANGELOG.md for tracking version history
- Dynamic version reading from package metadata in __init__.py

### Changed
- Updated typer from 0.12.3 to 0.21.1+ to fix compatibility issues

### Fixed
- Version command now correctly reports version from pyproject.toml instead of hardcoded value
- GitHub releases now sync with `monday version` command output

## [0.1.0] - Initial Release

### Added
- CLI interface for Monday.com API
- Item management commands (get, create)
- Subitem management commands (create, update-status)
- Update management commands (create)
- Environment-based configuration
- PyInstaller build script for Linux binaries
