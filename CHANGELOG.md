# CHANGELOG


## v0.6.2 (2026-07-19)

### Bug Fixes

- Bundle rich._unicode_data so --table works in the frozen binary (FR-0007)
  ([#62](https://github.com/AppHammer/monday-cli/pull/62),
  [`23828d9`](https://github.com/AppHammer/monday-cli/commit/23828d9747eb55fde37bcf654630f293293493e8))

PyInstaller --collect-submodules=rich._unicode_data + hermetic build guard + release.yml --table
  regression guard.

Closes #46, closes #47

- **output**: Route diagnostic output to stderr, guarantee clean JSON stdout (FR-0008)
  ([#63](https://github.com/AppHammer/monday-cli/pull/63),
  [`4d82a87`](https://github.com/AppHammer/monday-cli/commit/4d82a8777037997a5826dcb2ad67848611bf5867))

CLI-wide clean-stdout contract: secho_err/eprint helpers, all diagnostics to stderr, empty-result
  JSON, stdout-contract AST guard + integration tests.

Closes #37, closes #48, closes #49, closes #50, closes #51, closes #52, closes #53, closes #54


## v0.6.1 (2026-07-18)

### Bug Fixes

- Reliable large-document writes to Monday doc columns (FR-0005)
  ([#55](https://github.com/AppHammer/monday-cli/pull/55),
  [`ab372ea`](https://github.com/AppHammer/monday-cli/commit/ab372eaaabedb195935e545ef383878b0eb8283a))

Safe large put (preflight/chunking + per-request timeout), idempotent put/append, block-order +
  timeout hardening, docs clear/reset, lossless docs get blocks. Live-QA'd on the test board;
  reviewed + fix-looped.

Closes #32, closes #33, closes #34, closes #35, closes #36, closes #38


## v0.6.0 (2026-07-18)

### Documentation

- Point dev flow at /implement-feature (QA + code review)
  ([#29](https://github.com/AppHammer/monday-cli/pull/29),
  [`393001b`](https://github.com/AppHammer/monday-cli/commit/393001bfaac71d44e3b87c36bd0d03d180eef021))

Clarify the strict development flow in CLAUDE.md: use /implement-feature --label to work on issues,
  which always runs QA and then code review, rather than /implement-issue.

Co-authored-by: Michael Fudge <mafudge@gmail.com>

Co-authored-by: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### Features

- Agent self-discovery meta-commands — monday guide / guide --json / skill.md (Closes #1-#7)
  ([#24](https://github.com/AppHammer/monday-cli/pull/24),
  [`5ad0283`](https://github.com/AppHammer/monday-cli/commit/5ad0283f823523d57fea8196fff4678495b658ca))

* feat: monday guide + skill.md discovery meta-commands (Closes #1, #2, #3, #4)

Introspect the live Typer/Click app into a structured command model and add top-level agent
  self-discovery commands that consume it:

- utils/introspection.py: pure, side-effect-free walk of the assembled root app into groups ->
  commands -> params (name, kind, type, required, default, help). Duck-typed so it is robust across
  Typer versions that vendor their own Click. - monday guide: single-shot prose usage guide
  (authored preamble + a command listing generated from the model). - monday guide --json: full
  command tree as machine-readable JSON via print_json. - monday skill.md (+ monday guide --skill
  alias): thin SKILL.md generator whose body points back at `monday guide`; the CLI stays the single
  source of truth.

Registered on the root app alongside `version`, added to the order-sensitive bottom-of-file command
  import in cli.py.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

* test+ci: unit tests, drift guard, and pytest CI workflow (Closes #5, #6)

- tests/unit/test_introspection.py: asserts the model enumerates all 8 groups, known subcommands,
  and populated parameter metadata. - tests/unit/test_guide.py: verifies guide prose sections,
  valid/complete --json output, and the skill.md frontmatter + guide --skill alias. -
  tests/unit/test_guide_drift.py: drift guard — every command enumerated from the introspection
  model must appear in both `monday guide` and `monday guide --json`, so the outputs can never fall
  out of sync. - .github/workflows/tests.yml: repo's first test CI — installs the package with dev
  deps and runs pytest on push and PR against Python 3.11.

* docs: name `monday guide` as PRIMARY discovery, document 3-layer model (Closes #7)

README.md and CLAUDE.md now lead with `monday guide` as the primary discovery mechanism and describe
  the three-layer model (guide -> --help -> skill.md), noting the CLI is the single source of truth
  (no hand-maintained SKILL.md in-repo; it is emitted on demand).

* [code-review-fix] tests/unit/test_guide_drift.py: harden prose drift-guard to match whole command
  tokens

Substring matching let a dropped `list` command false-pass because `items list` is itself a
  substring of `items list-columns`. Match with word/hyphen boundary lookarounds instead so a
  same-prefixed sibling command can no longer stand in for the real one. Verified the guard now
  genuinely fails when a `list` command is dropped from the prose listing, then reverted the
  temporary drop.

* [code-review-fix] src/monday_cli/utils/introspection.py: guard _build_param against
  non-JSON-serializable defaults

Only callables were normalized before; a future Enum/Path/datetime/set/ Ellipsis default would flow
  into json.dumps and raise TypeError, breaking the "guide --json is always valid JSON" acceptance
  criterion. Add _json_safe_default() to pass JSON primitives through unchanged and stringify
  anything else.

* [code-review-fix] src/monday_cli/utils/introspection.py: split command help into full (JSON) vs
  short (prose)

_command_help embedded the full collapsed docstring in the prose listing too, producing noisy
  one-liners for commands with multi-paragraph docstrings. Add short_help (first paragraph only) to
  CommandModel and have guide.py's prose renderer use it, while guide --json keeps emitting the full
  help unchanged.

* [code-review-fix] src/monday_cli/utils/introspection.py: skip hidden commands and params during
  the walk

The introspection walk had no hidden filter, so a hidden=True command or param would surface in
  guide / guide --json. Skip hidden top-level commands, hidden group sub-commands, and hidden params
  so a deliberately hidden command is never advertised in discovery output.

* [code-review-fix] .github/workflows/tests.yml: scope pytest step to tests/unit

Bare pytest also collects tests/integration, which is empty today but will hold FR-0002's live-board
  tests requiring MONDAY_API_TOKEN. Scope CI to tests/unit so those don't break CI once they land.

* [code-review-fix] .github/workflows/tests.yml: scope push trigger to main and add concurrency
  group

push (all branches) plus pull_request double-ran CI on every PR branch. Limit push to main (+ v*
  tags) and add a concurrency group keyed on the ref with cancel-in-progress so in-flight runs on
  the same ref don't race.

* [code-review-fix] build/build_binary.py: use --optimize=1 to keep docstrings

--optimize=2 (-OO) strips docstrings, which Typer/Click derive command help from, leaving `monday
  guide` / `guide --json` help blank in the shipped binary (24 commands with null help). Level 1
  (-O) still drops asserts but preserves docstrings. Verified rebuilt binary: 0 commands with empty
  help.

---------

Co-authored-by: Michael Fudge <mafudge@gmail.com>

Co-authored-by: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- Ci-based automated release management with Conventional Commits (FR-0003)
  ([#31](https://github.com/AppHammer/monday-cli/pull/31),
  [`5993900`](https://github.com/AppHammer/monday-cli/commit/5993900ed7946d83ceac35a0f78108cd266bdf50))

python-semantic-release automation + commit-lint + refactored binary release; major_on_zero=false
  (0.x breaking => minor).

Closes #10, closes #11, closes #13, closes #14, closes #15, closes #23

- Docs get emits deterministic JSON by default; add --raw/--markdown
  ([#28](https://github.com/AppHammer/monday-cli/pull/28),
  [`a6fec0e`](https://github.com/AppHammer/monday-cli/commit/a6fec0e9cbdbc4267832e28f297c008681baba0e))

docs get now returns a lossless {markdown, blocks} JSON object via print_json; --raw/--markdown emit
  rendered Markdown. Closes #25, #26, #27.

BREAKING CHANGE: 'monday docs get' default output changed from Markdown to JSON. Use --raw (or
  --markdown) for the previous rendered-Markdown behavior.

- **FR-0002**: Live integration test suite + secret-gated CI (Closes #12,#16-#22)
  ([#30](https://github.com/AppHammer/monday-cli/pull/30),
  [`d1b2eef`](https://github.com/AppHammer/monday-cli/commit/d1b2eeffc4936b736bb5b9171c4a0ad947d39629))

* [issue-12] integration harness: conftest, helpers, factory fixtures + board guard

Adds the shared tests/integration/ harness (US-0002-01) that the six resource suites (#16-#21) and
  the CI job (#22) build on:

- helpers.run_cli(): in-process CliRunner invocation by default, with MONDAY_CLI_BIN opt-in to exec
  the packaged binary; extracts the JSON payload even when a human secho line precedes it on stdout,
  and supports raw=True / expect_error=True. - conftest.py: test_board_id (defaults to the scratch
  board 18422673411, hard-fails via pytest.fail if ever resolved to the PM board), an autouse skip
  gate on MONDAY_API_TOKEN, a session-scoped run_id suffix, and
  created_group/created_item/created_subitem factory fixtures that create-then-track-then-delete
  artifacts in teardown (idempotent, failure-safe even when the test body raises). -
  test_harness.py: meta-tests proving the board guard, the failure-safe teardown (via a forced
  xfail(strict=True) failure + an adjacent residue check), and run_cli's JSON-vs-raw contract. -
  pyproject.toml: registers the `integration` pytest marker.

Verified live against the test board: ruff/black clean on the new files, mypy src still at its
  pre-existing baseline, unit suite passes, `pytest -m integration --collect-only` selects the new
  tests, and two consecutive live runs of test_harness.py leave zero residual artifacts.

* test(integration): resource suites for workspaces/boards/statuses, groups, items, subitems,
  updates, docs

Add the live integration suites built on the US-0002-01 harness, all marked @pytest.mark.integration
  and targeting the test board 18422673411:

- test_workspaces/boards/statuses.py (#16): read/list + filter coverage, --table smoke checks -
  test_groups.py (#17): groups create/list/delete with color + residue check - test_items.py (#18):
  items CRUD, pagination contract, group filtering, list-columns - test_subitems.py (#19): subitems
  CRUD, list-columns, list-statuses, board pagination - test_updates.py (#20): updates create on
  item and subitem + read-back round-trip - test_docs.py (#21): docs put/append/put round-trip with
  block-order assertions

All run-scoped via run_id with failure-safe teardown; 42 integration tests collect cleanly; unit
  suite + ruff + black remain green.

Closes #16 Closes #17 Closes #18 Closes #19 Closes #20 Closes #21

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01EQZkG1JAcnmizVKdBGQY2D

* ci(integration): per-PR secret-gated workflow for the live integration suite

Add .github/workflows/integration.yml (US-0002-08). Runs `pytest tests/integration -m integration`
  against the shared TEST board on every pull_request (plus workflow_dispatch), serialized through a
  single `monday-integration` concurrency group with cancel-in-progress: false so overlapping PRs
  queue instead of colliding on the board.

- Gated on the MONDAY_API_TOKEN repo secret: forked PRs are filtered by the job `if` (no secret
  access) and never fail; same-repo runs without the secret skip cleanly via an early gate step
  (exit 0). - MONDAY_TEST_BOARD_ID defaults to 18422673411, overridable via a repo var. - Documents
  local + CI integration-test setup and the required secret in README.md and CLAUDE.md; adds
  MONDAY_TEST_BOARD_ID to the env-var table.

Independent of tests.yml (unit) and release.yml.

Closes #22

* [code-review-fix] test_docs.py: satisfy mypy no-any-return on column title lookup

* [code-review-fix] test_boards.py: annotate _board_ids with dict[str, Any] to satisfy mypy type-arg

* [code-review-fix] helpers.py: surface CliRunner exception on unexpected non-zero exit

In-process invocations that crash with an unhandled exception previously raised a bare "exited N,
  expected 0" assertion with empty stdout, since Typer's CliRunner captures the traceback on
  result.exception rather than stdout. run_cli now includes the exception repr/traceback in the
  failure message when expect_error=False, so a crashing command produces an actionable failure
  instead of a cryptic empty-output assertion. The JSON/raw return contract and expect_error
  semantics are unchanged.

* [code-review-fix] test_harness.py: paginate full board with --all in residue check

--limit 500 would produce a false negative if the scratch board ever grows past 500 items (the
  deleted item could be "absent" only because it fell past the page). --all paginates the whole
  board instead; cost is negligible on the small scratch board. Still raw=True.

---------

Co-authored-by: Michael Fudge <mafudge@gmail.com>

Co-authored-by: Claude Opus 4.8 (1M context) <noreply@anthropic.com>


## v0.5.0 (2026-02-17)


## v0.4.0 (2026-02-17)


## v0.3.0 (2026-02-15)


## v0.2.0 (2026-02-15)


## v0.1.2 (2026-01-15)


## v0.1.1 (2026-01-14)


## v0.1.0 (2026-01-14)
