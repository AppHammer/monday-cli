# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Project Overview

Monday CLI exists to make it easy for **AI agents to use Monday.com**. It is the fallback for environments where the Monday.com MCP server cannot be hosted (locked-down CI, minimal or air-gapped containers, ephemeral agent sandboxes): instead of an MCP integration, an agent shells out to a single self-contained `monday` binary. The primary user is an autonomous agent, not a human at a keyboard, and every design decision should serve that audience.

It is a Python tool built with Typer and httpx, packaged into a standalone single-file Linux binary with PyInstaller so it can be dropped into any agent's `PATH` with no runtime dependencies.

## Project Management
Monday Board Url:  https://apphammer.monday.com/boards/18422673287

Test Board Url:  https://apphammer.monday.com/boards/18422673411
This is a scratch board for automated/integration tests that exercise the CLI against a live Monday.com board. Use this board — never the project-management board above — for any test that creates, mutates, or deletes items, subitems, groups, statuses, updates, or docs.

## Instructions for Claude
1. Monday is the project north star. You can't code anything without a monday.com task.
2. Always use the apphammer agents to perform your tasks:
  pm - product management
  sa - system architect
  coder - software development, write code
  qa - quality assurance
  ui-testing - test the ui with playwright
3. You can use other tools / skills for thinking, researching and brainstorming, but the apphammer agents do the real work.
4. Follow a strict development flow:  
  1. Every Monday task must be well-defined for the sa. The pm agent can create a FRD as needed, but all tasks need a feature ID FR-XXXX
  2. the sa agent will break down the monday task into github issues. These are always labeled with the monday feature ID.
  3. The coder agent is the only agent allowed to write code. Always use /implement-feature --label to work on issues, QA and then code review them.
  4. Always pull requests, no commits working on main or commits to main ever.
5. If you encounter a bug, issue or enhancement while working on a task, create a new task in monday on the backlog for it. We don't code anything without a monday task!
6. As you complete phases update the status of the monday task, "Working on it", "Review", "Ready to Merge", etc. Post updated as needed.
7. When possible parallelize your work and invoke subagents.

## Common Commands

```bash
# Run from source (no build needed)
python -m monday_cli --help
python -m monday_cli items get --item-id 1234567890

# Install for development (editable + dev deps)
pip install -e ".[dev]"

# Tests
pytest                                   # full suite (coverage is on by default via pyproject addopts)
pytest tests/unit                        # only unit tests
pytest tests/unit/test_foo.py::test_bar  # a single test

# Lint / format / type-check
ruff check src tests
black src tests
mypy src            # strict mode is enabled

# Build the standalone Linux binary -> dist/monday
python build/build_binary.py
```

Requires Python >= 3.11. Auth is via the `MONDAY_API_TOKEN` environment variable (loaded from `.env` if present); token comes from https://apphammer.monday.com/admin/integrations/api.

## Architecture

The package lives under `src/monday_cli/` (src layout; console entry point is `monday = monday_cli.cli:main`).

**Command registration is import-driven and order-sensitive.** `cli.py` creates the root Typer `app` plus one sub-`Typer` per resource (`workspaces_app`, `boards_app`, `groups_app`, `items_app`, `subitems_app`, `statuses_app`, `updates_app`, `docs_app`). Each `commands/*.py` module imports its sub-app from `cli.py` and attaches commands via `@items_app.command(...)` decorators. Crucially, `cli.py` imports the command modules **at the bottom of the file** (after all definitions) to avoid a circular import — commands import from `cli`, and `cli` imports the commands last. Adding a new resource means creating the sub-`Typer`, registering it with `app.add_typer(...)`, and adding the module to that bottom-of-file import.

**Client layer** (`client/`):
- `graphql_client.py` — `MondayGraphQLClient` wraps a single `httpx.Client`. All calls go through `_make_request`, which is composed at call time as `rate_limiter(retry_decorator(_make_request))` via the `_rate_limited_request` property. It maps HTTP 401 → `AuthenticationError`, 429 → `RateLimitError`, GraphQL `errors` → `MondayAPIError` (or `ComplexityError` when the message mentions complexity), and network failures → `NetworkError`. Public API is `execute_query()` / `execute_mutation()`, both returning the `data` dict.
- `queries.py` / `mutations.py` — GraphQL operation strings as module constants (e.g. `GET_ITEM_BY_ID`, `CREATE_ITEM`, `CHANGE_COLUMN_VALUE`). Queries should include a `complexity { before after }` block so the client can log/warn on remaining budget.
- `models.py` — Pydantic models for API responses.

**Cross-cutting utilities** (`utils/`): `rate_limit.py` (`MondayRateLimiter`, 60 calls/60s by default), `retry.py` (`create_retry_decorator`, exponential backoff), `error_handler.py` (exception hierarchy rooted at `MondayCliError`), `output.py` (`print_json` for machine-readable output; list commands also render Rich tables), and `logging.py`.

**Config** (`config.py`): `Settings` is a `pydantic-settings` `BaseSettings` loaded from env / `.env`. Access it through the cached `get_settings()`; the client itself is lazily created once via `get_client()` in `cli.py` and closed in `main()`'s `finally`. Defaults (rate limits, retry, API URL, timeouts) live in `constants.py`.

## Agent-First Design Principles

The guiding principle for the CLI itself: it must be **usable and discoverable by an AI agent** that has no prior knowledge of a specific board and cannot ask a human for help. Every existing command follows these, and every new command or feature must uphold them — treat a change that breaks one as a regression:

- **`monday guide` is the PRIMARY discovery mechanism.** Discovery is layered: (1) `monday guide` — the canonical, in-binary, single-shot agent usage guide (plus `monday guide --json` for the command tree as machine-readable JSON); (2) `monday <resource> <verb> --help` — authoritative per-command option detail; (3) `monday skill.md` — a generated, thin `SKILL.md` wrapper for skill-aware harnesses (`monday guide --skill` is an equivalent alias). **The CLI is the single source of truth for its own usage — do NOT hand-maintain a `SKILL.md` in this repo; it is emitted on demand.** All three outputs derive their command inventory from `utils/introspection.py`, which introspects the live Typer/Click app, so they can never drift from the real command surface. A drift-guard test (`tests/unit/test_guide_drift.py`) enforces this; adding a command surfaces it in `guide` automatically, and any new resource should still be reachable from `monday guide`.
- **Discoverable from `--help` alone.** An agent should be able to learn the whole tool by walking `--help`. Keep a strict `monday <resource> <verb>` grammar, reuse the standard verbs (`list`, `get`, `create`, `update`, `delete`), and put concrete, copy-pasteable examples in every command docstring.
- **Self-describing boards.** Ship commands that let an agent learn a board's schema at runtime *before* acting: `items list-columns`, `statuses list`, `subitems list-columns`, `subitems list-statuses`. Any new resource should provide an equivalent discovery command.
- **Machine-readable by default.** Emit clean JSON on stdout via `print_json()` so an agent can parse output without scraping. `--table` is a human convenience layered on top — never the default.
- **Errors that teach the next step.** On failure, print what to do next and the valid choices, then exit non-zero. This is already the pattern: a bad column title prints `Available columns: ...`, a bad status label prints `Available statuses: ...`, a missing arg prints an example invocation. Preserve it.
- **Human-readable inputs over opaque IDs.** Let agents act on what they can see — accept names/titles/labels case-insensitively (e.g. `--title "Status" --value "Done"`) and resolve to column IDs and indices internally.
- **Deterministic and non-interactive.** Anything scriptable must run without a TTY prompt: `--all` for pagination, and a flag to skip delete confirmations. (Note: this skip flag is currently inconsistent — `groups delete` uses `--confirm/-y` while `items delete` and `subitems delete` use `--force/-f`. Converge new destructive commands on one spelling; consistency is itself a discoverability feature.)

## Conventions

- **CLI IDs are `int` typer options** for validation, but Monday's GraphQL uses `ID!` (string) — always `str(...)` an ID before putting it in query variables.
- **Named options over positional args** for all commands (e.g. `monday items get --item-id 123`).
- **All `list` commands support `--table`**; paginated list commands support `--limit` (1–500), `--cursor`, and `--all`.
- **Output**: data via `print_json()`; user messages via `typer.secho()` (green = success with a `✓`, yellow = warning/not-found, red = error). Always `raise typer.Exit(1)` after an error message.
- **Error handling in commands**: catch `AuthenticationError`, `RateLimitError`, `MondayAPIError`, then a catch-all `Exception`, in that order.
- Command names are kebab-case (`list-columns`); function names are snake_case.

## Status columns

Status columns carry a `settings_str` JSON blob mapping index → label (e.g. `{"labels": {"0": "Done", "1": "Working on it"}}`). The `items update` / `subitems update` commands look up a column by title (case-insensitive), detect its type from the board schema, and format the value accordingly — status labels are matched case-insensitively and converted to `{"index": N}`; other handled types include text, link, date, numbers, and long-text.

## Release Process (Conventional Commits + Automated CI)

Releases are **fully automated from CI** — never push tags by hand or edit version/changelog files manually.

### Commit Message Convention

Every commit must follow **Conventional Commits**:

```
<type>[optional scope]: <description>
```

| Type | Bump | Effect on release |
|------|------|-------------------|
| `feat` | minor (`0.x.0`) | Included in release |
| `fix` / `perf` | patch (`0.0.x`) | Included in release |
| `feat!` or `BREAKING CHANGE:` | major (`x.0.0`) | Included in release |
| `chore` / `ci` / `docs` / `build` / `style` / `test` / `refactor` | none | No release triggered |

A PR CI check (`commit-lint.yml`) **blocks the PR** if commits or the PR title don't conform.

### Automated Release Flow

```
merge to main → tests.yml (gate) → semantic-release.yml:
  - Compute next version from commits since last tag
  - If no releasable commits → NO-OP (no tag, no release, no changelog change)
  - If releasable:
      1. Bump version in pyproject.toml
      2. Update CHANGELOG.md
      3. Commit with [skip ci] (prevents infinite loop)
      4. Push annotated tag v{version}
      → tag triggers release.yml:
          1. Build Linux binary (build/build_binary.py)
          2. Verify binary version == released version
          3. Upload monday-linux + monday-linux.sha256 to GitHub Release
```

**Out of scope:** PyPI/package-index publishing. Binaries only.

### Files Managed by the Pipeline (Do Not Edit Manually)

| File | Managed by |
|------|------------|
| `pyproject.toml` `[project].version` | `python-semantic-release` |
| `CHANGELOG.md` | `python-semantic-release` |
| Git tags `v*.*.*` | `python-semantic-release` |

### Required Secret

`GH_TOKEN` — a PAT (classic) or GitHub App token with `Contents: write`. The default `GITHUB_TOKEN` cannot push to branch-protected `main`. See README.md "Release Bot Token Setup" for steps.

### CI Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `tests.yml` | push/PR | Unit tests (gate for release) |
| `commit-lint.yml` | PR | Enforces Conventional Commits |
| `semantic-release.yml` | push to main | Version bump + tag + changelog |
| `release.yml` | tag `v*.*.*` | Build + attach Linux binary |

## Reference

- Monday.com API: https://developer.monday.com/api-reference/reference/about-the-api-reference
- Column types: https://developer.monday.com/api-reference/docs/column-types-reference
- Version is defined **only** in `pyproject.toml`; `src/monday_cli/__init__.py` reads it via `importlib.metadata` at runtime. `CHANGELOG.md` is auto-generated by `python-semantic-release`. Releases are automated via `.github/workflows/semantic-release.yml` → `.github/workflows/release.yml`.
- Conventional Commits spec: https://www.conventionalcommits.org/
- python-semantic-release docs: https://python-semantic-release.readthedocs.io/
