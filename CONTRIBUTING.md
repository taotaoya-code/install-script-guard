# Contributing

## Reporting a problem

When opening an issue, include:

1. The output of `python3 isg.py <your-file> --format json`
2. The few lines of script that triggered the finding (with secrets removed)
3. Your Python version and operating system

If it is a **false positive**, put `false positive` in the title and explain why the code is actually safe. False positives are more urgent than misses — enough of them and people switch the whole tool off.

## Adding a rule

1. Add a `check_xxx(ctx) -> List[Finding]` function in `isg.py`. Keep it pure, no side effects.
2. Register it in the `RULES` list: `(rule_id, severity, title, function, category)`.
3. In `tests/test_rules.py`, write **two** cases: one that must match, one that must not.
4. Add a row to the rules table in the README.

Rule ids continue from `ISG011` upwards. Never reuse a retired number.

## Constraints every rule must respect

- **Deterministic first.** No LLM calls for detection. A judgement must be reproducible.
- **Zero dependencies.** No third-party packages.
- **Prefer missing a case over drowning users in false positives.** Noise gets the tool disabled.
- Every `Finding` must carry a `fix`. Flagging a problem without a direction is not useful.

## Pull requests

- One PR, one thing (a single rule, or a single bug).
- CI must be green: unit tests, self-audit, shellcheck.
- If you change rule behaviour, update the rules table in the README in the same PR.

## Development commands

```bash
python3 -m unittest discover -s tests -v
python3 isg.py . --repo owner/name
```
