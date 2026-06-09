# Contributing

Thanks for helping make the Harness CLI better.

## Local Setup

```bash
uv venv
uv pip install -e ".[dev]"
uv run python -m unittest
```

The CLI has no runtime dependencies. Keep new dependencies out unless they
remove meaningful complexity and are worth the installation cost.

## Endpoint Manifest

Endpoint commands are generated from the official Harness API docs:

```bash
python scripts/update_openapi_manifest.py
```

Commit generated changes together with the generator or runtime code that needs
them. If the upstream docs change in a way that removes endpoints, call that out
in the pull request.

## Pull Requests

Before opening a PR:

```bash
uv run python -m unittest
uv run python -m compileall -q src tests scripts
uv run ruff check .
```

If type-checking dependencies are installed, also run:

```bash
uv run mypy src/harness_cli
```

Please keep changes focused. Small, well-documented slices are much easier to
review than a giant mystery crate of enthusiasm.
