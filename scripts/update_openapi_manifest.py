#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

SOURCE_URL = "https://apidocs.harness.io/page-data/shared/oas-index.yaml.json"
DOCS_BASE_URL = "https://apidocs.harness.io"
HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
RESERVED_GROUPS = {"init", "config", "auth", "doctor", "api", "profile", "completion", "version"}
ROOT = Path(__file__).resolve().parents[1]
OPERATIONS_PATH = ROOT / "src" / "harness_cli" / "data" / "operations.json"
COVERAGE_PATH = ROOT / "docs" / "endpoint-coverage.md"


def main() -> int:
    raw_bytes = fetch(SOURCE_URL)
    payload = json.loads(raw_bytes)
    definition = payload["definition"]
    operations = build_operations(definition)
    groups = build_groups(operations)
    manifest = {
        "schema_version": 1,
        "source": SOURCE_URL,
        "source_hash": hashlib.sha256(raw_bytes).hexdigest(),
        "api_title": definition.get("info", {}).get("title", ""),
        "api_version": definition.get("info", {}).get("version", ""),
        "operation_count": len(operations),
        "group_count": len(groups),
        "groups": groups,
        "operations": operations,
    }
    OPERATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPERATIONS_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    COVERAGE_PATH.write_text(render_coverage(manifest), encoding="utf-8")
    print(f"Wrote {OPERATIONS_PATH}")
    print(f"Wrote {COVERAGE_PATH}")
    print(f"Operations: {len(operations)}")
    print(f"Groups: {len(groups)}")
    return 0


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "harness-cli-generator/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def build_operations(definition: dict[str, Any]) -> list[dict[str, Any]]:
    paths = definition.get("paths", {})
    components = definition.get("components", {})
    generated: list[dict[str, Any]] = []
    command_counts: Counter[tuple[str, str]] = Counter()

    for path, path_item in sorted(paths.items()):
        if not isinstance(path_item, dict):
            continue
        path_parameters = path_item.get("parameters", [])
        for method, operation in sorted(path_item.items()):
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId") or f"{method}-{path}"
            tag = first_tag(operation, path)
            docs_group = slugify(tag)
            group = safe_group_slug(docs_group)
            command = slugify(operation_id)
            key = (group, command)
            command_counts[key] += 1
            if command_counts[key] > 1:
                command = f"{command}-{method}-{short_hash(path)}"

            parameters = [
                serialize_parameter(resolve_ref(parameter, components))
                for parameter in [*path_parameters, *operation.get("parameters", [])]
            ]
            parameters = [parameter for parameter in parameters if parameter]
            generated.append(
                {
                    "operation_id": str(operation_id),
                    "command": command,
                    "group": group,
                    "tag": tag,
                    "method": method,
                    "path": path,
                    "summary": clean_text(operation.get("summary", "")),
                    "description": clean_text(operation.get("description", "")),
                    "deprecated": bool(operation.get("deprecated", False)),
                    "parameters": parameters,
                    "request_body": serialize_request_body(
                        resolve_ref(operation.get("requestBody"), components)
                    ),
                    "docs_url": docs_url(docs_group, command),
                }
            )

    generated.sort(key=lambda item: (item["group"], item["command"], item["method"], item["path"]))
    return generated


def build_groups(operations: list[dict[str, Any]]) -> dict[str, str]:
    groups: dict[str, str] = {}
    for operation in operations:
        groups.setdefault(operation["group"], operation["tag"])
    return dict(sorted(groups.items(), key=lambda item: item[0]))


def first_tag(operation: dict[str, Any], path: str) -> str:
    tags = operation.get("tags") or []
    if tags:
        return str(tags[0])
    parts = [part for part in path.split("/") if part and not part.startswith("{")]
    if parts and parts[0] == "v1" and len(parts) > 1:
        return parts[1]
    return parts[0] if parts else "api"


def resolve_ref(value: Any, components: dict[str, Any]) -> Any:
    if not isinstance(value, dict) or "$ref" not in value:
        return value
    ref = value["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#/components/"):
        return value
    current: Any = {"components": components}
    for part in ref.lstrip("#/").split("/"):
        current = current.get(part)
        if current is None:
            return value
    if isinstance(current, dict):
        merged = {key: item for key, item in value.items() if key != "$ref"}
        return {**current, **merged}
    return current


def serialize_parameter(parameter: Any) -> dict[str, Any] | None:
    if not isinstance(parameter, dict) or "name" not in parameter:
        return None
    schema = parameter.get("schema", {})
    return {
        "name": str(parameter.get("name")),
        "in": str(parameter.get("in", "query")),
        "required": bool(parameter.get("required", False)),
        "description": clean_text(parameter.get("description", "")),
        "schema_type": schema_type(schema),
        "default": schema.get("default") if isinstance(schema, dict) else None,
        "enum": schema.get("enum", []) if isinstance(schema, dict) else [],
    }


def serialize_request_body(request_body: Any) -> dict[str, Any] | None:
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content") or {}
    return {
        "required": bool(request_body.get("required", False)),
        "description": clean_text(request_body.get("description", "")),
        "content_types": sorted(content.keys()) if isinstance(content, dict) else [],
    }


def schema_type(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    if "$ref" in schema:
        return str(schema["$ref"]).split("/")[-1]
    if "type" in schema:
        if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
            return f"array[{schema_type(schema['items']) or 'unknown'}]"
        return str(schema["type"])
    if "oneOf" in schema:
        return "oneOf"
    if "anyOf" in schema:
        return "anyOf"
    if "allOf" in schema:
        return "allOf"
    return None


def docs_url(group: str, command: str) -> str:
    return f"{DOCS_BASE_URL}/{group}/{command}"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def slugify(value: Any) -> str:
    text = str(value).strip()
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "operation"


def safe_group_slug(group: str) -> str:
    if group in RESERVED_GROUPS:
        return f"{group}-api"
    return group


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def render_coverage(manifest: dict[str, Any]) -> str:
    operations = manifest["operations"]
    groups = manifest["groups"]
    counts = Counter(operation["group"] for operation in operations)
    lines = [
        "# Endpoint Coverage",
        "",
        f"Source: <{manifest['source']}>",
        "",
        f"Operations: {manifest['operation_count']}",
        f"Groups: {manifest['group_count']}",
        f"Source hash: `{manifest['source_hash']}`",
        "",
        "Every operation in the generated manifest is callable through:",
        "",
        "- `harness api call <operation-id>`",
        "- `harness <group> <operation>`",
        "",
        "## Groups",
        "",
        "| Group | Tag | Operations |",
        "| --- | --- | ---: |",
    ]
    for group, tag in sorted(groups.items()):
        lines.append(f"| `{group}` | {tag} | {counts[group]} |")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
