# Architecture

The CLI has three layers:

1. `harness_cli.manifest` loads the generated OpenAPI operation manifest.
2. `harness_cli.http` maps operation metadata plus CLI arguments to HTTP
   requests.
3. `harness_cli.cli` provides onboarding, config management, API discovery, and
   generated endpoint shortcuts.

The generated endpoint surface is intentionally metadata-driven. The project
does not hand-code thousands of Harness endpoints; it keeps the command behavior
generic and refreshes endpoint coverage from the official OpenAPI bundle.
Shell completion follows the same pattern: completion scripts call back into the
CLI so generated groups, operations, and parameter flags stay aligned with the
manifest.

## Config Profiles

Local configuration is stored as a profile document:

```json
{
  "current_profile": "prod",
  "profiles": {
    "prod": {
      "host": "https://app.harness.io",
      "account": "..."
    }
  }
}
```

Environment variables override the active profile at runtime. `HARNESS_PROFILE`
selects a profile without modifying the file.

Host values are validated as full `http://` or `https://` URLs during config
load, config write, and request construction so malformed saved hosts,
environment overrides, or per-call `--host` values fail before URL assembly.

Global CLI flags such as `--profile` and `--config` are implemented as
temporary environment overrides for one invocation, so command handlers continue
to use the same config-loading path as environment-variable based workflows.

## Terminal Rendering

Rendering is intentionally dependency-light. `harness_cli.render` owns table
layout, table frames, JSON highlighting, status styling, and the stderr-only
call spinner. Color follows `NO_COLOR`, `HARNESS_COLOR=always|never|auto`, and
dumb-terminal detection. Table frames follow
`HARNESS_TABLE_STYLE=auto|unicode|ascii|plain` with plain output for pipes.
Call status follows `HARNESS_STATUS=always|never|auto`, and animation follows
`HARNESS_ANIMATION=always|never|auto`.

## Packaging

The endpoint manifest is bundled as package data under
`harness_cli.data/operations.json`. CI builds both sdist and wheel artifacts and
smoke-tests an installed wheel by running `harness --version` and a manifest
lookup command.

## Manifest Validation

`scripts/validate_openapi_manifest.py` checks generated manifest integrity:
counts, unique operation IDs, unique shortcut pairs, valid methods, declared
groups, docs URLs, and collisions with built-in CLI commands. CI runs this
validator before packaging.

## Generated Commands

Each OpenAPI operation is exposed through:

- `harness api call <operation-id>`
- `harness api body <operation-id>` for request-body templates
- `harness <tag-slug> <operation-id>`

Operation parameters become flags when called through a generated group:

```bash
harness account-roles list-roles-acc --limit 10
```

Path, query, and header parameters can also be passed explicitly:

```bash
harness api call get-role-acc --path role=my-role
harness api call list-roles-acc --query limit=10
```

## Request Construction

The request builder:

- Resolves path parameters from operation metadata.
- Adds query and header parameters from flags.
- Expands configured account, org, and project profile defaults across common
  Harness scope aliases such as `accountIdentifier`, `accountId`, `account_id`,
  `orgIdentifier`, `organizationIdentifier`, `projectIdentifier`, and
  snake-case registry identifiers.
- Preserves explicit `--query` and `--header` values over profile-derived
  defaults for the same generated parameter.
- Uses `x-api-key` unless `--no-auth` is provided.
- Supports JSON/YAML/form request bodies as raw input.
- Stores request-body samples from OpenAPI examples or compact schema-derived
  templates for `harness api body`.
- Supports multipart file uploads through `--form` and `--file`.
- Supports binary response downloads through `--output-file`.
- Supports guarded pagination helpers for common list endpoint shapes.
- Provides `--dry-run` so users can inspect requests before sending them.
- Provides `--curl` so users can inspect or share a redacted cURL command
  without sending the request.
- Redacts credential-like headers in previews without changing the actual
  request headers sent to Harness.

## Error Handling

Harness HTTP responses are kept response-shaped: 4xx and 5xx bodies are rendered
and the command exits with status `1`. Transport failures such as DNS,
connection, or timeout errors are converted into concise CLI errors on stderr so
users do not see Python tracebacks during normal failure modes.

## Diagnostics

`harness doctor` is local by default: it checks profile state, config file
permissions, and manifest counts without sending traffic or mutating files.
`harness doctor --fix-permissions` opts into repairing config file permissions
to `0600`. `harness doctor --network` opts into a real `GET /v1/version`
reachability check against the configured host and reports the result in both
human and JSON output.

## Refreshing Endpoint Coverage

The generator fetches:

```text
https://apidocs.harness.io/page-data/shared/oas-index.yaml.json
```

That file is the Redocly shared-data JSON behind <https://apidocs.harness.io/>.
It contains the resolved OpenAPI definition used to build the published docs.
