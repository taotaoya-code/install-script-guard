# install-script-guard

> Deterministic supply-chain audit for `curl | bash` style install scripts.
> Zero dependencies, single file, works offline.

[![CI](https://github.com/taotaoya-code/install-script-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/taotaoya-code/install-script-guard/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.8%2B-blue)
![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![license](https://img.shields.io/badge/license-MIT-blue)

[中文说明](README.zh-CN.md)

---

## Why this exists

One-line installers are everywhere: `bash <(curl -fsSL ...)`. They all share the same flaw — **execution happens before verification**.

A real example, taken from a script I maintain (not a hypothetical):

```bash
RELEASE_REPO="${VPS_RELEASE_REPO:-oldaccount/vps-benchmark-public}"
RELEASE_TAG="${VPS_RELEASE_TAG:-}"
if [[ -n "$RELEASE_TAG" ]]; then
  BASE_URL="https://github.com/${RELEASE_REPO}/releases/download/${RELEASE_TAG}"
else
  BASE_URL="https://github.com/${RELEASE_REPO}/releases/latest/download"
fi
curl -fL "${BASE_URL}/${ASSET_TGZ}" -o "${TMP_DIR}/${ASSET_TGZ}"
```

Three separate failures, each of which breaks the install silently:

1. **A hard-coded owner.** The account was renamed; the old name only works because GitHub keeps a 301 redirect alive. Once that redirect is reclaimed, every command already distributed to users dies at once, with no error message.
2. **`releases/latest`.** The same script installs different versions on different days. User bug reports become unreproducible.
3. **The release never existed.** The upstream never published that asset. Users only see curl's raw error.

None of this is theoretical. `isg` turns these into things CI can block.

## Quick start

```bash
git clone https://github.com/taotaoya-code/install-script-guard
cd install-script-guard

# scan the current directory
python3 isg.py .

# scan specific scripts, declaring the current repo for consistency checks
python3 isg.py install.sh scripts/*.sh --repo owner/name

# only high severity, machine readable
python3 isg.py . --fail-on high --format json
```

No `pip install` needed. On Windows use `python isg.py`.

## Rules

| Rule | Severity | What it detects |
|---|---|---|
| `ISG001` | high | Network content piped directly into a shell (`curl \| bash`, `bash <(curl ...)`) |
| `ISG002` | high | Archive downloaded, but no sha256 verification anywhere in the file |
| `ISG003` | high | Hard-coded owner differs from the current repo (silent break after a rename); medium without `--repo` |
| `ISG004` | medium | A `releases/latest` branch exists (low when `RELEASE_TAG` can override it) |
| `ISG005` | high | Requires root, then executes content just fetched from the network |
| `ISG006` | medium | Missing errexit (`set -e`); low when `-e` is set but `pipefail` is not |
| `ISG007` | low | `mktemp` used without a `trap` cleanup |
| `ISG008` | medium | `curl` missing `-f` (404 saved as success) or `--max-time` |
| `ISG009` | medium | `rm -rf` on an unquoted variable |
| `ISG010` | low | Downloads from a release but has no explicit "asset not found" message |

Every rule is an independent function in the `RULES` list inside `isg.py`, so it can be tested or replaced in isolation.

## Use it in CI

```yaml
name: install-script-audit
on: [pull_request]

jobs:
  isg:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: taotaoya-code/install-script-guard@v0.1.0
        with:
          paths: "."
          fail-on: high         # block the PR on high severity findings
          format: sarif
          upload-sarif: "true"  # surface results in Code Scanning
```

Report only, never block: `fail-on: none`.

Findings show up as annotations on the changed lines in the PR's Files changed tab when `format: sarif` and `upload-sarif: "true"`.

## Output formats

Four renderers, one engine:

| `--format` | Purpose |
|---|---|
| `md` (default) | Human-readable table plus fix suggestions |
| `json` | For scripts and other tooling |
| `sarif` | GitHub Code Scanning; annotates lines in the PR diff |
| `codex` | Emits a constrained prompt for Codex to turn into patches |

### Working with Codex

`--format codex` produces a task brief with explicit constraints: cite file and line, give an applicable diff, do not introduce new dependencies, and state the reasoning when a finding is a false positive.

```bash
python3 isg.py . --format codex > /tmp/isg-prompt.md
codex exec "$(cat /tmp/isg-prompt.md)"
```

The split is deliberate: **the deterministic rules decide whether a problem exists; Codex only explains and writes the patch.** Letting a model judge "is this vulnerable" is not reliable, so it never gets that vote.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Nothing at or above the `--fail-on` threshold |
| `1` | At least one finding at or above the threshold |

`--fail-on` accepts `high` (default), `medium`, `low`, `none`.

## Design trade-offs

- **Zero dependencies.** Standard library only. Nothing to install in CI, works offline. An audit tool should not itself become a supply-chain risk.
- **Single-file core.** `isg.py` runs standalone, so it can be copied into another repo as a script.
- **Rules, not models.** Detection is regex and structural parsing. False-positive rate is measurable and results are reproducible, with no API key involved.
- **No auto-fix.** It reports only. Rewriting someone else's installer automatically is too risky; fixes go to a human or to Codex.

## Limitations (stated plainly)

- **Static text analysis only.** No shell semantics, no cross-file data-flow tracking (a variable assigned in file A and used in file B is not followed).
- **Misses dynamic construction.** Heavily obfuscated or `eval "$(...)"`-built scripts will slip through.
- **Known patterns, not complete vulnerability detection.** It catches common failure modes, not all attacks.
- **`--repo` consistency checking depends on the value passed in.** In CI, use `${{ github.repository }}` for it to mean anything.

## Development

```bash
python3 -m unittest discover -s tests -v
```

The suite includes a real fixture: `tests/fixtures/real-vps-benchmark-quick-install.sh` is an installer that was actually deployed. CI asserts it triggers at least one high severity finding — so the rules are proven against real code, not just toy samples.

Current status: 43 tests, passing on Ubuntu / Windows / macOS across Python 3.8 and 3.12.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). A new rule needs two tests: one that must match, one that must not.

## License

MIT — see [LICENSE](LICENSE).
