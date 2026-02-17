# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
