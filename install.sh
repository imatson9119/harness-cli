#!/usr/bin/env sh
set -eu

repo="${HCTL_REPO:-imatson9119/harness-cli}"
version="${HCTL_VERSION:-latest}"
install_dir="${HCTL_INSTALL_DIR:-$HOME/.local/bin}"
asset="hctl.pyz"

if [ "$version" = "latest" ]; then
  base_url="https://github.com/$repo/releases/latest/download"
else
  base_url="https://github.com/$repo/releases/download/$version"
fi
base_url="${HCTL_BASE_URL:-$base_url}"
git_url="${HCTL_GIT_URL:-https://github.com/$repo.git}"

tmp_dir="$(mktemp -d 2>/dev/null || mktemp -d -t hctl)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT INT TERM

download() {
  url="$1"
  dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$dest"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$dest" "$url"
  else
    echo "error: install requires curl or wget" >&2
    return 1
  fi
}

sha256_file() {
  file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    return 1
  fi
}

install_from_uv_git() {
  if ! command -v uv >/dev/null 2>&1; then
    return 1
  fi
  echo "Installing hctl from Git with uv..."
  uv tool install --force "git+$git_url"
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "warning: hctl.pyz needs python3. Falling back to uv-managed install if possible." >&2
  if install_from_uv_git; then
    exit 0
  fi
  echo "error: install requires python3 or uv" >&2
  exit 1
fi

asset_path="$tmp_dir/$asset"
if ! download "$base_url/$asset" "$asset_path"; then
  echo "Release artifact unavailable at $base_url/$asset" >&2
  if install_from_uv_git; then
    exit 0
  fi
  echo "error: install requires a published release artifact or uv" >&2
  exit 1
fi

checksums_path="$tmp_dir/checksums.txt"
if download "$base_url/checksums.txt" "$checksums_path"; then
  expected="$(awk '$2 == "hctl.pyz" {print $1}' "$checksums_path" | head -n 1)"
  if [ -n "$expected" ]; then
    actual="$(sha256_file "$asset_path" || true)"
    if [ -n "$actual" ] && [ "$actual" != "$expected" ]; then
      echo "error: checksum mismatch for hctl.pyz" >&2
      exit 1
    fi
  fi
fi

mkdir -p "$install_dir"
install -m 755 "$asset_path" "$install_dir/hctl"

echo "Installed hctl to $install_dir/hctl"
if ! command -v hctl >/dev/null 2>&1; then
  echo "Add $install_dir to PATH, or run:" >&2
  echo "  export PATH=\"$install_dir:\$PATH\"" >&2
fi
"$install_dir/hctl" --version
