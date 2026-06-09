from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_ENV = "HARNESS_CONFIG"
VALID_CONFIG_KEYS = {"host", "api_key", "account", "org", "project", "default_output"}


@dataclass(frozen=True)
class HarnessConfig:
    host: str = "https://app.harness.io"
    api_key: str | None = None
    account: str | None = None
    org: str | None = None
    project: str | None = None
    default_output: str = "json"

    def redacted(self) -> dict[str, str | None]:
        data = self.as_dict(include_empty=True)
        if data.get("api_key"):
            data["api_key"] = redact_secret(str(data["api_key"]))
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
    file_data: dict[str, Any] = {}
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                file_data = {key: loaded[key] for key in VALID_CONFIG_KEYS if key in loaded}
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc

    merged = {
        "host": os.environ.get("HARNESS_HOST", file_data.get("host", "https://app.harness.io")),
        "api_key": os.environ.get("HARNESS_API_KEY", file_data.get("api_key")),
        "account": os.environ.get("HARNESS_ACCOUNT", file_data.get("account")),
        "org": os.environ.get("HARNESS_ORG", file_data.get("org")),
        "project": os.environ.get("HARNESS_PROJECT", file_data.get("project")),
        "default_output": os.environ.get(
            "HARNESS_OUTPUT", file_data.get("default_output", "json")
        ),
    }
    return HarnessConfig(
        host=str(merged["host"]).rstrip("/"),
        api_key=_optional_string(merged["api_key"]),
        account=_optional_string(merged["account"]),
        org=_optional_string(merged["org"]),
        project=_optional_string(merged["project"]),
        default_output=str(merged["default_output"] or "json"),
    )


def read_config_file(path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_path()
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected object in {config_path}")
    return {key: loaded[key] for key in VALID_CONFIG_KEYS if key in loaded}


def write_config_file(values: dict[str, Any], path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = {key: values[key] for key in VALID_CONFIG_KEYS if values.get(key) not in (None, "")}
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with suppress(OSError):
        config_path.chmod(0o600)
    return config_path


def set_config_value(key: str, value: str, path: Path | None = None) -> Path:
    if key not in VALID_CONFIG_KEYS:
        raise KeyError(f"Unknown config key: {key}")
    data = read_config_file(path)
    data[key] = value
    return write_config_file(data, path)


def unset_config_value(key: str, path: Path | None = None) -> Path:
    if key not in VALID_CONFIG_KEYS:
        raise KeyError(f"Unknown config key: {key}")
    data = read_config_file(path)
    data.pop(key, None)
    return write_config_file(data, path)


def redact_secret(value: str) -> str:
    if len(value) <= 8:
        return "********"
    return f"{value[:4]}...{value[-4:]}"


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
