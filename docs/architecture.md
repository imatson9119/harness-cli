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

## Generated Commands

Each OpenAPI operation is exposed through:

- `harness api call <operation-id>`
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
- Uses `x-api-key` unless `--no-auth` is provided.
- Supports JSON/YAML/form request bodies as raw input.
- Supports multipart file uploads through `--form` and `--file`.
- Supports binary response downloads through `--output-file`.
- Provides `--dry-run` so users can inspect requests before sending them.

## Refreshing Endpoint Coverage

The generator fetches:

```text
https://apidocs.harness.io/page-data/shared/oas-index.yaml.json
```

That file is the Redocly shared-data JSON behind <https://apidocs.harness.io/>.
It contains the resolved OpenAPI definition used to build the published docs.
