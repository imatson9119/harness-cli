#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_cli.search import validate_search_index_data  # noqa: E402

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
RESERVED_GROUPS = {"init", "config", "auth", "doctor", "api", "profile", "completion", "version"}
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = ROOT / "src" / "harness_cli" / "data" / "operations.json"
DEFAULT_SEARCH_INDEX_PATH = ROOT / "src" / "harness_cli" / "data" / "search_index.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the generated Harness API manifest.")
    parser.add_argument("--path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--search-index-path", type=Path, default=DEFAULT_SEARCH_INDEX_PATH)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()

    manifest = json.loads(args.path.read_text(encoding="utf-8"))
    errors = validate_manifest(manifest)
    if args.search_index_path.exists():
        search_index = json.loads(args.search_index_path.read_text(encoding="utf-8"))
        if not isinstance(search_index, dict):
            errors.append("search index must be an object")
        else:
            errors.extend(validate_search_index_data(manifest, search_index))
    else:
        errors.append(f"search index does not exist at {args.search_index_path}")
    result = {
        "ok": not errors,
        "path": str(args.path),
        "search_index_path": str(args.search_index_path),
        "operation_count": manifest.get("operation_count"),
        "group_count": manifest.get("group_count"),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif errors:
        print(f"Manifest invalid: {args.path}", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print(
            f"Manifest OK: {manifest.get('operation_count')} operations, "
            f"{manifest.get('group_count')} groups"
        )
    return 0 if not errors else 1


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    operations = manifest.get("operations")
    groups = manifest.get("groups")
    if not isinstance(operations, list):
        return ["operations must be a list"]
    if not isinstance(groups, dict):
        return ["groups must be an object"]
    if manifest.get("schema_version") != 2:
        errors.append("schema_version must be 2")

    if manifest.get("operation_count") != len(operations):
        errors.append("operation_count does not match operations length")
    if manifest.get("group_count") != len(groups):
        errors.append("group_count does not match groups length")

    reserved = sorted(set(groups) & RESERVED_GROUPS)
    if reserved:
        errors.append(f"generated groups collide with built-in commands: {', '.join(reserved)}")

    operation_ids = Counter(_string_field(operation, "operation_id") for operation in operations)
    group_commands = Counter(
        (_string_field(operation, "group"), _string_field(operation, "command"))
        for operation in operations
    )
    duplicate_ids = sorted(item for item, count in operation_ids.items() if item and count > 1)
    duplicate_pairs = sorted(
        item for item, count in group_commands.items() if item[0] and count > 1
    )
    if duplicate_ids:
        errors.append(f"duplicate operation ids: {', '.join(duplicate_ids[:10])}")
    if duplicate_pairs:
        formatted = ", ".join(f"{group}/{command}" for group, command in duplicate_pairs[:10])
        errors.append(f"duplicate group/command pairs: {formatted}")

    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            errors.append(f"operation {index} must be an object")
            continue
        errors.extend(_validate_operation(operation, index, groups))
    return errors


def _validate_operation(operation: dict[str, Any], index: int, groups: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    label = operation.get("operation_id") or f"operation[{index}]"
    for field in ("operation_id", "command", "group", "tag", "method", "path"):
        if not _string_field(operation, field):
            errors.append(f"{label}: missing {field}")
    group = _string_field(operation, "group")
    if group and group not in groups:
        errors.append(f"{label}: group {group} is not declared")
    method = _string_field(operation, "method")
    if method and method not in HTTP_METHODS:
        errors.append(f"{label}: unsupported HTTP method {method}")
    path = _string_field(operation, "path")
    if path and not path.startswith("/"):
        errors.append(f"{label}: path must start with /")
    docs_url = _string_field(operation, "docs_url")
    if not docs_url.startswith("https://apidocs.harness.io/"):
        errors.append(f"{label}: docs_url must point to apidocs.harness.io")
    parameters = operation.get("parameters")
    if not isinstance(parameters, list):
        errors.append(f"{label}: parameters must be a list")
    request_body = operation.get("request_body")
    if request_body is not None and not isinstance(request_body, dict):
        errors.append(f"{label}: request_body must be an object or null")
    elif isinstance(request_body, dict):
        content_types = request_body.get("content_types")
        samples = request_body.get("samples")
        if not isinstance(content_types, list):
            errors.append(f"{label}: request_body.content_types must be a list")
        if samples is not None and not isinstance(samples, dict):
            errors.append(f"{label}: request_body.samples must be an object")
        if isinstance(content_types, list) and isinstance(samples, dict):
            unexpected = sorted(set(samples) - {str(item) for item in content_types})
            if unexpected:
                errors.append(
                    f"{label}: request_body.samples contains unknown content types: "
                    + ", ".join(unexpected[:10])
                )
    return errors


def _string_field(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    return value if isinstance(value, str) else ""


if __name__ == "__main__":
    raise SystemExit(main())
