# Harness CLI

`harness` is a polished, OpenAPI-backed command line interface for the Harness
Software Delivery Platform APIs.

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
harness init --profile prod --output table
harness init --profile sandbox
harness profile use prod
harness profile list
```

Onboarding asks for host, API key, account, org, project, and default output
mode. Host values must be full `http://` or `https://` URLs. Use
`--non-interactive` with flags when scripting setup.

Use global options when you want one command to use a different profile or
config file without changing your active setup:

```bash
harness --profile prod doctor
harness --config ./harness.config.json auth status
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
is sent as `Harness-Account`. Profile account, org, and project values are also
used for common generated endpoint parameter spellings such as
`accountIdentifier`, `accountId`, `account_id`, `orgIdentifier`,
`organizationIdentifier`, `projectIdentifier`, and snake-case registry
identifiers.

## Endpoint Commands

List generated operations:

```bash
harness api list --search pipeline
harness api list --search role --wide
harness api groups --search pipeline --limit 20
harness api list --tag "Account Roles"
harness api list --group account-roles --has-body
harness api list --method post --path /v1/roles
```

Describe an operation:

```bash
harness api describe list-roles-acc
```

Descriptions include parameter defaults, enum hints, docs links, pagination
support, and pasteable examples.

Print a request-body template for create/update operations:

```bash
harness api body create-role-acc > role.json
harness api body create-account-scoped-connector --content-type application/yaml > connector.yaml
harness api body create-role-acc --output-file role.json
harness api body create-role-acc --json
```

JSON templates are pretty-printed as JSON. YAML and other text templates are
printed as editable raw text; add `--json` when you want metadata such as the
selected content type wrapped around the body.

Call an operation through the stable API dispatcher:

```bash
harness api call --help
harness api call list-roles-acc --help
harness api call list-roles-acc --query limit=10 --help
harness api call list-roles-acc --query limit=10
```

Call the same operation through its generated group shortcut:

```bash
harness account-roles list-roles-acc --limit 10
```

Use `--host https://custom.example.com` for one-off calls against another
Harness base URL. Like saved hosts, per-call host overrides must be full
`http://` or `https://` URLs without query strings or fragments.

Render JSON list responses as a table when you want a compact human view:

```bash
harness account-roles list-roles-acc --limit 10 --output table
harness account-roles list-roles-acc --limit 10 --output table --columns identifier,name,createdAt
```

Fetch paginated list endpoints until they are exhausted:

```bash
harness account-roles list-roles-acc --all --all-page-size 100 --output table
```

`--all` recognizes the common pagination shapes in the generated Harness
manifest, including page, offset, and cursor-style query parameters.

Preview the request without sending it:

```bash
harness account-roles list-roles-acc --limit 10 --dry-run
harness account-roles list-roles-acc --limit 10 --curl
```

Preview output redacts `x-api-key`, `Authorization`, and common token/secret
style headers so requests are easier to share safely.

Send JSON request bodies from a file:

```bash
harness project-services create-service --org my-org --project my-project --body @service.json
harness project-services create-service --org my-org --project my-project --body-json @service.json
harness api call create-role-acc --body-template --dry-run
```

Use `--body-json` for inline JSON, `@file`, or `-` stdin when you want the CLI
to validate the payload before sending it. Use `--body-template` to send the
generated JSON or YAML request-body sample for an operation; pair it with
`--dry-run` first when exploring a new endpoint.

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

Interactive terminals get colorized tables, highlighted JSON, Unicode table
frames, and a live status indicator while API calls are in flight. Scripts
still get clean output: command data goes to stdout, while status, saved-file
messages, and clean transport errors go to stderr. HTTP 4xx/5xx responses
return exit code `1` and still render the response body so scripts can inspect
it.

Controls:

```bash
NO_COLOR=1 harness api list
HARNESS_COLOR=always harness api list
HARNESS_ANIMATION=never harness account-roles list-roles-acc --limit 10
HARNESS_STATUS=never harness account-roles list-roles-acc --limit 10
HARNESS_TABLE_STYLE=unicode harness account-roles list-roles-acc --output table
HARNESS_TABLE_STYLE=plain harness account-roles list-roles-acc --output table
HARNESS_ASCII=1 harness account-roles list-roles-acc --limit 10
```

Use `HARNESS_ANIMATION=never` to keep the final status line without live
motion. Use `HARNESS_STATUS=never` when you want no call status on stderr.

## Useful Commands

```bash
harness doctor
harness --profile prod doctor
harness doctor --fix-permissions
harness doctor --network
harness auth status
harness profile list
harness profile use prod
harness config list
harness config set account acc_123
harness config set default_output table
harness api info
harness api groups
harness api body create-role-acc
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
