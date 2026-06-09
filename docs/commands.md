# Command Reference

## Top Level

```bash
harness --help
harness init
harness doctor
harness auth status
harness profile list
harness config list
harness api list
harness completion zsh
```

## Onboarding

```bash
harness init
harness init --host https://app.harness.io --account acc_123
harness init --profile prod --account acc_123
harness init --non-interactive --api-key "$HARNESS_API_KEY"
```

## Profiles

```bash
harness profile list
harness profile current
harness profile use prod
harness profile remove sandbox --force
```

`HARNESS_PROFILE` selects a profile without changing the config file. `harness
init --profile NAME` writes onboarding values into a named profile.

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
harness api groups
harness api list --tag "Pipeline"
harness api list --method post --search execute
harness api describe execute-a-pipeline
```

## API Calls

```bash
harness api call list-roles-acc --query limit=10
harness account-roles list-roles-acc --limit 10
harness account-roles list-roles-acc --limit 10 --output table
harness account-roles get-role-acc --role my-role
harness project-services create-service --org my-org --project my-project --body @service.json
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
- `--dry-run`
- `--include`
- `--output json|raw|table`

`--form` and `--file` build multipart request bodies by default. Use
`--content-type application/x-www-form-urlencoded` with `--form` when an
endpoint expects URL-encoded form data instead.

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
