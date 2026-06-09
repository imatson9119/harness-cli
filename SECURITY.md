# Security

Do not put Harness API keys, account IDs, or private endpoint payloads in issues
or pull requests.

The CLI reads credentials in this order:

1. Explicit command flags such as `--api-key`.
2. Environment variables such as `HARNESS_API_KEY`.
3. The local config file, usually `~/.config/harness/config.json`.

`harness init` writes the config file with `0600` permissions. Prefer
environment variables or a secret manager for CI.

To report a security issue, contact the repository owner privately.

