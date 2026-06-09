from __future__ import annotations

import argparse
import difflib
import getpass
import os
import re
import sys
from typing import Any

from . import __version__
from .config import (
    VALID_CONFIG_KEYS,
    HarnessConfig,
    default_config_path,
    load_config,
    read_config_file,
    redact_secret,
    set_config_value,
    unset_config_value,
    write_config_file,
)
from .http import CallOptions, prepare_request, render_dry_run, render_response, send_request
from .manifest import Manifest, Operation, load_manifest
from .render import print_error, print_json, print_table

BUILTIN_COMMANDS = {"init", "config", "auth", "doctor", "api", "version"}
PAIR_FLAGS = {"--path", "--query", "--header", "--param"}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args or args[0] in {"-h", "--help", "help"}:
            print_top_level_help()
            return 0
        if args[0] in {"-V", "--version", "version"}:
            print(f"harness {__version__}")
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

        manifest = load_manifest()
        return command_generated(manifest, args)
    except KeyboardInterrupt:
        print_error("Interrupted.")
        return 130
    except (KeyError, ValueError) as exc:
        print_error(str(exc))
        return 2
    except BrokenPipeError:
        return 1


def print_top_level_help() -> None:
    print(
        """Harness CLI

Usage:
  harness init
  harness api list [--search TEXT] [--tag TAG]
  harness api describe OPERATION
  harness api call OPERATION [flags]
  harness <group> <operation> [flags]

Built-in commands:
  init        Run onboarding and write local config
  config      Read and update local config
  auth        Show authentication status
  doctor      Check local setup and generated manifest
  api         Discover and call generated API operations
  version     Print CLI version

Examples:
  harness init
  harness api list --search pipeline
  harness api describe list-roles-acc
  harness api call list-roles-acc --query limit=10
  harness account-roles list-roles-acc --limit 10 --dry-run
"""
    )


def command_init(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="harness init", description="Configure Harness CLI.")
    parser.add_argument("--host", default=None, help="Harness host URL.")
    parser.add_argument("--api-key", default=None, help="Harness API key.")
    parser.add_argument("--account", default=None, help="Default Harness account identifier.")
    parser.add_argument("--org", default=None, help="Default organization identifier.")
    parser.add_argument("--project", default=None, help="Default project identifier.")
    parser.add_argument(
        "--output",
        default=None,
        choices=["json", "raw"],
        help="Default output mode.",
    )
    parser.add_argument("--non-interactive", action="store_true", help="Do not prompt.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing values.")
    parsed = parser.parse_args(argv)

    path = default_config_path()
    existing = {} if parsed.overwrite else read_config_file(path)

    values: dict[str, Any] = dict(existing)
    values["host"] = parsed.host or values.get("host") or "https://app.harness.io"
    values["api_key"] = parsed.api_key or values.get("api_key") or os.environ.get("HARNESS_API_KEY")
    values["account"] = parsed.account or values.get("account")
    values["org"] = parsed.org or values.get("org")
    values["project"] = parsed.project or values.get("project")
    values["default_output"] = parsed.output or values.get("default_output") or "json"

    if not parsed.non_interactive:
        print("Harness CLI onboarding")
        values["host"] = _prompt("Host", str(values["host"])) or values["host"]
        values["api_key"] = (
            _prompt("API key", str(values["api_key"] or ""), secret=True) or values["api_key"]
        )
        values["account"] = _prompt("Default account", values.get("account") or "") or values.get(
            "account"
        )
        values["org"] = _prompt("Default org", values.get("org") or "") or values.get("org")
        values["project"] = _prompt("Default project", values.get("project") or "") or values.get(
            "project"
        )

    if not values.get("api_key"):
        print("No API key saved. Set HARNESS_API_KEY or run `harness config set api_key ...`.")

    written = write_config_file(values, path)
    print(f"Wrote {written}")
    print("Run `harness doctor` to check the setup.")
    return 0


def command_config(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            """Usage:
  harness config list
  harness config get KEY
  harness config set KEY VALUE
  harness config unset KEY

Keys: """
            + ", ".join(sorted(VALID_CONFIG_KEYS))
        )
        return 0
    action = argv[0]
    if action == "list":
        print_json(load_config().redacted())
        return 0
    if action == "get":
        if len(argv) != 2:
            raise ValueError("Usage: harness config get KEY")
        key = argv[1]
        if key not in VALID_CONFIG_KEYS:
            raise KeyError(f"Unknown config key: {key}")
        value = load_config().redacted().get(key)
        if value is not None:
            print(value)
        return 0
    if action == "set":
        if len(argv) != 3:
            raise ValueError("Usage: harness config set KEY VALUE")
        path = set_config_value(argv[1], argv[2])
        print(f"Wrote {path}")
        return 0
    if action == "unset":
        if len(argv) != 2:
            raise ValueError("Usage: harness config unset KEY")
        path = unset_config_value(argv[1])
        print(f"Wrote {path}")
        return 0
    raise ValueError(f"Unknown config action: {action}")


def command_auth(argv: list[str]) -> int:
    if argv and argv[0] not in {"status", "-h", "--help", "help"}:
        raise ValueError(f"Unknown auth action: {argv[0]}")
    if argv and argv[0] in {"-h", "--help", "help"}:
        print("Usage: harness auth status")
        return 0
    config = load_config()
    data = {
        "host": config.host,
        "api_key": redact_secret(config.api_key) if config.api_key else None,
        "has_api_key": bool(config.api_key),
        "account": config.account,
        "org": config.org,
        "project": config.project,
    }
    print_json(data)
    return 0


def command_doctor(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="harness doctor",
        description="Check local Harness CLI setup.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    parsed = parser.parse_args(argv)
    config_path = default_config_path()
    config = load_config()
    manifest = load_manifest()
    issues = []
    if not config.api_key:
        issues.append("No API key configured.")
    if config_path.exists():
        mode = config_path.stat().st_mode & 0o777
        if mode & 0o077:
            issues.append(f"Config file permissions are {mode:o}; expected 600.")
    else:
        issues.append(f"Config file does not exist at {config_path}.")
    data = {
        "ok": not issues,
        "config_path": str(config_path),
        "host": config.host,
        "has_api_key": bool(config.api_key),
        "operation_count": manifest.operation_count,
        "group_count": len(manifest.groups),
        "manifest_source": manifest.source,
        "issues": issues,
    }
    if parsed.json:
        print_json(data)
    else:
        print(f"Config: {config_path}")
        print(f"Host: {config.host}")
        print(f"API key: {'configured' if config.api_key else 'missing'}")
        print(f"Generated operations: {manifest.operation_count}")
        print(f"Generated groups: {len(manifest.groups)}")
        if issues:
            print("Issues:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("No local issues found.")
    return 0 if not issues else 1


def command_api(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            """Usage:
  harness api groups
  harness api list [--search TEXT] [--tag TAG] [--method METHOD]
  harness api describe OPERATION
  harness api call OPERATION [flags]
"""
        )
        return 0
    manifest = load_manifest()
    action = argv[0]
    rest = argv[1:]
    if action == "groups":
        return command_api_groups(manifest, rest)
    if action == "list":
        return command_api_list(manifest, rest)
    if action == "describe":
        return command_api_describe(manifest, rest)
    if action == "call":
        return command_api_call(manifest, rest)
    raise ValueError(f"Unknown api action: {action}")


def command_api_groups(manifest: Manifest, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="harness api groups")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parsed = parser.parse_args(argv)
    rows = []
    for group, label in sorted(manifest.groups.items(), key=lambda item: item[0]):
        rows.append(
            {
                "group": group,
                "tag": label,
                "operations": len(manifest.group_operations(group)),
            }
        )
    if parsed.json:
        print_json(rows)
    else:
        print_table(
            ["group", "tag", "operations"],
            [[r["group"], r["tag"], r["operations"]] for r in rows],
        )
    return 0


def command_api_list(manifest: Manifest, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="harness api list")
    parser.add_argument("--search", default=None, help="Search operations.")
    parser.add_argument("--tag", default=None, help="Filter by tag display name.")
    parser.add_argument("--method", default=None, help="Filter by HTTP method.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum rows to print.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parsed = parser.parse_args(argv)
    operations = manifest.search(text=parsed.search, tag=parsed.tag, method=parsed.method)
    limited = operations[: parsed.limit]
    if parsed.json:
        print_json([operation_to_dict(operation) for operation in limited])
    else:
        print_table(
            ["group", "operation", "method", "path", "summary"],
            [
                [op.group, op.command, op.method.upper(), op.path, op.summary]
                for op in limited
            ],
        )
        if len(operations) > len(limited):
            print(f"... {len(operations) - len(limited)} more. Increase --limit to show more.")
    return 0


def command_api_describe(manifest: Manifest, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="harness api describe")
    parser.add_argument("operation", help="Operation id, command slug, or group/operation.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parsed = parser.parse_args(argv)
    operation = resolve_operation(manifest, parsed.operation)
    if parsed.json:
        print_json(operation_to_dict(operation))
    else:
        print_operation_detail(operation)
    return 0


def command_api_call(manifest: Manifest, argv: list[str]) -> int:
    if not argv:
        raise ValueError("Usage: harness api call OPERATION [flags]")
    operation = resolve_operation(manifest, argv[0])
    return call_operation(operation, argv[1:])


def command_generated(manifest: Manifest, argv: list[str]) -> int:
    group = argv[0]
    if group not in manifest.groups:
        suggestions = difflib.get_close_matches(group, sorted(manifest.groups), n=5)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise ValueError(f"Unknown command or generated group: {group}.{hint}")
    if len(argv) == 1 or argv[1] in {"-h", "--help", "help"}:
        print_group_help(manifest, group)
        return 0
    command = argv[1]
    operation = manifest.by_group_command.get((group, command))
    if not operation:
        available = [op.command for op in manifest.group_operations(group)]
        suggestions = difflib.get_close_matches(command, available, n=5)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise ValueError(f"Unknown operation for group {group}: {command}.{hint}")
    if len(argv) > 2 and argv[2] in {"-h", "--help", "help"}:
        print_operation_help(operation)
        return 0
    return call_operation(operation, argv[2:])


def call_operation(operation: Operation, argv: list[str]) -> int:
    config = load_config()
    options = parse_call_options(operation, argv, config)
    request = prepare_request(operation, config, options)
    if options.dry_run:
        render_dry_run(request)
        return 0
    response = send_request(request, timeout=options.timeout)
    render_response(response, include=options.include, output=options.output)
    return 0 if response.status < 400 else 1


def parse_call_options(operation: Operation, argv: list[str], config: HarnessConfig) -> CallOptions:
    path_values: dict[str, str] = {}
    query_values: dict[str, list[str]] = {}
    header_values: dict[str, str] = {}
    param_values: dict[str, str] = {}
    body: str | None = None
    content_type: str | None = None
    include = False
    dry_run = False
    no_auth = False
    output = config.default_output
    timeout = 30.0
    host: str | None = None
    api_key: str | None = None

    parameter_names = {parameter.name for parameter in operation.parameters}
    parameter_flag_names = {
        _flag_name(parameter.name): parameter.name for parameter in operation.parameters
    }
    common_names = {
        "account": "account",
        "account-identifier": "accountIdentifier",
        "account-id": "accountID",
        "org": "org",
        "org-identifier": "orgIdentifier",
        "project": "project",
        "project-identifier": "projectIdentifier",
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--dry-run":
            dry_run = True
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
        elif token in {"--body", "--body-json"}:
            body, index = _consume_value(argv, index)
        elif token == "--body-file":
            value, index = _consume_value(argv, index)
            body = f"@{value}"
        elif token == "--content-type":
            content_type, index = _consume_value(argv, index)
        elif token == "--output":
            output, index = _consume_value(argv, index)
            if output not in {"json", "raw"}:
                raise ValueError("--output must be json or raw")
        elif token == "--timeout":
            value, index = _consume_value(argv, index)
            timeout = float(value)
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
                param_values[mapped] = value
        else:
            raise ValueError(f"Unexpected argument: {token}")

    return CallOptions(
        path_values=path_values,
        query_values=query_values,
        header_values=header_values,
        param_values=param_values,
        body=body,
        content_type=content_type,
        include=include,
        dry_run=dry_run,
        no_auth=no_auth,
        output=output,
        timeout=timeout,
        host=host,
        api_key=api_key,
    )


def resolve_operation(manifest: Manifest, value: str) -> Operation:
    matches = manifest.find_operation_matches(value)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        choices = ", ".join(f"{match.group}/{match.command}" for match in matches[:10])
        raise ValueError(f"Ambiguous operation {value}. Use one of: {choices}")
    suggestions = difflib.get_close_matches(value, sorted(manifest.by_operation_id), n=5)
    if not suggestions:
        suggestions = difflib.get_close_matches(value, sorted(manifest.by_command), n=5)
    hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    raise ValueError(f"Unknown operation: {value}.{hint}")


def print_group_help(manifest: Manifest, group: str) -> None:
    operations = manifest.group_operations(group)
    print(f"{manifest.groups[group]} ({group})")
    print()
    print(f"Usage: harness {group} OPERATION [flags]")
    print()
    rows = [[op.command, op.method.upper(), op.path, op.summary] for op in operations[:100]]
    print_table(["operation", "method", "path", "summary"], rows)
    if len(operations) > 100:
        print(
            f"... {len(operations) - 100} more. "
            f"Use `harness api list --tag {manifest.groups[group]!r}`."
        )


def print_operation_help(operation: Operation) -> None:
    print(f"{operation.operation_id}")
    print()
    print(f"Usage: harness {operation.group} {operation.command} [flags]")
    print(f"       harness api call {operation.operation_id} [flags]")
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
            print(f"  {flag} ({parameter.location}, {required})")
    if operation.request_body:
        required = "required" if operation.request_body.required else "optional"
        print()
        print(f"Body: {required}; content types: {', '.join(operation.request_body.content_types)}")
    print()
    print("Generic flags: --path, --query, --header, --param, --body, --dry-run, --include")


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
            ["name", "in", "required", "type", "description"],
            [
                [
                    parameter.name,
                    parameter.location,
                    "yes" if parameter.required else "no",
                    parameter.schema_type or "",
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
        }
        if operation.request_body
        else None,
    }


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


def _flag_name(name: str) -> str:
    text = name.replace("_", "-")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    return text.lower()


def _one_line(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _prompt(label: str, default: str, *, secret: bool = False) -> str:
    suffix = f" [{redact_secret(default) if secret and default else default}]" if default else ""
    prompt = f"{label}{suffix}: "
    if not sys.stdin.isatty():
        return default
    value = getpass.getpass(prompt) if secret else input(prompt)
    return value.strip() or default
