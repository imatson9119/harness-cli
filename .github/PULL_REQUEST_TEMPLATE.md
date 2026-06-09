## Summary

What changed, and why?

## CLI impact

- [ ] Adds or changes user-facing commands, flags, output, docs, or config behavior.
- [ ] Changes generated endpoint manifest or manifest generator behavior.
- [ ] No user-facing CLI behavior changed.

## Verification

Run the relevant checks before opening the PR:

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src/harness_cli
uv run python -m unittest
uv run python -m compileall -q src tests scripts
```

Paste any extra command output that proves the changed behavior, especially
`harness ... --dry-run` output for request-building changes.

## Endpoint manifest

If this PR refreshes `src/harness_cli/data/operations.json`, note:

- Harness docs source URL:
- Operation count before/after:
- Any removed or renamed groups/operations:
