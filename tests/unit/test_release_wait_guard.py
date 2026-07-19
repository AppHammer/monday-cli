"""Drift-guard: the release.yml "Wait for Release" loop must poll by exit code.

The FR-0017 bug was a *shell substring match*, not invalid YAML, so the FR-0011
actionlint gate legitimately passed it — actionlint cannot catch a
reintroduction. This token-free unit test parses
`.github/workflows/release.yml`, locates the "Wait for GitHub Release to exist"
step, and asserts the FR-0017 fix stays in place:

* the loop polls on `gh release view ... >/dev/null 2>&1`'s exit code
  (US-0017-02 AC2 / FRD AC-5),
* it never uses the substring-vulnerable `grep -q "found"` /
  `echo "found"|"not_found"` status idiom that broke on iteration 1
  (US-0017-02 AC2 — the exact FR-0017 regression signature),
* the loud final-failure check after the loop survives, so a genuinely-absent
  Release still fails the job (US-0017-02 AC4).

It lives in the `tests/unit` tier: no `MONDAY_API_TOKEN`, no network, never
skipped by the integration gate (US-0017-02 AC3). It parses the workflow with
`yaml.safe_load` rather than fragile line slicing, so it survives cosmetic
edits to release.yml (the FRD's cited line numbers are already stale).
"""

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"

WAIT_STEP_NAME = "Wait for GitHub Release to exist"


def _wait_step_run() -> str:
    """Return the `run` script of the wait-for-Release step in release.yml.

    Reads only ``jobs`` -> ``steps`` so it is unaffected by PyYAML 1.1 loading
    the ``on`` key as boolean ``True``.
    """
    doc = yaml.safe_load(WORKFLOW.read_text())
    for job in doc.get("jobs", {}).values():
        for step in job.get("steps", []):
            if step.get("name") == WAIT_STEP_NAME:
                return str(step["run"])
    raise AssertionError(f"'{WAIT_STEP_NAME}' step not found in {WORKFLOW}")


def test_wait_step_exists() -> None:
    """release.yml parses and contains the wait-for-Release step (AC1)."""
    run = _wait_step_run()
    assert run.strip(), "wait step has an empty run script"


def test_wait_step_polls_by_exit_code() -> None:
    """The loop polls on `gh release view` exit code, not stdout text (AC1)."""
    run = _wait_step_run()
    assert re.search(r"gh release view .*>/dev/null 2>&1", run), (
        "FR-0017: the wait loop must poll on `gh release view ... "
        ">/dev/null 2>&1` exit code, not on captured stdout text."
    )


def test_wait_step_has_no_substring_found_match() -> None:
    """The buggy `grep -q "found"` substring idiom must never return (AC2).

    ``"not_found"`` contains the substring ``"found"``, so `grep -q "found"`
    matches on iteration 1 and the loop breaks without ever waiting.
    """
    run = _wait_step_run()
    assert 'grep -q "found"' not in run, (
        "FR-0017 regression: the wait loop matches 'found' as a substring, "
        "which also matches 'not_found' and breaks on iteration 1 without "
        "waiting."
    )
    assert 'echo "not_found"' not in run, (
        'FR-0017 regression: the `echo "found"/"not_found"` status idiom '
        "that feeds the broken substring match has returned."
    )


def test_wait_step_still_fails_loudly() -> None:
    """A final absence-check after the loop keeps failing loudly (AC4).

    The fix must not mask a genuinely-absent Release: after the bounded poll,
    a final `gh release view` guarded by a non-zero exit must remain.
    """
    run = _wait_step_run()
    assert "exit 1" in run, (
        "FR-0017: the loud final-failure (exit 1) after the poll loop must be "
        "preserved so a truly-absent Release still fails the job."
    )
    # The final check must be a `gh release view` whose failure path exits 1
    # (via `|| { ... exit 1 }`), i.e. it is not merely the polling call.
    assert re.search(r"gh release view[^\n]*\n\s*\|\|", run) or "|| {" in run, (
        "FR-0017: expected a final `gh release view` guarded by a `|| { ... "
        "exit 1 }` failure block after the poll loop."
    )
