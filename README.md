# hctl

`hctl` is a polished, OpenAPI-backed command line interface for the Harness
Software Delivery Platform APIs.

The CLI is generated from the public Harness API reference at
<https://apidocs.harness.io/>. The current manifest includes every operation
published in the Redocly OpenAPI shared data bundle that is practical to expose
through a generic CLI caller.

## Install

Install the latest code from Git with `uv`:

```bash
uv tool install git+https://github.com/imatson9119/harness-cli.git
hctl --help
```

After the first PyPI release, the shortest install path is:

```bash
uv tool install hctl
```

The curl installer prefers the latest GitHub Release artifact and falls back to
the Git install path when no release artifact is available:

```bash
curl -fsSL https://raw.githubusercontent.com/imatson9119/harness-cli/main/install.sh | sh
```

Other supported channels:

```bash
pipx install hctl
brew tap imatson9119/tap && brew install hctl
curl -fsSLO https://github.com/imatson9119/harness-cli/releases/latest/download/hctl.pyz
chmod +x hctl.pyz
./hctl.pyz --help
```

See [docs/distribution.md](docs/distribution.md) for upgrade, uninstall,
release, Homebrew, PyPI, and standalone artifact details.

Upgrade and remove common installs:

```bash
uv tool upgrade hctl
uv tool uninstall hctl
brew upgrade hctl
brew uninstall hctl
rm ~/.local/bin/hctl
```

## Onboarding

Run the interactive onboarding flow:

```bash
hctl init
```

The flow stores configuration in `~/.config/hctl/config.json` by default and
sets file permissions to `0600`. Config is profile-based, so you can keep
multiple Harness accounts or projects handy:

```bash
hctl init --profile prod --output table
hctl init --profile sandbox
hctl config profile use prod
hctl config profile list
```

Onboarding asks for host, API key, account, org, project, and default output
mode. API key is required for authenticated Harness calls. Host has a default,
and account, org, project, and default output are optional conveniences you can
add or change later. Host values must be full `http://` or `https://` URLs. Use
`--non-interactive` with flags when scripting setup.

Non-default profiles inherit the default profile's API key when they do not set
their own. This keeps scripted or agent-created profiles simple: store the API
key once in `default`, then create narrower profiles for account, org, project,
or custom operation variables. Set `api_key` on a profile when it targets a
different Harness host or needs different access.

Use global options when you want one command to use a different profile or
config file without changing your active setup:

```bash
hctl --profile prod doctor
hctl --config ./harness.config.json auth status
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

Profiles can also store custom scalar variables:

```bash
hctl config set pipelineIdentifier release_pipeline
hctl config set serviceIdentifier checkout_service
```

When a custom key exactly matches a generated path, query, or header parameter
for the operation you call, hctl fills that parameter automatically. Explicit
flags such as `--pipeline-identifier`, `--param pipelineIdentifier=...`, or
`--query pipelineIdentifier=...` still win for that call.

## Endpoint Commands

List generated operations:

```bash
hctl api list --search pipeline
hctl api list --search role --wide
hctl api groups --search pipeline --limit 20
hctl api list --tag "Account Roles"
hctl api list --group account-roles --has-body
hctl api list --method post --path /v1/roles
```

Search is ranked from a bundled offline vector index, so natural phrases and
small typos such as `piplne execution` work without extra dependencies or
network calls.

Describe an operation:

```bash
hctl api describe list-roles-acc
```

Descriptions include parameter defaults, enum hints, docs links, pagination
support, and pasteable examples.

Print a request-body template for create/update operations:

```bash
hctl api body create-role-acc > role.json
hctl api body create-account-scoped-connector --content-type application/yaml > connector.yaml
hctl api body create-role-acc --output-file role.json
hctl api body create-role-acc --json
```

JSON templates are pretty-printed as JSON. YAML and other text templates are
printed as editable raw text; add `--json` when you want metadata such as the
selected content type wrapped around the body.

Call an operation through the stable API dispatcher:

```bash
hctl api call --help
hctl api call list-roles-acc --help
hctl api call list-roles-acc --query limit=10 --help
hctl api call list-roles-acc --query limit=10
```

Call the same operation through its generated group shortcut:

```bash
hctl account-roles list-roles-acc --limit 10
```

Use `--host https://custom.example.com` for one-off calls against another
Harness base URL. Like saved hosts, per-call host overrides must be full
`http://` or `https://` URLs without query strings or fragments.

Render JSON list responses as a table when you want a compact human view:

```bash
hctl account-roles list-roles-acc --limit 10 --output table
hctl account-roles list-roles-acc --limit 10 --output table --columns identifier,name,createdAt
hctl pipeline list-pipelines --output table --columns data.content[].identifier,data.content[].name
hctl pipeline list-pipelines --unwrap --jq content[] --output table --columns identifier,name
```

`--unwrap` removes Harness envelopes shaped like `{status, data, correlationId}`.
`--jq path` applies a small built-in jq-style selector with dotted fields and
`[]` array unwrapping. Table columns use the same path language, so nested
Harness payloads such as `data.content[].name` work without piping through an
external tool.

Fetch paginated list endpoints until they are exhausted:

```bash
hctl account-roles list-roles-acc --all --all-page-size 100 --output table
```

`--all` recognizes the common pagination shapes in the generated Harness
manifest, including page, offset, and cursor-style query parameters.

Preview the request without sending it:

```bash
hctl account-roles list-roles-acc --limit 10 --dry-run
hctl account-roles list-roles-acc --limit 10 --curl
```

Preview output redacts `x-api-key`, `Authorization`, and common token/secret
style headers so requests are easier to share safely.

Send JSON request bodies from a file:

```bash
hctl project-services create-service --org my-org --project my-project --body @service.json
hctl project-services create-service --org my-org --project my-project --body-json @service.json
hctl api call create-role-acc --body-template --dry-run
```

Use `--body-json` for inline JSON, `@file`, or `-` stdin when you want the CLI
to validate the payload before sending it. Use `--body-template` to send the
generated JSON or YAML request-body sample for an operation; pair it with
`--dry-run` first when exploring a new endpoint.

Upload multipart files for file-oriented endpoints:

```bash
hctl artifact-signing upload-signature \
  --org my-org \
  --project my-project \
  --form note=release \
  --file signature=@signature.json
```

Save binary responses:

```bash
hctl file-store download-file --identifier readme --output-file readme.md
```

## Shell Completion

Print completion scripts for supported shells:

```bash
hctl completion bash
hctl completion zsh
hctl completion fish
```

Install completions:

```bash
mkdir -p ~/.local/share/bash-completion/completions
hctl completion bash > ~/.local/share/bash-completion/completions/hctl
mkdir -p ~/.zfunc
hctl completion zsh > ~/.zfunc/_hctl
mkdir -p ~/.config/fish/completions
hctl completion fish > ~/.config/fish/completions/hctl.fish
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
NO_COLOR=1 hctl api list
HARNESS_COLOR=always hctl api list
HARNESS_ANIMATION=never hctl account-roles list-roles-acc --limit 10
HARNESS_STATUS=never hctl account-roles list-roles-acc --limit 10
HARNESS_TABLE_STYLE=unicode hctl account-roles list-roles-acc --output table
HARNESS_TABLE_STYLE=plain hctl account-roles list-roles-acc --output table
HARNESS_ASCII=1 hctl account-roles list-roles-acc --limit 10
```

Use `HARNESS_ANIMATION=never` to keep the final status line without live
motion. Use `HARNESS_STATUS=never` when you want no call status on stderr.

## Useful Commands

```bash
hctl doctor
hctl --profile prod doctor
hctl doctor --fix-permissions
hctl doctor --network
hctl auth status
hctl config profile list
hctl config profile use prod
hctl config list
hctl config set account acc_123
hctl config set pipelineIdentifier release_pipeline
hctl config set default_output table
hctl api info
hctl api groups
hctl api body create-role-acc
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
uv venv
uv pip install -e ".[dev]"
uv run ruff format .
uv run ruff check .
uv run mypy src/harness_cli
uv run python scripts/validate_openapi_manifest.py
uv run python -m compileall -q src tests scripts
uv build --sdist --wheel
uv run python scripts/build_standalone.py
```

Install commit-time formatting hooks:

```bash
uv run --extra dev pre-commit install
uv run --extra dev pre-commit run --all-files
```

The hooks use `uv run --frozen --extra dev ruff format` and
`uv run --frozen --extra dev ruff check --fix` so everyday commits get the same
formatter and autofix behavior as CI.

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/architecture.md](docs/architecture.md) for the project shape.
