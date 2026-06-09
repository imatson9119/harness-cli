# Harness CLI

`harness` is an OpenAPI-backed command line interface for the Harness Software
Delivery Platform APIs.

The CLI is generated from the public Harness API reference at
<https://apidocs.harness.io/>. The current manifest includes every operation
published in the Redocly OpenAPI shared data bundle that is practical to expose
through a generic CLI caller.

## Install

```bash
uv venv
uv pip install -e .
```

Then run:

```bash
harness --help
```

## Onboarding

Run the interactive onboarding flow:

```bash
harness init
```

The flow stores configuration in `~/.config/harness/config.json` by default and
sets file permissions to `0600`. Config is profile-based, so you can keep
multiple Harness accounts or projects handy:

```bash
harness init --profile prod
harness init --profile sandbox
harness profile use prod
harness profile list
```

You can also use environment variables:

```bash
export HARNESS_HOST=https://app.harness.io
export HARNESS_API_KEY=your-token
export HARNESS_PROFILE=prod
export HARNESS_ACCOUNT=your-account-id
export HARNESS_ORG=optional-org-id
export HARNESS_PROJECT=optional-project-id
```

Harness authenticates API calls with the `x-api-key` header. When an endpoint
requires the Harness account header, `--account` or the active profile account
is sent as `Harness-Account`.

## Endpoint Commands

List generated operations:

```bash
harness api list --search pipeline
harness api list --tag "Account Roles"
```

Describe an operation:

```bash
harness api describe list-roles-acc
```

Descriptions include parameter defaults, enum hints, docs links, pagination
support, and pasteable examples.

Call an operation through the stable API dispatcher:

```bash
harness api call list-roles-acc --query limit=10
```

Call the same operation through its generated group shortcut:

```bash
harness account-roles list-roles-acc --limit 10
```

Render JSON list responses as a table when you want a compact human view:

```bash
harness account-roles list-roles-acc --limit 10 --output table
```

Fetch paginated list endpoints until they are exhausted:

```bash
harness account-roles list-roles-acc --all --all-page-size 100 --output table
```

Preview the request without sending it:

```bash
harness account-roles list-roles-acc --limit 10 --dry-run
```

Send JSON request bodies from a file:

```bash
harness project-services create-service --org my-org --project my-project --body @service.json
```

Upload multipart files for file-oriented endpoints:

```bash
harness artifact-signing upload-signature \
  --org my-org \
  --project my-project \
  --form note=release \
  --file signature=@signature.json
```

Save binary responses:

```bash
harness file-store download-file --identifier readme --output-file readme.md
```

## Shell Completion

Print completion scripts for supported shells:

```bash
harness completion bash
harness completion zsh
harness completion fish
```

## Terminal Experience

Interactive terminals get colorized tables, highlighted JSON, and a live status
indicator while API calls are in flight. Scripts still get clean output:
command data goes to stdout, while status and saved-file messages go to stderr.

Controls:

```bash
NO_COLOR=1 harness api list
HARNESS_COLOR=always harness api list
HARNESS_ANIMATION=never harness account-roles list-roles-acc --limit 10
HARNESS_ASCII=1 harness account-roles list-roles-acc --limit 10
```

## Useful Commands

```bash
harness doctor
harness auth status
harness profile list
harness profile use prod
harness config list
harness config set account acc_123
harness api info
harness api groups
```

## Development

Refresh the generated endpoint manifest from Harness API docs:

```bash
uv run python scripts/update_openapi_manifest.py
```

Run the standard library test suite:

```bash
uv run python -m unittest
```

Install development tooling and run checks:

```bash
uv pip install -e ".[dev]"
uv run ruff format .
uv run ruff check .
uv run mypy src/harness_cli
uv run python scripts/validate_openapi_manifest.py
uv run python -m compileall -q src tests scripts
uv build --sdist --wheel
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/architecture.md](docs/architecture.md) for the project shape.
