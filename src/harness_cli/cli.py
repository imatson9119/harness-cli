from __future__ import annotations

import argparse
import contextlib
import difflib
import getpass
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import __version__
from .config import (
    BUILTIN_CONFIG_KEYS,
    CONFIG_ENV,
    DEFAULT_PROFILE,
    PROFILE_ENV,
    VALID_OUTPUT_MODES,
    HarnessConfig,
    current_profile_name,
    default_config_path,
    list_profiles,
    load_config,
    read_config_file,
    redact_secret,
    remove_profile,
    set_config_value,
    unset_config_value,
    use_profile,
    validate_config_key,
    write_config_file,
)
from .http import (
    CallOptions,
    RequestError,
    pagination_help,
    prepare_request,
    render_curl,
    render_dry_run,
    render_response,
    send_paginated_request,
    send_request,
)
from .manifest import HTTP_METHODS, Manifest, Operation, load_manifest
from .render import CallStatus, glyph, print_error, print_json, print_notice, print_table, stylize

BUILTIN_COMMANDS = {"init", "config", "auth", "doctor", "api", "completion", "version"}
PAIR_FLAGS = {"--path", "--query", "--header", "--param"}
GENERIC_CALL_FLAGS = (
    "--path",
    "--query",
    "--header",
    "--param",
    "--body",
    "--body-json",
    "--body-file",
    "--body-template",
    "--form",
    "--file",
    "--content-type",
    "--columns",
    "--jq",
    "--output",
    "--output-file",
    "--all",
    "--all-page-size",
    "--max-pages",
    "--timeout",
    "--host",
    "--api-key",
    "--curl",
    "--dry-run",
    "--include",
    "--unwrap",
    "--no-auth",
    "--help",
)
COMMON_PARAMETER_FLAGS = (
    "--account",
    "--account-identifier",
    "--account-id",
    "--org",
    "--org-identifier",
    "--project",
    "--project-identifier",
)
GLOBAL_FLAGS = {
    "--config": CONFIG_ENV,
    "--profile": PROFILE_ENV,
}
HELP_TOKENS = {"-h", "--help", "help"}
CALL_VALUE_FLAGS = {
    *PAIR_FLAGS,
    "--api-key",
    "--all-page-size",
    "--body",
    "--body-file",
    "--body-json",
    "--content-type",
    "--columns",
    "--file",
    "--form",
    "--host",
    "--jq",
    "--max-pages",
    "--output",
    "--output-file",
    "--timeout",
}
CALL_BOOLEAN_FLAGS = {
    "--all",
    "--body-template",
    "--curl",
    "--dry-run",
    "--include",
    "--no-auth",
    "--unwrap",
}


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    try:
        args, env_overrides = parse_global_options(raw_args)
        with temporary_environ(env_overrides):
            return dispatch(args)
    except KeyboardInterrupt:
        print_error("Interrupted.")
        return 130
    except RequestError as exc:
        print_error(str(exc))
        return 1
    except (KeyError, ValueError) as exc:
        print_error(str(exc))
        return 2
    except BrokenPipeError:
        return 1


def dispatch(args: list[str]) -> int:
    if not args or args[0] in {"-h", "--help", "help"}:
        print_top_level_help()
        return 0
    if args[0] in {"-V", "--version", "version"}:
        print(f"hctl {__version__}")
        return 0

    command = args[0]
    if command == "init":
        return command_init(args[1:])
    if command == "config":
        return command_config(args[1:])
    if command == "auth":
        return command_auth(args[1:])
    if command == "doctor":
        return command_doctor(args[1:])
    if command == "api":
        return command_api(args[1:])
    if command == "completion":
        return command_completion(args[1:])
    if command == "__complete":
        return command_internal_complete(args[1:])

    manifest = load_manifest()
    return command_generated(manifest, args)


def parse_global_options(argv: list[str]) -> tuple[list[str], dict[str, str]]:
    args: list[str] = []
    overrides: dict[str, str] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            args.extend(argv[index + 1 :])
            break
        if token in GLOBAL_FLAGS:
            value, index = _consume_value(argv, index)
            overrides[GLOBAL_FLAGS[token]] = value
            continue
        if token.startswith("--profile="):
            overrides[PROFILE_ENV] = token.split("=", 1)[1]
            index += 1
            continue
        if token.startswith("--config="):
            overrides[CONFIG_ENV] = token.split("=", 1)[1]
            index += 1
            continue
        args.extend(argv[index:])
        break
    return args, overrides


@contextlib.contextmanager
def temporary_environ(overrides: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, previous_value in previous.items():
            if previous_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous_value


def print_top_level_help() -> None:
    print(
        """Harness CLI

Usage:
  hctl [--profile NAME] [--config PATH] COMMAND
  hctl init
  hctl api list [--search TEXT] [--tag TAG]
  hctl api describe OPERATION
  hctl api body OPERATION
  hctl api call OPERATION [flags]
  hctl <group> <operation> [flags]
  hctl config profile list
  hctl completion SHELL

Built-in commands:
  init        Run onboarding and write local config
  config      Read and update local config and profiles
  auth        Show authentication status
  doctor      Check local setup and generated manifest
  api         Discover and call generated API operations
  completion  Print shell completion scripts
  version     Print CLI version

Global options:
  --profile NAME  Use a config profile for this command only
  --config PATH   Use a config file for this command only

Examples:
  hctl init
  hctl --profile prod doctor
  hctl config profile use prod
  hctl api list --search pipeline
  hctl api describe list-roles-acc
  hctl api body create-role-acc > body.json
  hctl api call list-roles-acc --query limit=10
  hctl account-roles list-roles-acc --limit 10 --dry-run
"""
    )


def command_init(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hctl init", description="Configure Harness CLI.")
    parser.add_argument("--host", default=None, help="Harness host URL.")
    parser.add_argument("--api-key", default=None, help="Harness API key.")
    parser.add_argument("--account", default=None, help="Default Harness account identifier.")
    parser.add_argument("--org", default=None, help="Default organization identifier.")
    parser.add_argument("--project", default=None, help="Default project identifier.")
    parser.add_argument("--profile", default=None, help="Config profile to write.")
    parser.add_argument(
        "--output",
        default=None,
        choices=sorted(VALID_OUTPUT_MODES),
        help="Default output mode.",
    )
    parser.add_argument("--non-interactive", action="store_true", help="Do not prompt.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing values.")
    parsed = parser.parse_args(argv)

    path = default_config_path()
    profile = current_profile_name(path, explicit=parsed.profile)
    existing = {} if parsed.overwrite else read_config_file(path, profile=profile)
    profiles = list_profiles(path)

    values: dict[str, Any] = dict(existing)
    values["host"] = parsed.host or values.get("host") or "https://app.harness.io"
    values["api_key"] = parsed.api_key or values.get("api_key") or os.environ.get("HARNESS_API_KEY")
    values["account"] = parsed.account or values.get("account")
    values["org"] = parsed.org or values.get("org")
    values["project"] = parsed.project or values.get("project")
    values["default_output"] = parsed.output or values.get("default_output") or "json"

    if not parsed.non_interactive:
        _print_init_intro(path, profile)
        values["host"] = _prompt("Host (default)", str(values["host"])) or values["host"]
        values["api_key"] = (
            _prompt(
                "API key (required for authenticated calls)",
                str(values["api_key"] or ""),
                secret=True,
            )
            or values["api_key"]
        )
        values["account"] = _prompt(
            "Default account (optional)",
            values.get("account") or "",
        ) or values.get("account")
        values["org"] = _prompt("Default org (optional)", values.get("org") or "") or values.get(
            "org"
        )
        values["project"] = _prompt(
            "Default project (optional)",
            values.get("project") or "",
        ) or values.get("project")
        values["default_output"] = _prompt_choice(
            "Default output (optional)",
            sorted(VALID_OUTPUT_MODES),
            str(values["default_output"]),
        )

    api_key_source = _profile_api_key_source(profile, values, profiles)
    if not api_key_source:
        print(
            "No API key available. Set HARNESS_API_KEY, "
            "`hctl config set api_key ...`, or configure the default profile."
        )

    written = write_config_file(values, path, profile=profile)
    _print_init_summary(written, profile, values, api_key_source=api_key_source)
    return 0


def command_config(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            """Usage:
  hctl config list
  hctl config get KEY
  hctl config set KEY VALUE
  hctl config unset KEY
  hctl config profile list [--json]
  hctl config profile current
  hctl config profile use NAME
  hctl config profile remove NAME --force

Built-in keys: """
            + ", ".join(sorted(BUILTIN_CONFIG_KEYS))
            + """

Profiles may also store custom scalar variables. If a custom key matches a
generated path, query, or header parameter for an operation, hctl fills it
automatically unless you pass an explicit flag for that call."""
        )
        return 0
    action = argv[0]
    if action == "profile":
        return command_config_profile(argv[1:])
    if action == "list":
        print_json(load_config().redacted())
        return 0
    if action == "get":
        if len(argv) != 2:
            raise ValueError("Usage: hctl config get KEY")
        key = argv[1]
        validate_config_key(key)
        value = load_config().redacted().get(key)
        if value is not None:
            print(value)
        return 0
    if action == "set":
        if len(argv) != 3:
            raise ValueError("Usage: hctl config set KEY VALUE")
        path = set_config_value(argv[1], argv[2])
        print(f"Wrote {path}")
        return 0
    if action == "unset":
        if len(argv) != 2:
            raise ValueError("Usage: hctl config unset KEY")
        path = unset_config_value(argv[1])
        print(f"Wrote {path}")
        return 0
    raise ValueError(f"Unknown config action: {action}")


def command_config_profile(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            """Usage:
  hctl config profile list [--json]
  hctl config profile current
  hctl config profile use NAME
  hctl config profile remove NAME --force
"""
        )
        return 0
    action = argv[0]
    rest = argv[1:]
    if action == "list":
        parser = argparse.ArgumentParser(prog="hctl config profile list")
        parser.add_argument("--json", action="store_true", help="Print JSON.")
        parsed = parser.parse_args(rest)
        return command_config_profile_list(parsed.json)
    if action == "current":
        if rest:
            raise ValueError("Usage: hctl config profile current")
        profile = current_profile_name() or "default"
        print(profile)
        return 0
    if action == "use":
        if len(rest) != 1:
            raise ValueError("Usage: hctl config profile use NAME")
        path = use_profile(rest[0])
        print(f"Active profile: {rest[0]}")
        print(f"Wrote {path}")
        return 0
    if action == "remove":
        parser = argparse.ArgumentParser(prog="hctl config profile remove")
        parser.add_argument("name")
        parser.add_argument("--force", action="store_true", help="Confirm removal.")
        parsed = parser.parse_args(rest)
        if not parsed.force:
            raise ValueError("Use --force to remove a profile.")
        path = remove_profile(parsed.name)
        print(f"Removed profile: {parsed.name}")
        print(f"Wrote {path}")
        return 0
    raise ValueError(f"Unknown config profile action: {action}")


def command_config_profile_list(json_output: bool) -> int:
    profiles = list_profiles()
    active = current_profile_name() or ("default" if "default" in profiles else None)
    rows = [
        {
            "profile": name,
            "active": name == active,
            "has_api_key": bool(_profile_api_key_source(name, values, profiles)),
            "api_key_source": _profile_api_key_source(name, values, profiles),
            "host": values.get("host", "https://app.harness.io"),
            "account": values.get("account"),
            "org": values.get("org"),
            "project": values.get("project"),
        }
        for name, values in sorted(profiles.items())
    ]
    if json_output:
        print_json(rows)
    else:
        print_table(
            ["profile", "active", "host", "account", "org", "project", "api_key"],
            [
                [
                    row["profile"],
                    "yes" if row["active"] else "",
                    row["host"],
                    row["account"] or "",
                    row["org"] or "",
                    row["project"] or "",
                    _profile_api_key_label(row["api_key_source"]),
                ]
                for row in rows
            ],
        )
    return 0


def _profile_api_key_source(
    profile: str,
    values: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
) -> str | None:
    if values.get("api_key"):
        return "profile"
    default_values = profiles.get(DEFAULT_PROFILE, {})
    if profile != DEFAULT_PROFILE and default_values.get("api_key"):
        return DEFAULT_PROFILE
    return None


def _profile_api_key_label(source: Any) -> str:
    if source == "profile":
        return "yes"
    if source == DEFAULT_PROFILE:
        return DEFAULT_PROFILE
    return ""


def command_auth(argv: list[str]) -> int:
    if argv and argv[0] not in {"status", "-h", "--help", "help"}:
        raise ValueError(f"Unknown auth action: {argv[0]}")
    if argv and argv[0] in {"-h", "--help", "help"}:
        print("Usage: hctl auth status")
        return 0
    config = load_config()
    data = {
        "host": config.host,
        "api_key": redact_secret(config.api_key) if config.api_key else None,
        "has_api_key": bool(config.api_key),
        "account": config.account,
        "org": config.org,
        "project": config.project,
        "profile": config.profile,
    }
    print_json(data)
    return 0


def command_doctor(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="hctl doctor",
        description="Check local Harness CLI setup.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    parser.add_argument(
        "--network",
        action="store_true",
        help="Also check reachability with GET /v1/version.",
    )
    parser.add_argument(
        "--fix-permissions",
        action="store_true",
        help="Repair config file permissions to 0600 when possible.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Network check timeout in seconds.",
    )
    parsed = parser.parse_args(argv)
    if parsed.timeout <= 0:
        raise ValueError("--timeout must be greater than zero")
    config_path = default_config_path()
    config = load_config()
    manifest = load_manifest()
    issues: list[str] = []
    fixed_permissions = False
    if not config.api_key:
        issues.append("No API key configured.")
    if config_path.exists():
        mode = config_path.stat().st_mode & 0o777
        if mode & 0o077:
            if parsed.fix_permissions:
                try:
                    config_path.chmod(0o600)
                    fixed_permissions = True
                    mode = config_path.stat().st_mode & 0o777
                except OSError as exc:
                    issues.append(f"Could not fix config file permissions: {exc}")
            if mode & 0o077:
                issues.append(f"Config file permissions are {mode:o}; expected 600.")
    else:
        issues.append(f"Config file does not exist at {config_path}.")
    network_check: dict[str, Any] | None = None
    if parsed.network:
        network_check = doctor_network_check(manifest, config, parsed.timeout)
        if not network_check["ok"]:
            issues.append(f"Network check failed: {network_check['message']}")
    data = {
        "ok": not issues,
        "config_path": str(config_path),
        "host": config.host,
        "profile": config.profile,
        "has_api_key": bool(config.api_key),
        "fixed_permissions": fixed_permissions,
        "operation_count": manifest.operation_count,
        "group_count": len(manifest.groups),
        "manifest_source": manifest.source,
        "network_check": network_check,
        "issues": issues,
    }
    if parsed.json:
        print_json(data)
    else:
        print(f"Config: {config_path}")
        print(f"Profile: {config.profile}")
        print(f"Host: {config.host}")
        print(f"API key: {'configured' if config.api_key else 'missing'}")
        if fixed_permissions:
            print("Config permissions: fixed to 600")
        print(f"Generated operations: {manifest.operation_count}")
        print(f"Generated groups: {len(manifest.groups)}")
        print_doctor_network_check(network_check)
        if issues:
            print("Issues:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("No local issues found.")
    return 0 if not issues else 1


def doctor_network_check(
    manifest: Manifest,
    config: HarnessConfig,
    timeout: float,
) -> dict[str, Any]:
    operation = manifest.by_operation_id.get("getVersion")
    if operation is None:
        return {
            "ok": False,
            "message": "Version operation is missing from the endpoint manifest.",
        }
    options = CallOptions(
        path_values={},
        query_values={},
        header_values={},
        param_values={},
        body=None,
        content_type=None,
        no_auth=True,
    )
    request = prepare_request(operation, config, options)
    try:
        response = send_request(request, timeout=timeout)
    except RequestError as exc:
        return {
            "ok": False,
            "method": request.method,
            "path": operation.path,
            "url": request.url,
            "message": str(exc),
        }
    message = f"{request.method} {operation.path} returned HTTP {response.status}"
    return {
        "ok": response.status < 400,
        "method": request.method,
        "path": operation.path,
        "url": request.url,
        "status": response.status,
        "message": message,
    }


def print_doctor_network_check(network_check: dict[str, Any] | None) -> None:
    if network_check is None:
        print("Network: skipped (run `hctl doctor --network`)")
        return
    symbol = glyph("ok" if network_check["ok"] else "fail", stream=sys.stdout)
    style = "green" if network_check["ok"] else "red"
    print(f"Network: {stylize(symbol, style)} {network_check['message']}")


def command_completion(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print("Usage: hctl completion bash|zsh|fish")
        return 0
    shell = argv[0]
    scripts = {
        "bash": _bash_completion_script,
        "zsh": _zsh_completion_script,
        "fish": _fish_completion_script,
    }
    script = scripts.get(shell)
    if not script:
        raise ValueError(f"Unknown shell: {shell}. Expected bash, zsh, or fish.")
    print(script())
    return 0


def command_internal_complete(argv: list[str]) -> int:
    current = ""
    current_supplied = False
    words: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--current":
            current_supplied = True
            current, index = _consume_value(argv, index)
        elif token == "--":
            words.extend(argv[index + 1 :])
            break
        else:
            words.append(token)
            index += 1

    if not current_supplied and current == "" and words:
        current = words[-1]
        words = words[:-1]

    manifest = load_manifest()
    for candidate in completion_candidates(manifest, words, current):
        print(candidate)
    return 0


def command_api(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            """Usage:
  hctl api info
  hctl api groups
  hctl api list [--search TEXT] [--tag TAG] [--method METHOD]
  hctl api describe OPERATION
  hctl api body OPERATION
  hctl api call OPERATION [flags]
"""
        )
        return 0
    manifest = load_manifest()
    action = argv[0]
    rest = argv[1:]
    if action == "info":
        return command_api_info(manifest, rest)
    if action == "groups":
        return command_api_groups(manifest, rest)
    if action == "list":
        return command_api_list(manifest, rest)
    if action == "describe":
        return command_api_describe(manifest, rest)
    if action == "body":
        return command_api_body(manifest, rest)
    if action == "call":
        return command_api_call(manifest, rest)
    raise ValueError(f"Unknown api action: {action}")


def command_api_info(manifest: Manifest, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hctl api info")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parsed = parser.parse_args(argv)
    data = {
        "api_title": manifest.raw.get("api_title", ""),
        "api_version": manifest.raw.get("api_version", ""),
        "operation_count": manifest.operation_count,
        "group_count": len(manifest.groups),
        "source": manifest.source,
        "source_hash": manifest.source_hash,
    }
    if parsed.json:
        print_json(data)
    else:
        print_table(["key", "value"], [[key, value] for key, value in data.items()])
    return 0


def command_api_groups(manifest: Manifest, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hctl api groups")
    parser.add_argument("--search", default=None, help="Search group slug or tag.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum rows to print.")
    parser.add_argument("--wide", action="store_true", help="Do not truncate table cells.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parsed = parser.parse_args(argv)
    if parsed.limit <= 0:
        raise ValueError("--limit must be greater than zero")
    search = parsed.search.lower() if parsed.search else None
    rows = []
    for group, label in sorted(manifest.groups.items(), key=lambda item: item[0]):
        if search and search not in group.lower() and search not in label.lower():
            continue
        rows.append(
            {
                "group": group,
                "tag": label,
                "operations": len(manifest.group_operations(group)),
            }
        )
    limited = rows[: parsed.limit]
    if parsed.json:
        print_json(limited)
    else:
        print_table(
            ["group", "tag", "operations"],
            [[r["group"], r["tag"], r["operations"]] for r in limited],
            fit_width=not parsed.wide,
            max_cell_width=None if parsed.wide else 80,
        )
        if len(rows) > len(limited):
            print(f"... {len(rows) - len(limited)} more. Increase --limit to show more.")
    return 0


def command_api_list(manifest: Manifest, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hctl api list")
    parser.add_argument("--search", default=None, help="Search operations.")
    parser.add_argument("--tag", default=None, help="Filter by tag display name.")
    parser.add_argument("--group", default=None, help="Filter by generated group slug.")
    parser.add_argument("--method", default=None, help="Filter by HTTP method.")
    parser.add_argument("--path", default=None, help="Filter by path substring.")
    parser.add_argument(
        "--has-body",
        action="store_true",
        help="Only include operations with request bodies.",
    )
    parser.add_argument(
        "--deprecated",
        action="store_true",
        help="Only include deprecated operations.",
    )
    parser.add_argument("--limit", type=int, default=50, help="Maximum rows to print.")
    parser.add_argument("--wide", action="store_true", help="Do not truncate table cells.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parsed = parser.parse_args(argv)
    method = _validate_http_method_filter(parsed.method)
    group = _validate_group_filter(manifest, parsed.group)
    operations = manifest.search(
        text=parsed.search,
        tag=parsed.tag,
        method=method,
        group=group,
        path=parsed.path,
        has_body=parsed.has_body,
        deprecated=parsed.deprecated,
    )
    if parsed.limit <= 0:
        raise ValueError("--limit must be greater than zero")
    limited = operations[: parsed.limit]
    if parsed.json:
        print_json([operation_to_dict(operation) for operation in limited])
    else:
        print_table(
            ["group", "operation", "method", "path", "summary"],
            [[op.group, op.command, op.method.upper(), op.path, op.summary] for op in limited],
            fit_width=not parsed.wide,
            max_cell_width=None if parsed.wide else 80,
        )
        if len(operations) > len(limited):
            print(f"... {len(operations) - len(limited)} more. Increase --limit to show more.")
    return 0


def command_api_describe(manifest: Manifest, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hctl api describe")
    parser.add_argument("operation", help="Operation id, command slug, or group/operation.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parsed = parser.parse_args(argv)
    operation = resolve_operation(manifest, parsed.operation)
    if parsed.json:
        print_json(operation_to_dict(operation))
    else:
        print_operation_detail(operation)
    return 0


def command_api_body(manifest: Manifest, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hctl api body")
    parser.add_argument("operation", help="Operation id, command slug, or group/operation.")
    parser.add_argument("--content-type", default=None, help="Request content type to sample.")
    parser.add_argument("--output-file", default=None, help="Write the template to a file.")
    parser.add_argument("--json", action="store_true", help="Include body metadata.")
    parsed = parser.parse_args(argv)
    operation = resolve_operation(manifest, parsed.operation)
    content_type, sample = request_body_sample(operation, parsed.content_type)
    if parsed.json:
        payload = {
            "operation_id": operation.operation_id,
            "content_type": content_type,
            "body": sample,
        }
        if parsed.output_file:
            write_json_file(parsed.output_file, payload)
        else:
            print_json(payload)
    elif parsed.output_file:
        write_text_file(parsed.output_file, body_template_text(content_type, sample))
    else:
        print_body_template(content_type, sample)
    return 0


def command_api_call(manifest: Manifest, argv: list[str]) -> int:
    if not argv or argv[0] in HELP_TOKENS:
        print_api_call_help()
        return 0
    operation = resolve_operation(manifest, argv[0])
    if call_help_requested(argv[1:]):
        print_operation_help(operation)
        return 0
    return call_operation(operation, argv[1:])


def command_generated(manifest: Manifest, argv: list[str]) -> int:
    group = argv[0]
    if group not in manifest.groups:
        if manifest.find_operation_matches(group):
            selected_operation = resolve_operation(manifest, group)
            if call_help_requested(argv[1:]):
                print_operation_help(selected_operation)
                return 0
            return call_operation(selected_operation, argv[1:])
        suggestions = difflib.get_close_matches(group, sorted(manifest.groups), n=5)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise ValueError(f"Unknown command or generated group: {group}.{hint}")
    if len(argv) == 1 or argv[1] in HELP_TOKENS:
        print_group_help(manifest, group)
        return 0
    command = argv[1]
    operation = manifest.by_group_command.get((group, command))
    if not operation:
        available = [op.command for op in manifest.group_operations(group)]
        suggestions = difflib.get_close_matches(command, available, n=5)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise ValueError(f"Unknown operation for group {group}: {command}.{hint}")
    if call_help_requested(argv[2:]):
        print_operation_help(operation)
        return 0
    return call_operation(operation, argv[2:])


def call_help_requested(argv: list[str]) -> bool:
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in HELP_TOKENS:
            return True
        if token in CALL_VALUE_FLAGS:
            index += 2
            continue
        if token.startswith("--") and "=" not in token and token not in CALL_BOOLEAN_FLAGS:
            index += 2
            continue
        index += 1
    return False


def call_operation(operation: Operation, argv: list[str]) -> int:
    config = load_config()
    options = parse_call_options(operation, argv, config)
    request = prepare_request(operation, config, options)
    if options.curl:
        if options.all_pages:
            raise ValueError("--curl cannot be combined with --all")
        render_curl(request)
        return 0
    if options.dry_run:
        render_dry_run(request)
        return 0
    with CallStatus(request.method, request.url) as status:
        if options.all_pages:
            response = send_paginated_request(
                operation,
                config,
                options,
                timeout=options.timeout,
            )
        else:
            response = send_request(request, timeout=options.timeout)
        status.done(response.status)
    render_response(
        response,
        include=options.include,
        output=options.output,
        output_file=options.output_file,
        table_columns=options.table_columns,
        unwrap_response=options.unwrap_response,
        jq_path=options.jq_path,
    )
    return 0 if response.status < 400 else 1


def parse_call_options(operation: Operation, argv: list[str], config: HarnessConfig) -> CallOptions:
    path_values: dict[str, str] = {}
    query_values: dict[str, list[str]] = {}
    header_values: dict[str, str] = {}
    param_values: dict[str, str] = {}
    form_values: dict[str, list[str]] = {}
    file_values: dict[str, list[str]] = {}
    body: str | None = None
    body_json = False
    body_template = False
    content_type: str | None = None
    include = False
    curl = False
    dry_run = False
    no_auth = False
    output = config.default_output
    output_file: str | None = None
    table_columns: list[str] = []
    unwrap_response = False
    jq_path: str | None = None
    all_pages = False
    all_page_size: int | None = None
    max_pages = 100
    timeout = 30.0
    host: str | None = None
    api_key: str | None = None

    parameter_names = {parameter.name for parameter in operation.parameters}
    parameter_by_name = {parameter.name: parameter for parameter in operation.parameters}
    parameter_flag_names = {
        _flag_name(parameter.name): parameter.name for parameter in operation.parameters
    }
    common_names = {
        "account": "account",
        "account-identifier": "accountIdentifier",
        "account-id": "accountID",
        "org": "org",
        "org-identifier": "orgIdentifier",
        "org-id": "orgId",
        "organization": "organization",
        "organization-identifier": "organizationIdentifier",
        "project": "project",
        "project-identifier": "projectIdentifier",
        "project-id": "projectId",
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--dry-run":
            dry_run = True
            index += 1
        elif token == "--curl":
            curl = True
            index += 1
        elif token == "--include":
            include = True
            index += 1
        elif token == "--no-auth":
            no_auth = True
            index += 1
        elif token in PAIR_FLAGS:
            value, index = _consume_value(argv, index)
            key, parsed_value = _split_pair(value)
            if token == "--path":
                path_values[key] = parsed_value
            elif token == "--query":
                query_values.setdefault(key, []).append(parsed_value)
            elif token == "--header":
                header_values[key] = parsed_value
            else:
                param_values[key] = parsed_value
        elif token == "--body":
            body, index = _consume_value(argv, index)
        elif token == "--body-json":
            body, index = _consume_value(argv, index)
            body_json = True
            if content_type is None:
                content_type = "application/json"
        elif token == "--body-file":
            value, index = _consume_value(argv, index)
            body = f"@{value}"
        elif token == "--body-template":
            body_template = True
            index += 1
        elif token == "--form":
            value, index = _consume_value(argv, index)
            key, parsed_value = _split_pair(value)
            form_values.setdefault(key, []).append(parsed_value)
        elif token == "--file":
            value, index = _consume_value(argv, index)
            key, parsed_value = _split_pair(value)
            file_values.setdefault(key, []).append(parsed_value)
        elif token == "--content-type":
            content_type, index = _consume_value(argv, index)
        elif token == "--columns":
            value, index = _consume_value(argv, index)
            table_columns.extend(_split_columns(value))
        elif token == "--unwrap":
            unwrap_response = True
            index += 1
        elif token == "--jq":
            jq_path, index = _consume_value(argv, index)
        elif token == "--output":
            output, index = _consume_value(argv, index)
            if output not in {"json", "raw", "table"}:
                raise ValueError("--output must be json, raw, or table")
        elif token == "--output-file":
            output_file, index = _consume_value(argv, index)
        elif token == "--all":
            all_pages = True
            index += 1
        elif token == "--all-page-size":
            value, index = _consume_value(argv, index)
            all_page_size = _parse_positive_int(value, "--all-page-size")
        elif token == "--max-pages":
            value, index = _consume_value(argv, index)
            max_pages = _parse_positive_int(value, "--max-pages")
        elif token == "--timeout":
            value, index = _consume_value(argv, index)
            timeout = _parse_positive_float(value, "--timeout")
        elif token == "--host":
            host, index = _consume_value(argv, index)
        elif token == "--api-key":
            api_key, index = _consume_value(argv, index)
        elif token.startswith("--"):
            name, value, index = _consume_dynamic_flag(argv, index)
            normalized_name = _flag_name(name)
            mapped = parameter_flag_names.get(normalized_name) or common_names.get(normalized_name)
            if not mapped:
                known = sorted(set(parameter_flag_names) | set(common_names))
                suggestions = difflib.get_close_matches(normalized_name, known, n=5)
                hint = (
                    f" Did you mean: {', '.join('--' + s for s in suggestions)}?"
                    if suggestions
                    else ""
                )
                raise ValueError(f"Unknown flag for {operation.operation_id}: --{name}.{hint}")
            if mapped in parameter_names or mapped in common_names.values():
                parameter = parameter_by_name.get(mapped)
                if parameter and parameter.location == "query":
                    query_values.setdefault(mapped, []).append(value)
                else:
                    param_values[mapped] = value
        else:
            raise ValueError(f"Unexpected argument: {token}")

    if not all_pages and (all_page_size is not None or max_pages != 100):
        raise ValueError("--all-page-size and --max-pages require --all")
    if table_columns and output != "table":
        raise ValueError("--columns requires --output table")
    if body_template:
        if body is not None or form_values or file_values:
            raise ValueError(
                "--body-template cannot be combined with other body, form, or file input."
            )
        content_type, body, body_json = request_body_template(operation, content_type)

    return CallOptions(
        path_values=path_values,
        query_values=query_values,
        header_values=header_values,
        param_values=param_values,
        body=body,
        content_type=content_type,
        body_json=body_json,
        form_values=form_values,
        file_values=file_values,
        include=include,
        curl=curl,
        dry_run=dry_run,
        no_auth=no_auth,
        output=output,
        output_file=output_file,
        table_columns=tuple(table_columns),
        unwrap_response=unwrap_response,
        jq_path=jq_path,
        all_pages=all_pages,
        all_page_size=all_page_size,
        max_pages=max_pages,
        timeout=timeout,
        host=host,
        api_key=api_key,
    )


def resolve_operation(manifest: Manifest, value: str) -> Operation:
    matches = manifest.find_operation_matches(value)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        if _interactive_operation_selection_enabled():
            return _prompt_for_operation(value, matches)
        raise ValueError(_ambiguous_operation_message(value, matches))
    suggestions = difflib.get_close_matches(value, sorted(manifest.by_operation_id), n=5)
    if not suggestions:
        suggestions = difflib.get_close_matches(value, sorted(manifest.by_command), n=5)
    hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    raise ValueError(f"Unknown operation: {value}.{hint}")


def _interactive_operation_selection_enabled() -> bool:
    return (
        bool(getattr(sys.stdin, "isatty", lambda: False)())
        and bool(getattr(sys.stderr, "isatty", lambda: False)())
        and os.environ.get("CI") is None
    )


def _prompt_for_operation(value: str, matches: list[Operation]) -> Operation:
    limit = min(len(matches), 20)
    print(f"Ambiguous operation {value!r}. Choose one:", file=sys.stderr)
    for index, operation in enumerate(matches[:limit], start=1):
        print(f"  {_operation_choice_line(index, operation)}", file=sys.stderr)
    if len(matches) > limit:
        print(
            f"  ... {len(matches) - limit} more; use `hctl api list --search {value}`.",
            file=sys.stderr,
        )
    while True:
        sys.stderr.write(f"Select operation [1-{limit}] (or q to cancel): ")
        sys.stderr.flush()
        choice = sys.stdin.readline()
        if not choice:
            raise ValueError(_ambiguous_operation_message(value, matches))
        normalized = choice.strip().lower()
        if normalized in {"", "q", "quit", "cancel"}:
            raise ValueError("Cancelled operation selection.")
        if normalized.isdigit():
            selected = int(normalized)
            if 1 <= selected <= limit:
                return matches[selected - 1]
        print(f"Enter a number from 1 to {limit}, or q to cancel.", file=sys.stderr)


def _ambiguous_operation_message(value: str, matches: list[Operation]) -> str:
    lines = [f"Ambiguous operation {value!r}. Use a fully-qualified operation:"]
    lines.extend(
        f"  {_operation_choice_line(index, operation)}"
        for index, operation in enumerate(matches[:10], start=1)
    )
    if len(matches) > 10:
        lines.append(f"  ... {len(matches) - 10} more. Run `hctl api list --search {value}`.")
    return "\n".join(lines)


def _operation_choice_line(index: int, operation: Operation) -> str:
    summary = f" - {operation.summary}" if operation.summary else ""
    return (
        f"{index}. {operation.group}/{operation.command} "
        f"({operation.operation_id}) {operation.method.upper()} {operation.path}{summary}"
    )


def print_group_help(manifest: Manifest, group: str) -> None:
    operations = manifest.group_operations(group)
    print(f"{manifest.groups[group]} ({group})")
    print()
    print(f"Usage: hctl {group} OPERATION [flags]")
    print()
    rows = [[op.command, op.method.upper(), op.path, op.summary] for op in operations[:100]]
    print_table(["operation", "method", "path", "summary"], rows)
    if len(operations) > 100:
        print(
            f"... {len(operations) - 100} more. "
            f"Use `hctl api list --tag {manifest.groups[group]!r}`."
        )


def print_operation_help(operation: Operation) -> None:
    print(f"{operation.operation_id}")
    print()
    print(f"Usage: hctl {operation.group} {operation.command} [flags]")
    print(f"       hctl api call {operation.operation_id} [flags]")
    print()
    print(f"{operation.method.upper()} {operation.path}")
    if operation.summary:
        print(operation.summary)
    if operation.description:
        print()
        print(_one_line(operation.description, 500))
    if operation.parameters:
        print()
        print("Parameters:")
        for parameter in operation.parameters:
            required = "required" if parameter.required else "optional"
            flag = f"--{_flag_name(parameter.name)}"
            details = [parameter.location, required]
            if parameter.default is not None:
                details.append(f"default: {parameter.default}")
            if parameter.enum:
                details.append("one of: " + ", ".join(str(value) for value in parameter.enum[:8]))
            print(f"  {flag} ({'; '.join(details)})")
    if operation.request_body:
        required = "required" if operation.request_body.required else "optional"
        print()
        print(f"Body: {required}; content types: {', '.join(operation.request_body.content_types)}")
        print(f"Body template: hctl api body {operation.operation_id}")
        print("Send template: add --body-template")
    pagination = pagination_help(operation)
    if pagination:
        print()
        print(f"Pagination: {pagination}")
    examples = operation_examples(operation)
    if examples:
        print()
        print("Examples:")
        for example in examples:
            print(f"  {example}")
    print()
    print_call_flags_help()


def print_api_call_help() -> None:
    print(
        """Usage:
  hctl api call OPERATION [flags]
  hctl api call OPERATION --help

Call any generated Harness API operation by operation id, command slug, or
group/operation pair.

Examples:
  hctl api call list-roles-acc --query limit=10
  hctl api call account-roles/list-roles-acc --curl
  hctl api call create-role-acc --body @role.json
"""
    )
    print_call_flags_help()


def print_call_flags_help() -> None:
    print("Generic flags:")
    for flag in [
        "--path key=value",
        "--query key=value",
        "--header key=value",
        "--param key=value",
        "--body VALUE|@file|-",
        "--body-file path",
        "--body-json JSON",
        "--body-template",
        "--form key=value",
        "--file field=@path",
        "--content-type value",
        "--columns a,b,c",
        "--unwrap",
        "--jq path",
        "--output json|raw|table",
        "--output-file path",
        "--all",
        "--all-page-size N",
        "--max-pages N",
        "--curl",
        "--dry-run",
        "--include",
        "--timeout seconds",
        "--host http(s)-url",
        "--api-key KEY",
        "--no-auth",
    ]:
        print(f"  {flag}")


def print_operation_detail(operation: Operation) -> None:
    print(f"Operation: {operation.operation_id}")
    print(f"Command: {operation.group}/{operation.command}")
    print(f"Tag: {operation.tag}")
    print(f"Request: {operation.method.upper()} {operation.path}")
    if operation.summary:
        print(f"Summary: {operation.summary}")
    if operation.docs_url:
        print(f"Docs: {operation.docs_url}")
    if operation.parameters:
        print()
        print_table(
            ["name", "in", "required", "type", "default", "enum", "description"],
            [
                [
                    parameter.name,
                    parameter.location,
                    "yes" if parameter.required else "no",
                    parameter.schema_type or "",
                    "" if parameter.default is None else str(parameter.default),
                    ", ".join(str(value) for value in parameter.enum[:8]),
                    _one_line(parameter.description, 80),
                ]
                for parameter in operation.parameters
            ],
        )
    if operation.request_body:
        print()
        print(
            "Body: "
            + ("required" if operation.request_body.required else "optional")
            + f" ({', '.join(operation.request_body.content_types)})"
        )
        print(f"Body template: hctl api body {operation.operation_id}")
        print("Send template: add --body-template")
    pagination = pagination_help(operation)
    if pagination:
        print()
        print(f"Pagination: {pagination}")
    examples = operation_examples(operation)
    if examples:
        print()
        print("Examples:")
        for example in examples:
            print(f"  {example}")


def operation_examples(operation: Operation) -> list[str]:
    required_flags = _example_required_flags(operation)
    examples = [
        f"hctl {operation.group} {operation.command}{required_flags}",
        f"hctl api call {operation.operation_id}{_example_required_pairs(operation)}",
    ]
    examples[0] += _example_body_flags(operation)
    if pagination_help(operation):
        examples.append(f"hctl {operation.group} {operation.command} --all --output table")
    examples.append(f"hctl {operation.group} {operation.command}{required_flags} --dry-run")
    return examples


def request_body_sample(operation: Operation, content_type: str | None) -> tuple[str, Any]:
    request_body = operation.request_body
    if not request_body:
        raise ValueError(f"Operation {operation.operation_id} does not define a request body.")
    samples = request_body.samples or {}
    if content_type:
        if content_type not in request_body.content_types:
            available = ", ".join(request_body.content_types)
            raise ValueError(
                f"Unknown content type for {operation.operation_id}: {content_type}. "
                f"Available: {available}"
            )
        return content_type, samples.get(content_type, {})
    for preferred in ("application/json", "application/yaml", "application/x-yaml"):
        if preferred in samples:
            return preferred, samples[preferred]
    if samples:
        selected = sorted(samples)[0]
        return selected, samples[selected]
    selected = request_body.content_types[0] if request_body.content_types else "application/json"
    return selected, {}


def request_body_template(
    operation: Operation,
    content_type: str | None,
) -> tuple[str, str, bool]:
    selected_content_type, sample = request_body_sample(operation, content_type)
    is_json = _is_json_content_type(selected_content_type)
    if isinstance(sample, str):
        return selected_content_type, sample, is_json
    if is_json:
        return selected_content_type, json.dumps(sample, indent=2, sort_keys=True), True
    if _is_yaml_content_type(selected_content_type):
        return selected_content_type, body_template_text(selected_content_type, sample), False
    raise ValueError(
        "--body-template can only serialize structured samples for JSON or YAML content types. "
        f"Use `hctl api body {operation.operation_id}` and pass the result with "
        "--body instead."
    )


def print_body_template(content_type: str, payload: Any) -> None:
    if _is_json_content_type(content_type):
        print_json(payload)
        return
    sys.stdout.write(body_template_text(content_type, payload))


def body_template_text(content_type: str, payload: Any) -> str:
    if isinstance(payload, str):
        text = payload
    elif _is_yaml_content_type(content_type):
        text = _yaml_template(payload)
    else:
        text = json.dumps(payload, indent=2, sort_keys=True)
    return text if text.endswith("\n") else text + "\n"


def write_json_file(output_file: str, payload: Any) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    write_text_file(output_file, text)


def write_text_file(output_file: str, text: str) -> None:
    if output_file == "-":
        sys.stdout.write(text)
        return
    path = Path(output_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise ValueError(f"Could not write output file {path}: {detail}") from exc
    print_notice(f"Wrote {path} ({len(text.encode('utf-8'))} bytes)")


def _example_required_flags(operation: Operation) -> str:
    parts = []
    for parameter in operation.parameters:
        if not parameter.required or parameter.location not in {"path", "query", "header"}:
            continue
        if parameter.name == "Harness-Account":
            parts.append("--account ACCOUNT")
        else:
            parts.append(f"--{_flag_name(parameter.name)} {_placeholder(parameter.name)}")
    return f" {' '.join(parts)}" if parts else ""


def _example_required_pairs(operation: Operation) -> str:
    parts = []
    for parameter in operation.parameters:
        if not parameter.required or parameter.location not in {"path", "query", "header"}:
            continue
        value = _placeholder(parameter.name)
        if parameter.location == "path":
            parts.append(f"--path {parameter.name}={value}")
        elif parameter.location == "query":
            parts.append(f"--query {parameter.name}={value}")
        else:
            parts.append(f"--header {parameter.name}={value}")
    return f" {' '.join(parts)}" if parts else ""


def _example_body_flags(operation: Operation) -> str:
    if not operation.request_body:
        return ""
    content_types = set(operation.request_body.content_types)
    if "multipart/form-data" in content_types:
        return " --form field=value --file file=@path"
    if "application/x-www-form-urlencoded" in content_types:
        return " --form field=value --content-type application/x-www-form-urlencoded"
    return " --body @body.json"


def _is_json_content_type(content_type: str) -> bool:
    return content_type == "application/json" or content_type.endswith("+json")


def _is_yaml_content_type(content_type: str) -> bool:
    return "yaml" in content_type


def _yaml_template(value: Any, *, indent: int = 0) -> str:
    return "\n".join(_yaml_lines(value, indent=indent))


def _yaml_lines(value: Any, *, indent: int) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return [pad + "{}"]
        lines: list[str] = []
        for key, item in value.items():
            key_text = _yaml_scalar(str(key))
            if isinstance(item, dict | list):
                lines.append(f"{pad}{key_text}:")
                lines.extend(_yaml_lines(item, indent=indent + 2))
            else:
                lines.append(f"{pad}{key_text}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [pad + "[]"]
        list_lines: list[str] = []
        for item in value:
            if isinstance(item, dict):
                if not item:
                    list_lines.append(pad + "- {}")
                    continue
                first = True
                for key, nested in item.items():
                    key_text = _yaml_scalar(str(key))
                    prefix = "- " if first else "  "
                    if isinstance(nested, dict | list):
                        list_lines.append(f"{pad}{prefix}{key_text}:")
                        list_lines.extend(_yaml_lines(nested, indent=indent + 4))
                    else:
                        list_lines.append(f"{pad}{prefix}{key_text}: {_yaml_scalar(nested)}")
                    first = False
            elif isinstance(item, list):
                list_lines.append(pad + "-")
                list_lines.extend(_yaml_lines(item, indent=indent + 2))
            else:
                list_lines.append(f"{pad}- {_yaml_scalar(item)}")
        return list_lines
    return [pad + _yaml_scalar(value)]


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    if "\n" in text:
        return json.dumps(text)
    lowered = text.lower()
    if lowered in {"true", "false", "null", "~"}:
        return json.dumps(text)
    if re.fullmatch(r"[A-Za-z0-9_./:@+=,-]+(?: [A-Za-z0-9_./:@+=,-]+)*", text):
        return text
    return json.dumps(text)


def _placeholder(name: str) -> str:
    if name == "Harness-Account":
        return "ACCOUNT"
    normalized = _flag_name(name).replace("-", "_").upper()
    if "ACCOUNT" in normalized:
        return "ACCOUNT"
    if normalized in {"ORG", "ORGANIZATION", "ORG_IDENTIFIER"}:
        return "ORG"
    if "PROJECT" in normalized:
        return "PROJECT"
    if "IDENTIFIER" in normalized:
        return "IDENTIFIER"
    return normalized or "VALUE"


def operation_to_dict(operation: Operation) -> dict[str, Any]:
    return {
        "operation_id": operation.operation_id,
        "command": operation.command,
        "group": operation.group,
        "tag": operation.tag,
        "method": operation.method,
        "path": operation.path,
        "summary": operation.summary,
        "description": operation.description,
        "deprecated": operation.deprecated,
        "docs_url": operation.docs_url,
        "parameters": [
            {
                "name": parameter.name,
                "in": parameter.location,
                "required": parameter.required,
                "description": parameter.description,
                "schema_type": parameter.schema_type,
                "default": parameter.default,
                "enum": list(parameter.enum),
            }
            for parameter in operation.parameters
        ],
        "request_body": {
            "required": operation.request_body.required,
            "content_types": list(operation.request_body.content_types),
            "description": operation.request_body.description,
            "samples": operation.request_body.samples or {},
        }
        if operation.request_body
        else None,
    }


def completion_candidates(manifest: Manifest, words: list[str], current: str) -> list[str]:
    if words and words[-1] == "--profile":
        return _filter_candidates(sorted(list_profiles()), current)
    if words and words[-1] == "--config":
        return []
    words = strip_leading_global_options(words)
    if words and words[-1] == "--output":
        return _filter_candidates(["json", "raw", "table"], current)
    if words and words[-1] == "--method":
        return _filter_candidates(sorted(HTTP_METHODS), current)
    if len(words) >= 2 and words[0] == "api" and words[1] == "list" and words[-1] == "--group":
        return _filter_candidates(sorted(manifest.groups), current)

    if not words:
        candidates = _top_level_completion_candidates(manifest)
        if current:
            candidates.extend(_operation_completion_candidates(manifest))
        return _filter_candidates(candidates, current)

    command = words[0]
    if command == "completion":
        return _filter_candidates(["bash", "fish", "zsh"], current)
    if command == "config":
        return _config_completion_candidates(words[1:], current)
    if command == "auth":
        return _filter_candidates(["status"], current) if len(words) == 1 else []
    if command == "doctor":
        return _filter_candidates(
            ["--fix-permissions", "--json", "--network", "--timeout", "--help"], current
        )
    if command == "init":
        return _filter_candidates(
            [
                "--host",
                "--api-key",
                "--account",
                "--org",
                "--project",
                "--profile",
                "--output",
                "--non-interactive",
                "--overwrite",
                "--help",
            ],
            current,
        )
    if command == "api":
        return _api_completion_candidates(manifest, words[1:], current)
    if command in manifest.groups:
        return _generated_completion_candidates(manifest, command, words[1:], current)
    operation = manifest.find_operation(command)
    if operation:
        if words[-1] == "--content-type" and operation.request_body:
            return _filter_candidates(list(operation.request_body.content_types), current)
        return _operation_flag_completion_candidates(operation, current)
    return []


def strip_leading_global_options(words: list[str]) -> list[str]:
    index = 0
    while index < len(words):
        token = words[index]
        if token in GLOBAL_FLAGS:
            index += 2
            continue
        if token.startswith("--profile=") or token.startswith("--config="):
            index += 1
            continue
        break
    return words[index:]


def _api_completion_candidates(manifest: Manifest, words: list[str], current: str) -> list[str]:
    if not words:
        return _filter_candidates(["body", "call", "describe", "groups", "info", "list"], current)
    action = words[0]
    if action in {"body", "call", "describe"}:
        if len(words) == 1:
            return _filter_candidates(_operation_completion_candidates(manifest), current)
        operation = manifest.find_operation(words[1])
        if action == "body":
            if words[-1] == "--content-type" and operation and operation.request_body:
                return _filter_candidates(list(operation.request_body.content_types), current)
            return _filter_candidates(
                ["--content-type", "--output-file", "--json", "--help"], current
            )
        if (
            action == "call"
            and words[-1] == "--content-type"
            and operation
            and operation.request_body
        ):
            return _filter_candidates(list(operation.request_body.content_types), current)
        if action == "call" and operation:
            return _operation_flag_completion_candidates(operation, current)
        return []
    if action == "groups":
        return _filter_candidates(["--search", "--limit", "--wide", "--json", "--help"], current)
    if action == "info":
        return _filter_candidates(["--json", "--help"], current)
    if action == "list":
        return _filter_candidates(
            [
                "--search",
                "--tag",
                "--group",
                "--method",
                "--path",
                "--has-body",
                "--deprecated",
                "--limit",
                "--wide",
                "--json",
                "--help",
            ],
            current,
        )
    return _filter_candidates(["body", "call", "describe", "groups", "info", "list"], current)


def _config_completion_candidates(words: list[str], current: str) -> list[str]:
    actions = ["get", "list", "profile", "set", "unset"]
    if not words:
        return _filter_candidates(actions, current)
    action = words[0]
    if action == "profile":
        return _config_profile_completion_candidates(words[1:], current)
    if action in {"get", "set", "unset"} and len(words) == 1:
        return _filter_candidates(_config_key_completion_candidates(), current)
    return []


def _config_key_completion_candidates() -> list[str]:
    candidates = set(BUILTIN_CONFIG_KEYS)
    with contextlib.suppress(Exception):
        candidates.update(read_config_file())
    return sorted(candidates)


def _config_profile_completion_candidates(words: list[str], current: str) -> list[str]:
    actions = ["current", "list", "remove", "use"]
    if not words:
        return _filter_candidates(actions, current)
    action = words[0]
    if action == "list":
        return _filter_candidates(["--json", "--help"], current)
    if action == "remove":
        if len(words) == 1:
            return _filter_candidates(sorted(list_profiles()), current)
        return _filter_candidates(["--force", "--help"], current)
    if action == "use" and len(words) == 1:
        return _filter_candidates(sorted(list_profiles()), current)
    return []


def _generated_completion_candidates(
    manifest: Manifest,
    group: str,
    words: list[str],
    current: str,
) -> list[str]:
    if not words:
        operations = [operation.command for operation in manifest.group_operations(group)]
        return _filter_candidates(operations, current)
    operation = manifest.by_group_command.get((group, words[0]))
    if not operation:
        return []
    if words[-1] == "--content-type" and operation.request_body:
        return _filter_candidates(list(operation.request_body.content_types), current)
    return _operation_flag_completion_candidates(operation, current)


def _operation_flag_completion_candidates(operation: Operation, current: str) -> list[str]:
    parameter_flags = [f"--{_flag_name(parameter.name)}" for parameter in operation.parameters]
    return _filter_candidates(
        [*parameter_flags, *COMMON_PARAMETER_FLAGS, *GENERIC_CALL_FLAGS],
        current,
    )


def _top_level_completion_candidates(manifest: Manifest) -> list[str]:
    return ["--config", "--profile", *sorted(BUILTIN_COMMANDS), *sorted(manifest.groups)]


def _operation_completion_candidates(manifest: Manifest) -> list[str]:
    candidates: list[str] = []
    for operation in manifest.operations:
        candidates.append(operation.operation_id)
        candidates.append(f"{operation.group}/{operation.command}")
        if len(manifest.by_command.get(operation.command, ())) == 1:
            candidates.append(operation.command)
    return candidates


def _filter_candidates(candidates: list[str], current: str) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        if current and not candidate.startswith(current):
            continue
        unique.append(candidate)
        seen.add(candidate)
    return unique


def _bash_completion_script() -> str:
    return r"""# bash completion for hctl
_hctl_complete() {
    local current
    current="${COMP_WORDS[COMP_CWORD]}"
    local -a words
    words=("${COMP_WORDS[@]:1:COMP_CWORD-1}")
    mapfile -t COMPREPLY < <(hctl __complete --current "$current" -- "${words[@]}")
}

complete -F _hctl_complete hctl"""


def _zsh_completion_script() -> str:
    return """#compdef hctl

_hctl() {
    local current
    current="${words[$CURRENT]}"
    local -a prior completions
    prior=("${words[@]:1:$((CURRENT - 2))}")
    completions=("${(@f)$(hctl __complete --current "$current" -- "${prior[@]}")}")
    compadd -- "${completions[@]}"
}

_hctl "$@"
"""


def _fish_completion_script() -> str:
    return """function __hctl_complete
    set -l current (commandline -ct)
    set -l tokens (commandline -opc)
    if test (count $tokens) -gt 0
        set -e tokens[1]
    end
    if test -n "$current"; and test (count $tokens) -gt 0
        set -l last_index (count $tokens)
        if test $tokens[$last_index] = "$current"
            set -e tokens[$last_index]
        end
    end
    hctl __complete --current "$current" -- $tokens
end

complete -c hctl -f -a "(__hctl_complete)"
"""


def _consume_value(argv: list[str], index: int) -> tuple[str, int]:
    if index + 1 >= len(argv):
        raise ValueError(f"Expected value after {argv[index]}")
    return argv[index + 1], index + 2


def _consume_dynamic_flag(argv: list[str], index: int) -> tuple[str, str, int]:
    token = argv[index]
    name_value = token[2:]
    if "=" in name_value:
        name, value = name_value.split("=", 1)
        return name, value, index + 1
    if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
        raise ValueError(f"Expected value after {token}")
    return name_value, argv[index + 1], index + 2


def _split_pair(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"Expected key=value, got {value}")
    key, parsed_value = value.split("=", 1)
    if not key:
        raise ValueError("Pair key cannot be empty")
    return key, parsed_value


def _split_columns(value: str) -> list[str]:
    columns = [item.strip() for item in value.split(",") if item.strip()]
    if not columns:
        raise ValueError("--columns requires at least one column name")
    return columns


def _parse_positive_int(value: str, flag: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{flag} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{flag} must be greater than zero")
    return parsed


def _parse_positive_float(value: str, flag: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{flag} must be a number of seconds") from exc
    if parsed <= 0:
        raise ValueError(f"{flag} must be greater than zero")
    return parsed


def _validate_http_method_filter(value: str | None) -> str | None:
    if value is None:
        return None
    method = value.lower()
    if method not in HTTP_METHODS:
        choices = ", ".join(sorted(HTTP_METHODS))
        raise ValueError(f"--method must be one of: {choices}")
    return method


def _validate_group_filter(manifest: Manifest, value: str | None) -> str | None:
    if value is None:
        return None
    group = value.lower()
    if group not in manifest.groups:
        suggestions = difflib.get_close_matches(group, sorted(manifest.groups), n=5)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise ValueError(f"Unknown API group: {value}.{hint}")
    return group


def _flag_name(name: str) -> str:
    text = name.replace("_", "-")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    return text.lower()


def _one_line(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _print_init_intro(path: Any, profile: str) -> None:
    print(stylize("Harness CLI onboarding", "bold"))
    print("Let's set up a local profile for fast, tidy Harness API calls.")
    print("Required: API key for authenticated calls.")
    print("Optional: account, org, project, and other defaults can be added anytime.")
    print(f"Config: {path}")
    print(f"Profile: {profile}")
    print()


def _print_init_summary(
    path: Any,
    profile: str,
    values: dict[str, Any],
    *,
    api_key_source: str | None,
) -> None:
    api_key_status = "missing"
    if values.get("api_key"):
        api_key_status = "configured"
    elif api_key_source == DEFAULT_PROFILE:
        api_key_status = "inherited from default"
    print()
    print(
        f"{stylize(glyph('ok', stream=sys.stdout), 'green')} "
        f"Profile {stylize(profile, 'bold')} is ready"
    )
    print_table(
        ["setting", "value"],
        [
            ["config", path],
            ["host", values.get("host") or "https://app.harness.io"],
            ["api_key (required for calls)", api_key_status],
            ["account (optional default)", values.get("account") or ""],
            ["org (optional default)", values.get("org") or ""],
            ["project (optional default)", values.get("project") or ""],
            ["default_output (optional)", values.get("default_output") or "json"],
        ],
    )
    print()
    print("Next steps:")
    print("  hctl doctor")
    print("  hctl api list --search pipeline")
    print("  hctl account-roles list-roles-acc --dry-run")


def _prompt_choice(label: str, choices: list[str], default: str) -> str:
    selected_default = default if default in choices else choices[0]
    if not sys.stdin.isatty():
        return selected_default
    choice_text = "/".join(choices)
    while True:
        value = input(f"{label} [{selected_default}] ({choice_text}): ").strip().lower()
        if not value:
            return selected_default
        if value in choices:
            return value
        print(f"Expected one of: {', '.join(choices)}")


def _prompt(label: str, default: str, *, secret: bool = False) -> str:
    suffix = f" [{redact_secret(default) if secret and default else default}]" if default else ""
    prompt = f"{label}{suffix}: "
    if not sys.stdin.isatty():
        return default
    value = getpass.getpass(prompt) if secret else input(prompt)
    return value.strip() or default
