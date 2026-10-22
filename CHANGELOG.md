# Changelog

This project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-22

First usable release.

### Added

- 10 deterministic detection rules (`ISG001`–`ISG010`) covering: remote code piped into a shell, missing integrity verification, hard-coded repository owners, `releases/latest`, root execution of downloaded content, missing errexit, missing trap cleanup, `curl` without failure/timeout guards, unquoted variables in destructive deletes, and silent download failures.
- Four output formats: Markdown, JSON, SARIF 2.1.0, and a Codex prompt.
- `--repo owner/name` consistency check that reports a hard-coded owner differing from the current repository.
- `--exclude PATTERN` to skip paths by directory prefix or glob.
- `--fail-on high|medium|low|none` exit-code gate, usable directly as a CI merge condition.
- Composite GitHub Action (`action.yml`) with optional SARIF upload to Code Scanning.
- 43 unit tests, including a regression fixture taken from an installer that was actually deployed.
- CI matrix: Ubuntu / Windows / macOS × Python 3.8 / 3.12, plus self-audit and shellcheck.

### Known limitations

- Static text analysis only; no cross-file data-flow tracking.
- Dynamic construction such as `eval "$(...)"` is not detected.
