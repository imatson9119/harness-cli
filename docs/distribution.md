# Distribution

The public package and command name is `hctl`.

The internal Python import package remains `harness_cli` so the generated API
runtime can evolve separately from the user-facing command name.

## User Install Paths

### Git with uv

This path works before the first registry release:

```bash
uv tool install git+https://github.com/imatson9119/harness-cli.git
hctl init
```

Upgrade and remove:

```bash
uv tool upgrade hctl
uv tool uninstall hctl
```

### PyPI

After the first tagged release publishes to PyPI:

```bash
uv tool install hctl
```

`pipx` is also supported:

```bash
pipx install hctl
```

Upgrade and remove:

```bash
uv tool upgrade hctl
uv tool uninstall hctl
pipx upgrade hctl
pipx uninstall hctl
```

### GitHub Releases

Tagged releases attach:

- `hctl-<version>.tar.gz`
- `hctl-<version>-py3-none-any.whl`
- `hctl.pyz`
- `hctl.rb`
- `checksums.txt`

The zipapp artifact is executable on systems with Python 3.10 or newer:

```bash
curl -fsSLO https://github.com/imatson9119/harness-cli/releases/latest/download/hctl.pyz
chmod +x hctl.pyz
./hctl.pyz --version
```

Upgrade by replacing the file with a newer release artifact. Uninstall by
removing the installed file.

### Curl Installer

The installer prefers the latest `hctl.pyz` release artifact and falls back to
`uv tool install` from Git when no release artifact is available.

```bash
curl -fsSL https://raw.githubusercontent.com/imatson9119/harness-cli/main/install.sh | sh
```

Install a specific release:

```bash
curl -fsSL https://raw.githubusercontent.com/imatson9119/harness-cli/main/install.sh \
  | HCTL_VERSION=v0.1.0 sh
```

Install somewhere else:

```bash
curl -fsSL https://raw.githubusercontent.com/imatson9119/harness-cli/main/install.sh \
  | HCTL_INSTALL_DIR="$HOME/bin" sh
```

Installer maintainers can test non-production artifacts with `HCTL_BASE_URL`
and `HCTL_GIT_URL`.

### Homebrew

Each GitHub release includes a rendered `hctl.rb` formula. Copy that formula
into a tap:

```bash
curl -fsSLO https://github.com/imatson9119/harness-cli/releases/latest/download/hctl.rb
cp hctl.rb /path/to/homebrew-tap/Formula/hctl.rb
```

Users can then install from the tap:

```bash
brew tap imatson9119/tap
brew install hctl
```

Upgrade and remove:

```bash
brew upgrade hctl
brew uninstall hctl
```

## Shell Completion

`hctl` prints completion scripts for Bash, Zsh, and Fish:

```bash
hctl completion bash
hctl completion zsh
hctl completion fish
```

Common install paths:

```bash
mkdir -p ~/.local/share/bash-completion/completions
hctl completion bash > ~/.local/share/bash-completion/completions/hctl
mkdir -p ~/.zfunc
hctl completion zsh > ~/.zfunc/_hctl
mkdir -p ~/.config/fish/completions
hctl completion fish > ~/.config/fish/completions/hctl.fish
```

## Release Process

1. Update `src/harness_cli/__init__.py` and `pyproject.toml` to the release
   version.
2. Refresh the endpoint manifest if needed:

   ```bash
   uv run python scripts/update_openapi_manifest.py
   ```

3. Run the full local verification suite:

   ```bash
   uv run --frozen ruff format --check .
   uv run --frozen ruff check .
   uv run --frozen mypy src/harness_cli
   uv run --frozen python -m unittest
   uv run --frozen python scripts/validate_openapi_manifest.py
   uv run --frozen python -m compileall -q src tests scripts
   uv build --sdist --wheel
   uv run --frozen python scripts/build_standalone.py
   ```

4. Tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

The release workflow builds the Python package, builds `hctl.pyz`, renders the
Homebrew formula, writes checksums, creates a GitHub Release, and publishes to
PyPI using trusted publishing.

For PyPI trusted publishing, configure the `hctl` project with:

- Owner: `imatson9119`
- Repository: `harness-cli`
- Workflow: `release.yml`
- Environment: `pypi`
