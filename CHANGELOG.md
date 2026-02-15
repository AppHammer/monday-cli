# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
