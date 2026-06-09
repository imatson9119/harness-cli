from __future__ import annotations

import json
import mimetypes
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import HarnessConfig, redact_secret
from .manifest import Operation, Parameter
from .render import format_http_status, print_data_table, print_json, print_notice, stylize

PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


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
    dry_run: bool = False
    no_auth: bool = False
    output: str = "json"
    output_file: str | None = None
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
        redacted = dict(self.headers)
        if "x-api-key" in redacted:
            redacted["x-api-key"] = redact_secret(redacted["x-api-key"])
        return redacted


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


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
        if not api_key and not options.dry_run:
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
                        'Content-Disposition: form-data; '
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
