from __future__ import annotations

import json
import mimetypes
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .config import HarnessConfig, redact_secret
from .manifest import Operation, Parameter
from .render import format_http_status, print_data_table, print_json, print_notice, stylize

PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")
SENSITIVE_HEADER_NAMES = {
    "authorization",
    "api-key",
    "apikey",
    "x-api-key",
    "xapikey",
}
SENSITIVE_HEADER_FRAGMENTS = ("credential", "password", "secret", "token")


class RequestError(RuntimeError):
    """Raised when a request cannot reach Harness at the transport layer."""


@dataclass(frozen=True)
class CallOptions:
    path_values: dict[str, str]
    query_values: dict[str, list[str]]
    header_values: dict[str, str]
    param_values: dict[str, str]
    body: str | None
    content_type: str | None
    form_values: dict[str, list[str]] = field(default_factory=dict)
    file_values: dict[str, list[str]] = field(default_factory=dict)
    include: bool = False
    curl: bool = False
    dry_run: bool = False
    no_auth: bool = False
    output: str = "json"
    output_file: str | None = None
    all_pages: bool = False
    all_page_size: int | None = None
    max_pages: int = 100
    timeout: float = 30.0
    host: str | None = None
    api_key: str | None = None


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None

    def redacted_headers(self) -> dict[str, str]:
        return {
            name: redact_secret(value) if _is_sensitive_header(name) else value
            for name, value in self.headers.items()
        }


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class PaginationPlan:
    kind: str
    page_param: str | None
    size_param: str | None
    cursor_param: str | None
    start: int


def prepare_request(
    operation: Operation,
    config: HarnessConfig,
    options: CallOptions,
) -> PreparedRequest:
    host = (options.host or config.host).rstrip("/")
    values = _merge_parameter_values(operation, config, options)
    path = _format_path(operation, values)
    query = _query_values(operation, values, options)
    url = f"{host}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"

    headers = _header_values(operation, values, options)
    if not options.no_auth:
        api_key = options.api_key or config.api_key
        if not api_key and not options.dry_run and not options.curl:
            raise ValueError("Missing Harness API key. Run `harness init` or set HARNESS_API_KEY.")
        if api_key:
            headers["x-api-key"] = api_key

    body, body_headers = _body_bytes_and_headers(operation, options)
    headers.update({key: value for key, value in body_headers.items() if key not in headers})
    return PreparedRequest(operation.method.upper(), url, headers, body)


def send_request(request: PreparedRequest, *, timeout: float) -> Response:
    urllib_request = urllib.request.Request(
        request.url,
        data=request.body,
        headers=request.headers,
        method=request.method,
    )
    try:
        with urllib.request.urlopen(urllib_request, timeout=timeout) as response:
            return Response(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return Response(
            status=exc.code,
            headers=dict(exc.headers.items()),
            body=exc.read(),
        )
    except urllib.error.URLError as exc:
        raise RequestError(_transport_error_message(request, exc)) from exc
    except TimeoutError as exc:
        raise RequestError(_transport_error_message(request, exc)) from exc
    except OSError as exc:
        raise RequestError(_transport_error_message(request, exc)) from exc


def send_paginated_request(
    operation: Operation,
    config: HarnessConfig,
    options: CallOptions,
    *,
    timeout: float,
) -> Response:
    plan = pagination_plan(operation)
    if not plan:
        raise ValueError(
            "--all requires query pagination parameters like page/limit, "
            "page/size, pageIndex/pageSize, offset/limit, or pageToken."
        )
    collected: list[Any] = []
    last_response: Response | None = None
    cursor: str | None = None
    page_or_offset = plan.start

    for page_count in range(options.max_pages):
        page_options = replace(
            options,
            query_values=_paginated_query_values(options, plan, page_or_offset, cursor),
        )
        request = prepare_request(operation, config, page_options)
        response = send_request(request, timeout=timeout)
        last_response = response
        if response.status >= 400:
            return response
        data = _json_body(response)
        if data is None:
            return response
        items = _items_from_json(data)
        collected.extend(items)

        if plan.kind == "cursor":
            cursor = _next_token(data)
            if not cursor:
                break
        else:
            limit = _effective_page_size(options, plan)
            total_pages = _total_pages(data)
            if not items:
                break
            if total_pages is not None and page_count + 1 >= total_pages:
                break
            if limit is not None and len(items) < limit:
                break
            page_or_offset = page_or_offset + (len(items) if plan.kind == "offset" else 1)
    if last_response is None:
        return Response(status=200, headers={}, body=b"[]")
    return Response(
        status=last_response.status,
        headers=last_response.headers,
        body=json.dumps(collected, indent=2, sort_keys=True).encode("utf-8"),
    )


def render_response(
    response: Response,
    *,
    include: bool,
    output: str,
    output_file: str | None = None,
) -> None:
    if include:
        print(format_http_status(response.status))
        for key, value in sorted(response.headers.items()):
            print(f"{stylize(key, 'cyan')}: {value}")
        print()
    if output_file:
        _write_output_file(output_file, response.body)
        return
    if not response.body:
        return
    if output == "raw":
        sys.stdout.buffer.write(response.body)
        if not response.body.endswith(b"\n"):
            sys.stdout.write("\n")
        return
    try:
        parsed = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        sys.stdout.buffer.write(response.body)
        if not response.body.endswith(b"\n"):
            sys.stdout.write("\n")
        return
    if output == "table":
        print_data_table(parsed)
        return
    print_json(parsed)


def render_dry_run(request: PreparedRequest) -> None:
    print(f"{stylize(request.method, 'blue')} {request.url}")
    for key, value in sorted(request.redacted_headers().items()):
        print(f"{stylize(key, 'cyan')}: {value}")
    if request.body:
        print()
        try:
            body = request.body.decode("utf-8")
        except UnicodeDecodeError:
            body = f"<{len(request.body)} bytes>"
        print(body)


def render_curl(request: PreparedRequest) -> None:
    lines = [f"curl -X {shlex.quote(request.method)}", f"  {shlex.quote(request.url)}"]
    for key, value in sorted(request.redacted_headers().items()):
        lines.append(f"  -H {shlex.quote(f'{key}: {value}')}")
    if request.body:
        try:
            body = request.body.decode("utf-8")
        except UnicodeDecodeError:
            body = f"<{len(request.body)} binary bytes>"
        lines.append(f"  --data-raw {shlex.quote(body)}")
    print(" \\\n".join(lines))


def _merge_parameter_values(
    operation: Operation,
    config: HarnessConfig,
    options: CallOptions,
) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in {
        "account": config.account,
        "accountIdentifier": config.account,
        "accountID": config.account,
        "org": config.org,
        "orgIdentifier": config.org,
        "project": config.project,
        "projectIdentifier": config.project,
    }.items():
        if value:
            values[key] = value
    values.update(options.param_values)
    values.update(options.path_values)
    if "account" in values and "Harness-Account" not in values:
        values["Harness-Account"] = values["account"]
    return values


def _format_path(operation: Operation, values: dict[str, str]) -> str:
    missing = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.append(key)
            return match.group(0)
        return urllib.parse.quote(str(values[key]), safe="")

    path = PATH_PARAM_RE.sub(replace, operation.path)
    if missing:
        raise ValueError(f"Missing path parameter(s): {', '.join(sorted(missing))}")
    return path


def _query_values(
    operation: Operation,
    values: dict[str, str],
    options: CallOptions,
) -> dict[str, list[str]]:
    query: dict[str, list[str]] = {key: list(value) for key, value in options.query_values.items()}
    for parameter in _parameters_in(operation, "query"):
        if parameter.name in values:
            query.setdefault(parameter.name, []).append(str(values[parameter.name]))
    return query


def _header_values(
    operation: Operation,
    values: dict[str, str],
    options: CallOptions,
) -> dict[str, str]:
    headers = dict(options.header_values)
    for parameter in _parameters_in(operation, "header"):
        if parameter.name in values:
            headers[parameter.name] = str(values[parameter.name])
    return headers


def _parameters_in(operation: Operation, location: str) -> list[Parameter]:
    return [parameter for parameter in operation.parameters if parameter.location == location]


def _is_sensitive_header(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    compact = re.sub(r"[^a-z0-9]+", "", name.lower())
    if normalized in SENSITIVE_HEADER_NAMES or compact in SENSITIVE_HEADER_NAMES:
        return True
    return any(fragment in compact for fragment in SENSITIVE_HEADER_FRAGMENTS)


def pagination_plan(operation: Operation) -> PaginationPlan | None:
    query_params = {parameter.name: parameter for parameter in _parameters_in(operation, "query")}
    if "pageToken" in query_params:
        return PaginationPlan(
            "cursor",
            None,
            _first_present(query_params, ["pageSize", "limit", "size"]),
            "pageToken",
            0,
        )
    if "cursor" in query_params:
        return PaginationPlan(
            "cursor",
            None,
            _first_present(query_params, ["limit", "pageSize", "size"]),
            "cursor",
            0,
        )
    for page_param, size_param in [
        ("page", "limit"),
        ("page", "size"),
        ("page", "pageSize"),
        ("pageIndex", "pageSize"),
        ("pageNumber", "pageSize"),
    ]:
        if page_param in query_params and size_param in query_params:
            return PaginationPlan(
                "page",
                page_param,
                size_param,
                None,
                _int_value(query_params[page_param].default, 0),
            )
    offset_size_param = _first_present(query_params, ["limit", "pageSize", "size"])
    if "offset" in query_params and offset_size_param:
        return PaginationPlan(
            "offset",
            "offset",
            offset_size_param,
            None,
            _int_value(query_params["offset"].default, 0),
        )
    return None


def pagination_help(operation: Operation) -> str | None:
    plan = pagination_plan(operation)
    if not plan:
        return None
    if plan.kind == "cursor":
        cursor = plan.cursor_param or "cursor"
        size = f" and --all-page-size for {plan.size_param}" if plan.size_param else ""
        return f"Supports --all using {cursor} cursor pagination{size}."
    if plan.kind == "offset":
        return f"Supports --all using {plan.page_param}/{plan.size_param} pagination."
    return f"Supports --all using {plan.page_param}/{plan.size_param} pagination."


def _paginated_query_values(
    options: CallOptions,
    plan: PaginationPlan,
    page_or_offset: int,
    cursor: str | None,
) -> dict[str, list[str]]:
    query = {key: list(values) for key, values in options.query_values.items()}
    if plan.size_param and options.all_page_size is not None:
        query[plan.size_param] = [str(options.all_page_size)]
    if plan.kind == "cursor":
        if plan.cursor_param and cursor:
            query[plan.cursor_param] = [cursor]
    elif plan.page_param:
        query[plan.page_param] = [str(page_or_offset)]
    return query


def _effective_page_size(options: CallOptions, plan: PaginationPlan) -> int | None:
    if options.all_page_size is not None:
        return options.all_page_size
    if plan.size_param:
        values = options.query_values.get(plan.size_param)
        if values:
            return _optional_int(values[-1])
        value = options.param_values.get(plan.size_param)
        if value is not None:
            return _optional_int(value)
    return None


def _json_body(response: Response) -> Any | None:
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _items_from_json(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "items", "content", "results", "resources", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = _items_from_json(value)
                if nested:
                    return nested
    return [data] if data not in (None, {}) else []


def _next_token(data: Any) -> str | None:
    keys = (
        "nextPageToken",
        "next_page_token",
        "nextToken",
        "next_token",
        "nextCursor",
        "next_cursor",
    )
    value = _find_first(data, keys)
    return str(value) if value not in (None, "") else None


def _total_pages(data: Any) -> int | None:
    value = _find_first(data, ("totalPages", "total_pages", "pageCount", "page_count"))
    return _optional_int(value)


def _find_first(data: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data:
            return data[key]
    for nested_key in ("pagination", "pageInfo", "page_info", "meta", "metadata", "data"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            value = _find_first(nested, keys)
            if value is not None:
                return value
    return None


def _first_present(values: dict[str, Parameter], keys: list[str]) -> str | None:
    for key in keys:
        if key in values:
            return key
    return None


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _content_type(operation: Operation, options: CallOptions) -> str:
    if options.content_type:
        return options.content_type
    if operation.request_body and operation.request_body.content_types:
        preferred = [
            "application/json",
            "application/yaml",
            "application/x-yaml",
            "multipart/form-data",
        ]
        for content_type in preferred:
            if content_type in operation.request_body.content_types:
                return content_type
        return operation.request_body.content_types[0]
    return "application/json"


def _body_bytes_and_headers(
    operation: Operation,
    options: CallOptions,
) -> tuple[bytes | None, dict[str, str]]:
    has_form = bool(options.form_values or options.file_values)
    if options.body is not None and has_form:
        raise ValueError("Use either --body/--body-file or --form/--file, not both.")
    if has_form:
        return _form_body_and_headers(operation, options)
    body = _body_bytes(options.body)
    if body is None:
        return None, {}
    return body, {"Content-Type": _content_type(operation, options)}


def _form_body_and_headers(
    operation: Operation,
    options: CallOptions,
) -> tuple[bytes, dict[str, str]]:
    content_type = options.content_type or _content_type(operation, options)
    if options.file_values or content_type == "multipart/form-data":
        body, boundary = _multipart_body(options.form_values, options.file_values)
        return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if content_type == "application/x-www-form-urlencoded":
        body = urllib.parse.urlencode(options.form_values, doseq=True).encode("utf-8")
        return body, {"Content-Type": content_type}
    body, boundary = _multipart_body(options.form_values, options.file_values)
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def _body_bytes(body: str | None) -> bytes | None:
    if body is None:
        return None
    if body == "-":
        return sys.stdin.buffer.read()
    if body.startswith("@"):
        return Path(body[1:]).read_bytes()
    return body.encode("utf-8")


def _multipart_body(
    form_values: dict[str, list[str]],
    file_values: dict[str, list[str]],
) -> tuple[bytes, str]:
    boundary = f"harness-cli-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, values in form_values.items():
        for value in values:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{_quote_header(name)}"\r\n'.encode(),
                    b"\r\n",
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )
    for name, paths in file_values.items():
        for value in paths:
            file_path = Path(value[1:] if value.startswith("@") else value)
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    (
                        "Content-Disposition: form-data; "
                        f'name="{_quote_header(name)}"; '
                        f'filename="{_quote_header(file_path.name)}"\r\n'
                    ).encode(),
                    f"Content-Type: {content_type}\r\n".encode(),
                    b"\r\n",
                    file_path.read_bytes(),
                    b"\r\n",
                ]
            )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def _write_output_file(output_file: str, body: bytes) -> None:
    if output_file == "-":
        sys.stdout.buffer.write(body)
        if body and not body.endswith(b"\n"):
            sys.stdout.write("\n")
        return
    path = Path(output_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    print_notice(f"Wrote {path} ({len(body)} bytes)")


def _quote_header(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


def _transport_error_message(request: PreparedRequest, error: BaseException) -> str:
    reason = getattr(error, "reason", None) or error
    message = str(reason) or error.__class__.__name__
    return f"{_request_label(request.method, request.url)} failed: {message}"


def _request_label(method: str, url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path or "/"
    return f"{method.upper()} {path}"
