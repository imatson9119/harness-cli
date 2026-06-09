# Command Reference

## Top Level

```bash
harness --help
harness --profile prod doctor
harness --config ./harness.config.json auth status
harness init
harness doctor
harness doctor --network
harness auth status
harness profile list
harness config list
harness api info
harness api body create-role-acc
harness api list
harness completion zsh
```

## Onboarding

```bash
harness init
harness init --host https://app.harness.io --account acc_123
harness init --profile prod --account acc_123 --output table
harness init --non-interactive --api-key "$HARNESS_API_KEY"
```

Interactive setup prompts for host, API key, account, org, project, and default
output mode. `--output` and `default_output` accept `json`, `raw`, or `table`.
Global `--profile NAME` and `--config PATH` select command context for a single
invocation without mutating the active profile or requiring exported
environment variables.

## Profiles

```bash
harness profile list
harness profile current
harness profile use prod
harness profile remove sandbox --force
```

`HARNESS_PROFILE` selects a profile without changing the config file. `harness
init --profile NAME` writes onboarding values into a named profile.

## Diagnostics

```bash
harness doctor
harness doctor --network
harness doctor --network --timeout 5 --json
harness auth status
```

`harness doctor` checks local config, profile, permissions, and generated
manifest counts. `--network` also sends `GET /v1/version` to the configured
Harness host so setup problems can be separated from connectivity problems.

## Configuration

```bash
harness config list
harness config get host
harness config set account acc_123
harness config unset project
```

Supported config keys:

- `host`
- `api_key`
- `account`
- `org`
- `project`
- `default_output`

## API Discovery

```bash
harness api info
harness api groups
harness api list --tag "Pipeline"
harness api list --method post --search execute
harness api list --group account-roles --has-body
harness api list --path /v1/roles --method post
harness api describe execute-a-pipeline
harness api body create-role-acc
harness api body create-role-acc --output-file role.json
harness api body create-role-acc --content-type application/yaml --json
```

`harness api describe` prints docs links, defaults, enums, pagination support,
body-template hints, and pasteable examples for the generated shortcut and
stable `api call` form. `harness api body` prints request-body templates from
official examples where available, then falls back to a compact schema-derived
sample. Use `--output-file` to write the template before editing it and sending
it with `--body @file.json`.

Useful discovery filters:

- `--search TEXT`
- `--tag "Display Name"`
- `--group generated-group`
- `--method get|post|put|patch|delete`
- `--path /path-fragment`
- `--has-body`
- `--deprecated`

## API Calls

```bash
harness api call --help
harness api call list-roles-acc --help
harness api call list-roles-acc --query limit=10 --help
harness api call list-roles-acc --query limit=10
harness account-roles list-roles-acc --limit 10
harness account-roles list-roles-acc --limit 10 --help
harness account-roles list-roles-acc --limit 10 --output table
harness account-roles list-roles-acc --limit 10 --output table --columns identifier,name,createdAt
harness account-roles list-roles-acc --all --all-page-size 100 --output table
harness account-roles list-roles-acc --limit 10 --curl
harness account-roles get-role-acc --role my-role
harness project-services create-service --org my-org --project my-project --body @service.json
harness project-services create-service --org my-org --project my-project --body-json @service.json
harness api call create-role-acc --body '{"identifier":"demo","name":"Demo"}'
harness artifact-signing upload-signature --org my-org --project my-project --file signature=@sig.json
harness file-store download-file --identifier readme --output-file readme.md
```

Useful call flags:

- `--path key=value`
- `--query key=value`
- `--header key=value`
- `--param key=value`
- `--body @file.json`
- `--body -`
- `--form key=value`
- `--file field=@path`
- `--output-file path`
- `--columns identifier,name,metadata.status`
- `--all`
- `--all-page-size 100`
- `--max-pages 50`
- `--curl`
- `--dry-run`
- `--include`
- `--output json|raw|table`

Add `--help` anywhere after an operation name to print that operation's
parameters, examples, body-template hint, pagination support, and generic call
flags without sending a request.

Use `--columns` with `--output table` to choose table columns in order. Dotted
names such as `metadata.status` read nested object fields.

`--body-json` accepts inline JSON, `@file`, or `-` stdin, validates the payload
before sending it, and defaults the content type to `application/json`.

`--form` and `--file` build multipart request bodies by default. Use
`--content-type application/x-www-form-urlencoded` with `--form` when an
endpoint expects URL-encoded form data instead.

`--all` works with endpoints that expose recognizable query pagination
parameters such as `page`/`limit`, `page`/`size`, `page`/`pageSize`,
`pageIndex`/`pageSize`, `pageNumber`/`pageSize`, `offset`/`limit`,
`offset`/`pageSize`, or cursor-style `pageToken`/`cursor`. It stops at
`--max-pages` as a safety guard.

`--curl` prints a redacted cURL command and does not send the request. It is
useful for sharing or debugging a prepared request without exposing API keys.
Dry-run and cURL previews also redact `Authorization`, case variants of
`x-api-key`, and common token/secret/password-style headers.

`--account` and the active profile account are also used for endpoints that
expect the `Harness-Account` header.

## Shell Completion

```bash
harness completion bash
harness completion zsh
harness completion fish
```

Completion scripts call the CLI's generated manifest at completion time, so
refreshed endpoint groups and operations are immediately reflected.

## Terminal Output

The CLI keeps stdout for command data and uses stderr for progress/status
messages. Color and animation are automatic for interactive terminals and are
disabled for pipes, `TERM=dumb`, and `NO_COLOR`.

```bash
HARNESS_COLOR=always harness api list --search pipeline
HARNESS_ANIMATION=never harness account-roles list-roles-acc --limit 10
HARNESS_ASCII=1 harness account-roles list-roles-acc --limit 10
```

## Developer Formatting

```bash
uv run ruff format .
uv run ruff check .
```
