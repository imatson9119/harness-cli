# Command Reference

## Top Level

```bash
hctl --help
hctl --profile prod doctor
hctl --config ./harness.config.json auth status
hctl init
hctl doctor
hctl doctor --network
hctl auth status
hctl profile list
hctl config list
hctl api info
hctl api body create-role-acc
hctl api list
hctl completion zsh
```

## Onboarding

```bash
hctl init
hctl init --host https://app.harness.io --account acc_123
hctl init --profile prod --account acc_123 --output table
hctl init --non-interactive --api-key "$HARNESS_API_KEY"
```

Interactive setup prompts for host, API key, account, org, project, and default
output mode. Host values must be full `http://` or `https://` URLs. `--output`
and `default_output` accept `json`, `raw`, or `table`.
Global `--profile NAME` and `--config PATH` select command context for a single
invocation without mutating the active profile or requiring exported
environment variables.

## Profiles

```bash
hctl profile list
hctl profile current
hctl profile use prod
hctl profile remove sandbox --force
```

`HARNESS_PROFILE` selects a profile without changing the config file. `hctl
init --profile NAME` writes onboarding values into a named profile.

## Diagnostics

```bash
hctl doctor
hctl doctor --fix-permissions
hctl doctor --network
hctl doctor --network --timeout 5 --json
hctl auth status
```

`hctl doctor` checks local config, profile, permissions, and generated
manifest counts. `--fix-permissions` repairs the config file mode to `0600`
when possible. `--network` also sends `GET /v1/version` to the configured
Harness host so setup problems can be separated from connectivity problems.

## Configuration

```bash
hctl config list
hctl config get host
hctl config set account acc_123
hctl config unset project
```

Supported config keys:

- `host`
- `api_key`
- `account`
- `org`
- `project`
- `default_output`

`host` must be a full `http://` or `https://` URL, such as
`https://app.harness.io`.

## API Discovery

```bash
hctl api info
hctl api groups
hctl api groups --search pipeline --limit 20
hctl api list --tag "Pipeline"
hctl api list --method post --search execute
hctl api list --search role --wide
hctl api list --group account-roles --has-body
hctl api list --path /v1/roles --method post
hctl api describe execute-a-pipeline
hctl api body create-role-acc
hctl api body create-account-scoped-connector --content-type application/yaml
hctl api body create-role-acc --output-file role.json
hctl api body create-role-acc --content-type application/yaml --json
```

`hctl api describe` prints docs links, defaults, enums, pagination support,
body-template hints, and pasteable examples for the generated shortcut and
stable `api call` form. `hctl api body` prints request-body templates from
official examples where available, then falls back to a compact schema-derived
sample. JSON templates are pretty-printed as JSON. YAML and other text
templates are printed or written as editable raw text. Use `--json` when you
want metadata such as the selected content type wrapped around the body. Use
`--output-file` to write the template before editing it and sending it with
`--body @file.json`.

Useful discovery filters:

- `hctl api groups --search TEXT --limit N`
- `--search TEXT`
- `--tag "Display Name"`
- `--group generated-group`
- `--method get|post|put|patch|delete`
- `--path /path-fragment`
- `--has-body`
- `--deprecated`
- `--wide`

`--method` is validated against known HTTP methods, and `--group` must match a
generated group slug. Misspelled groups include nearest-match suggestions.

Use `--wide` on `api list` or `api groups` when you want copy-friendly tables
with full command and group names instead of terminal-fitted cells.

## API Calls

```bash
hctl api call --help
hctl api call list-roles-acc --help
hctl api call list-roles-acc --query limit=10 --help
hctl api call list-roles-acc --query limit=10
hctl account-roles list-roles-acc --limit 10
hctl account-roles list-roles-acc --limit 10 --help
hctl account-roles list-roles-acc --limit 10 --output table
hctl account-roles list-roles-acc --limit 10 --output table --columns identifier,name,createdAt
hctl account-roles list-roles-acc --all --all-page-size 100 --output table
hctl account-roles list-roles-acc --limit 10 --curl
hctl account-roles get-role-acc --role my-role
hctl project-services create-service --org my-org --project my-project --body @service.json
hctl project-services create-service --org my-org --project my-project --body-json @service.json
hctl api call create-role-acc --body-template --dry-run
hctl api call create-role-acc --body '{"identifier":"demo","name":"Demo"}'
hctl artifact-signing upload-signature --org my-org --project my-project --file signature=@sig.json
hctl file-store download-file --identifier readme --output-file readme.md
```

Useful call flags:

- `--path key=value`
- `--query key=value`
- `--header key=value`
- `--param key=value`
- `--body VALUE|@file|-`
- `--body-file path`
- `--body-json JSON`
- `--body-template`
- `--form key=value`
- `--file field=@path`
- `--content-type value`
- `--columns a,b,c`
- `--output json|raw|table`
- `--output-file path`
- `--all`
- `--all-page-size 100`
- `--max-pages 50`
- `--curl`
- `--dry-run`
- `--include`
- `--timeout seconds`
- `--host http(s)-url`
- `--api-key KEY`
- `--no-auth`

Add `--help` anywhere after an operation name to print that operation's
parameters, examples, body-template hint, pagination support, and generic call
flags without sending a request.

Use `--columns` with `--output table` to choose table columns in order. Dotted
names such as `metadata.status` read nested object fields.

`--body-json` accepts inline JSON, `@file`, or `-` stdin, validates the payload
before sending it, and defaults the content type to `application/json`.
`--body-template` sends the generated request-body sample for an operation when
the sample can be serialized as JSON or YAML; pair it with `--dry-run` when
exploring an unfamiliar endpoint. For other structured content types, run
`hctl api body OPERATION --content-type TYPE --output-file body.txt`, edit
the result, and send it with `--body @body.txt --content-type TYPE`.
Unreadable `@file` body inputs, upload files, and unwritable output paths fail
with concise local file errors.

`--host` overrides the Harness base URL for one call. It must be a full
`http://` or `https://` URL and cannot include query strings or fragments.

`--form` and `--file` build multipart request bodies by default. Use
`--content-type application/x-www-form-urlencoded` with `--form` when an
endpoint expects URL-encoded form data instead.

`--all` works with endpoints that expose recognizable query pagination
parameters such as `page`/`limit`, `page`/`size`, `page`/`pageSize`,
`pageIndex`/`pageSize`, `pageNumber`/`pageSize`, `offset`/`limit`,
`offset`/`pageSize`, or cursor-style `pageToken`/`cursor`. It stops at
`--max-pages` as a safety guard.

`--timeout`, `--all-page-size`, and `--max-pages` must be positive numbers.

`--curl` prints a redacted cURL command and does not send the request. It is
useful for sharing or debugging a prepared request without exposing API keys.
Dry-run and cURL previews also redact `Authorization`, case variants of
`x-api-key`, and common token/secret/password-style headers.

`--account` and the active profile account are also used for endpoints that
expect the `Harness-Account` header. Profile account, org, and project values
also fill common generated parameter spellings, including camel-case, ID-style,
and snake-case Harness scope identifiers.

## Shell Completion

```bash
hctl completion bash
hctl completion zsh
hctl completion fish
```

Completion scripts call the CLI's generated manifest at completion time, so
refreshed endpoint groups and operations are immediately reflected.

## Terminal Output

The CLI keeps stdout for command data and uses stderr for progress/status
messages. Color respects `NO_COLOR`. Table frames and animation are automatic
for interactive terminals and are disabled for pipes and `TERM=dumb`.

```bash
HARNESS_COLOR=always hctl api list --search pipeline
HARNESS_ANIMATION=never hctl account-roles list-roles-acc --limit 10
HARNESS_STATUS=never hctl account-roles list-roles-acc --limit 10
HARNESS_TABLE_STYLE=unicode hctl account-roles list-roles-acc --output table
HARNESS_TABLE_STYLE=ascii hctl account-roles list-roles-acc --output table
HARNESS_TABLE_STYLE=plain hctl account-roles list-roles-acc --output table
HARNESS_ASCII=1 hctl account-roles list-roles-acc --limit 10
```

`HARNESS_ANIMATION=never` keeps the final call status but removes live motion.
`HARNESS_STATUS=never` hides call status entirely.

## Developer Formatting

```bash
uv run ruff format .
uv run ruff check .
```
