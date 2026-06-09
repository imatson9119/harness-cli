# Command Reference

## Top Level

```bash
harness --help
harness init
harness doctor
harness auth status
harness config list
harness api list
```

## Onboarding

```bash
harness init
harness init --host https://app.harness.io --account acc_123
harness init --non-interactive --api-key "$HARNESS_API_KEY"
```

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
harness account-roles get-role-acc --role my-role
harness project-services create-service --org my-org --project my-project --body @service.json
harness api call create-role-acc --body '{"identifier":"demo","name":"Demo"}'
```

Useful call flags:

- `--path key=value`
- `--query key=value`
- `--header key=value`
- `--param key=value`
- `--body @file.json`
- `--body -`
- `--dry-run`
- `--include`
- `--output json|raw`

