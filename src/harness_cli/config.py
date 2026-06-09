from __future__ import annotations

import json
import os
import re
import urllib.parse
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_ENV = "HARNESS_CONFIG"
PROFILE_ENV = "HARNESS_PROFILE"
DEFAULT_PROFILE = "default"
VALID_CONFIG_KEYS = {"host", "api_key", "account", "org", "project", "default_output"}
VALID_OUTPUT_MODES = {"json", "raw", "table"}
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class HarnessConfig:
    host: str = "https://app.harness.io"
    api_key: str | None = None
    account: str | None = None
    org: str | None = None
    project: str | None = None
    default_output: str = "json"
    profile: str = DEFAULT_PROFILE

    def redacted(self) -> dict[str, str | None]:
        data = self.as_dict(include_empty=True)
        if data.get("api_key"):
            data["api_key"] = redact_secret(str(data["api_key"]))
        if self.profile:
            data["profile"] = self.profile
        return data

    def as_dict(self, *, include_empty: bool = False) -> dict[str, str | None]:
        data: dict[str, str | None] = {
            "host": self.host,
            "api_key": self.api_key,
            "account": self.account,
            "org": self.org,
            "project": self.project,
            "default_output": self.default_output,
        }
        if include_empty:
            return data
        return {key: value for key, value in data.items() if value not in (None, "")}


def default_config_path() -> Path:
    configured = os.environ.get(CONFIG_ENV)
    if configured:
        return Path(configured).expanduser()
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home).expanduser() / "harness" / "config.json"
    return Path.home() / ".config" / "harness" / "config.json"


def load_config(path: Path | None = None) -> HarnessConfig:
    config_path = path or default_config_path()
    raw_data = read_config_document(config_path)
    profile = current_profile_name(config_path, raw=raw_data)
    file_data = _profile_values(raw_data, profile=profile)

    merged = {
        "host": os.environ.get("HARNESS_HOST", file_data.get("host", "https://app.harness.io")),
        "api_key": os.environ.get("HARNESS_API_KEY", file_data.get("api_key")),
        "account": os.environ.get("HARNESS_ACCOUNT", file_data.get("account")),
        "org": os.environ.get("HARNESS_ORG", file_data.get("org")),
        "project": os.environ.get("HARNESS_PROJECT", file_data.get("project")),
        "default_output": os.environ.get("HARNESS_OUTPUT", file_data.get("default_output", "json")),
    }
    default_output = _validate_output_mode(merged["default_output"])
    return HarnessConfig(
        host=validate_host_url(merged["host"]),
        api_key=_optional_string(merged["api_key"]),
        account=_optional_string(merged["account"]),
        org=_optional_string(merged["org"]),
        project=_optional_string(merged["project"]),
        default_output=default_output,
        profile=profile,
    )


def read_config_document(path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_path()
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected object in {config_path}")
    return loaded


def read_config_file(path: Path | None = None, *, profile: str | None = None) -> dict[str, Any]:
    raw = read_config_document(path)
    selected_profile = current_profile_name(path, raw=raw, explicit=profile)
    return _profile_values(raw, profile=selected_profile)


def write_config_file(
    values: dict[str, Any],
    path: Path | None = None,
    *,
    profile: str | None = None,
) -> Path:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_config_document(config_path)
    selected_profile = current_profile_name(config_path, raw=existing, explicit=profile)
    data = _config_document(existing)
    data["current_profile"] = selected_profile
    profiles = _profiles_from_document(data)
    profiles[selected_profile] = _config_values(values)
    data["profiles"] = profiles
    _write_config_document(data, config_path)
    return config_path


def set_config_value(
    key: str,
    value: str,
    path: Path | None = None,
    *,
    profile: str | None = None,
) -> Path:
    if key not in VALID_CONFIG_KEYS:
        raise KeyError(f"Unknown config key: {key}")
    data = read_config_file(path, profile=profile)
    data[key] = value
    return write_config_file(data, path, profile=profile)


def unset_config_value(key: str, path: Path | None = None, *, profile: str | None = None) -> Path:
    if key not in VALID_CONFIG_KEYS:
        raise KeyError(f"Unknown config key: {key}")
    data = read_config_file(path, profile=profile)
    data.pop(key, None)
    return write_config_file(data, path, profile=profile)


def list_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return _profiles_from_document(read_config_document(path))


def current_profile_name(
    path: Path | None = None,
    *,
    raw: dict[str, Any] | None = None,
    explicit: str | None = None,
) -> str:
    if explicit:
        return _validate_profile_name(explicit)
    env_profile = os.environ.get(PROFILE_ENV)
    if env_profile:
        return _validate_profile_name(env_profile)
    data = raw if raw is not None else read_config_document(path)
    current = data.get("current_profile")
    if isinstance(current, str) and current:
        return _validate_profile_name(current)
    return DEFAULT_PROFILE


def use_profile(name: str, path: Path | None = None, *, create: bool = True) -> Path:
    profile_name = _validate_profile_name(name)
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = _config_document(read_config_document(config_path))
    profiles = _profiles_from_document(data)
    if profile_name not in profiles:
        if not create:
            raise KeyError(f"Unknown profile: {profile_name}")
        profiles[profile_name] = {}
    data["current_profile"] = profile_name
    data["profiles"] = profiles
    _write_config_document(data, config_path)
    return config_path


def remove_profile(name: str, path: Path | None = None) -> Path:
    profile_name = _validate_profile_name(name)
    config_path = path or default_config_path()
    data = _config_document(read_config_document(config_path))
    profiles = _profiles_from_document(data)
    if profile_name not in profiles:
        raise KeyError(f"Unknown profile: {profile_name}")
    profiles.pop(profile_name)
    current = data.get("current_profile")
    if current == profile_name:
        data["current_profile"] = sorted(profiles)[0] if profiles else DEFAULT_PROFILE
    else:
        data["current_profile"] = current
    data["profiles"] = profiles
    _write_config_document(data, config_path)
    return config_path


def _write_config_document(data: dict[str, Any], config_path: Path) -> None:
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with suppress(OSError):
        config_path.chmod(0o600)


def _profile_values(raw: dict[str, Any], *, profile: str) -> dict[str, Any]:
    return _profiles_from_document(raw).get(profile, {})


def _config_document(raw: dict[str, Any]) -> dict[str, Any]:
    current = raw.get("current_profile")
    current_profile = (
        _validate_profile_name(current) if isinstance(current, str) and current else DEFAULT_PROFILE
    )
    return {
        "current_profile": current_profile,
        "profiles": _profiles_from_document(raw),
    }


def _profiles_from_document(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if "profiles" not in raw:
        return {}
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Expected config `profiles` to be an object.")
    clean: dict[str, dict[str, Any]] = {}
    for name, values in profiles.items():
        if not isinstance(name, str):
            raise ValueError("Profile names must be strings.")
        if not isinstance(values, dict):
            raise ValueError(f"Expected profile {name} to be an object.")
        clean[_validate_profile_name(name)] = _config_values(values)
    return clean


def _config_values(values: dict[str, Any]) -> dict[str, Any]:
    clean = {key: values[key] for key in VALID_CONFIG_KEYS if values.get(key) not in (None, "")}
    if "host" in clean:
        clean["host"] = validate_host_url(clean["host"])
    if "default_output" in clean:
        clean["default_output"] = _validate_output_mode(clean["default_output"])
    return clean


def _validate_profile_name(name: str) -> str:
    if not name or not PROFILE_NAME_RE.fullmatch(name):
        raise ValueError(
            "Profile names can contain only letters, numbers, dots, underscores, and hyphens."
        )
    return name


def _validate_output_mode(value: Any) -> str:
    mode = str(value or "json")
    if mode not in VALID_OUTPUT_MODES:
        choices = ", ".join(sorted(VALID_OUTPUT_MODES))
        raise ValueError(f"default_output must be one of: {choices}")
    return mode


def validate_host_url(value: Any) -> str:
    host = str(value or "https://app.harness.io").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(host)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("host must be an http(s) URL, for example https://app.harness.io")
    if parsed.query or parsed.fragment:
        raise ValueError("host must not include query or fragment components")
    return host


def redact_secret(value: str) -> str:
    if len(value) <= 8:
        return "********"
    return f"{value[:4]}...{value[-4:]}"


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
