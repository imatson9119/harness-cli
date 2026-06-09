from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from typing import Any

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}


@dataclass(frozen=True)
class Parameter:
    name: str
    location: str
    required: bool
    description: str
    schema_type: str | None = None
    default: Any = None
    enum: tuple[Any, ...] = ()


@dataclass(frozen=True)
class RequestBody:
    required: bool
    content_types: tuple[str, ...]
    description: str = ""


@dataclass(frozen=True)
class Operation:
    operation_id: str
    command: str
    group: str
    tag: str
    method: str
    path: str
    summary: str
    description: str
    deprecated: bool
    parameters: tuple[Parameter, ...]
    request_body: RequestBody | None
    docs_url: str | None

    @property
    def display_name(self) -> str:
        return self.summary or self.operation_id


class Manifest:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.source = str(raw.get("source", ""))
        self.source_hash = str(raw.get("source_hash", ""))
        self.operation_count = int(raw.get("operation_count", 0))
        self.groups: dict[str, str] = dict(raw.get("groups", {}))
        self.operations = tuple(_operation_from_raw(item) for item in raw["operations"])
        self.by_operation_id = {operation.operation_id: operation for operation in self.operations}
        self.by_group_command: dict[tuple[str, str], Operation] = {}
        self.by_command: dict[str, list[Operation]] = {}
        for operation in self.operations:
            self.by_group_command[(operation.group, operation.command)] = operation
            self.by_command.setdefault(operation.command, []).append(operation)

    def group_operations(self, group: str) -> list[Operation]:
        return [operation for operation in self.operations if operation.group == group]

    def find_operation(self, value: str) -> Operation | None:
        if value in self.by_operation_id:
            return self.by_operation_id[value]
        if "/" in value:
            group, command = value.split("/", 1)
            return self.by_group_command.get((group, command))
        matches = self.by_command.get(value, [])
        if len(matches) == 1:
            return matches[0]
        return None

    def find_operation_matches(self, value: str) -> list[Operation]:
        matches: list[Operation] = []
        if value in self.by_operation_id:
            matches.append(self.by_operation_id[value])
        if "/" in value:
            group, command = value.split("/", 1)
            operation = self.by_group_command.get((group, command))
            if operation:
                matches.append(operation)
        matches.extend(self.by_command.get(value, []))
        seen: set[str] = set()
        unique: list[Operation] = []
        for operation in matches:
            if operation.operation_id not in seen:
                unique.append(operation)
                seen.add(operation.operation_id)
        return unique

    def search(
        self,
        *,
        text: str | None = None,
        tag: str | None = None,
        method: str | None = None,
    ) -> list[Operation]:
        needle = text.lower() if text else None
        method_filter = method.lower() if method else None
        tag_filter = tag.lower() if tag else None
        results: list[Operation] = []
        for operation in self.operations:
            if method_filter and operation.method != method_filter:
                continue
            if tag_filter and tag_filter not in operation.tag.lower():
                continue
            if needle:
                haystack = " ".join(
                    [
                        operation.operation_id,
                        operation.command,
                        operation.group,
                        operation.tag,
                        operation.method,
                        operation.path,
                        operation.summary,
                    ]
                ).lower()
                if needle not in haystack:
                    continue
            results.append(operation)
        return results


def load_manifest() -> Manifest:
    with (
        resources.files("harness_cli.data")
        .joinpath("operations.json")
        .open("r", encoding="utf-8") as handle
    ):
        return Manifest(json.load(handle))


def iter_parameter_names(operation: Operation, location: str | None = None) -> Iterable[str]:
    for parameter in operation.parameters:
        if location is None or parameter.location == location:
            yield parameter.name


def _operation_from_raw(item: dict[str, Any]) -> Operation:
    request_body = item.get("request_body")
    return Operation(
        operation_id=item["operation_id"],
        command=item["command"],
        group=item["group"],
        tag=item["tag"],
        method=item["method"],
        path=item["path"],
        summary=item.get("summary", ""),
        description=item.get("description", ""),
        deprecated=bool(item.get("deprecated", False)),
        parameters=tuple(_parameter_from_raw(param) for param in item.get("parameters", [])),
        request_body=_request_body_from_raw(request_body) if request_body else None,
        docs_url=item.get("docs_url"),
    )


def _parameter_from_raw(item: dict[str, Any]) -> Parameter:
    return Parameter(
        name=item["name"],
        location=item["in"],
        required=bool(item.get("required", False)),
        description=item.get("description", ""),
        schema_type=item.get("schema_type"),
        default=item.get("default"),
        enum=tuple(item.get("enum", [])),
    )


def _request_body_from_raw(item: dict[str, Any]) -> RequestBody:
    return RequestBody(
        required=bool(item.get("required", False)),
        content_types=tuple(item.get("content_types", [])),
        description=item.get("description", ""),
    )
