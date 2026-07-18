/**
 * commitlint configuration for monday-cli
 *
 * Enforces the Conventional Commits specification:
 * https://www.conventionalcommits.org/
 *
 * This config mirrors the commit_parser settings in [tool.semantic_release]
 * in pyproject.toml so that what passes commit-lint is exactly what
 * python-semantic-release can parse for version bumps.
 *
 * Bump mapping (documented in sync with pyproject.toml):
 *   feat:              → minor bump  (new feature)
 *   fix: / perf:       → patch bump  (bug fix / performance)
 *   feat!: or BREAKING CHANGE: footer → major bump
 *   chore:/ci:/docs:/build:/style:/test:/refactor: → no version bump
 *
 * Usage examples:
 *   feat: add --all flag to items list for full pagination
 *   fix: handle 429 rate-limit response in GraphQL client
 *   feat!: rename --item to --item-id (BREAKING CHANGE: removes --item flag)
 *   chore: update CI Python version to 3.13
 *   docs: document Conventional Commits process in README
 */

export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // Allow longer subject lines (Monday CLI commit subjects can be verbose)
    'header-max-length': [1, 'always', 120],
    // Enforce lowercase type (feat, not Feat)
    'type-case': [2, 'always', 'lower-case'],
    // Allow these types (superset of conventional defaults)
    'type-enum': [
      2,
      'always',
      [
        'feat',      // new feature → minor bump
        'fix',       // bug fix → patch bump
        'perf',      // performance improvement → patch bump
        'chore',     // maintenance, no bump
        'ci',        // CI/CD changes, no bump
        'docs',      // documentation only, no bump
        'build',     // build system changes, no bump
        'style',     // formatting, no bump
        'test',      // test changes, no bump
        'refactor',  // code restructure, no bump
        'revert',    // revert a prior commit
      ],
    ],
  },
};
