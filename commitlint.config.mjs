/**
 * Conventional Commits, enforced on commit-msg and re-checked in CI.
 * Types and scopes mirror docs/12-repository-standards.md §3.
 */
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      [
        "feat",
        "fix",
        "docs",
        "style",
        "refactor",
        "perf",
        "test",
        "build",
        "ci",
        "chore",
        "revert",
      ],
    ],
    "scope-enum": [
      2,
      "always",
      ["api", "web", "db", "auth", "biometrics", "docs", "infra", "deps", "shared"],
    ],
    "scope-empty": [1, "never"],
    "subject-case": [2, "always", "lower-case"],
    "subject-full-stop": [2, "never", "."],
    "header-max-length": [2, "always", 72],
    "body-max-line-length": [1, "always", 100],
  },
};
