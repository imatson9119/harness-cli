from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

RESET = "\033[0m"
STYLES = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
}
JSON_TOKEN_RE = re.compile(
    r'(?P<key>"(?:\\.|[^"\\])*")(?=\s*:)|'
    r'(?P<string>"(?:\\.|[^"\\])*")|'
    r"(?P<bool>\btrue\b|\bfalse\b)|"
    r"(?P<null>\bnull\b)|"
    r"(?P<number>-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)"
)
PREFERRED_TABLE_COLUMNS = (
    "identifier",
    "id",
    "name",
    "status",
    "state",
    "type",
    "createdAt",
    "updatedAt",
)


@dataclass(frozen=True)
class TableFrame:
    row_left: str
    row_separator: str
    row_right: str
    top_left: str
    top_separator: str
    top_right: str
    divider_left: str
    divider_separator: str
    divider_right: str
    bottom_left: str
    bottom_separator: str
    bottom_right: str
    horizontal: str


ASCII_TABLE_FRAME = TableFrame(
    row_left="|",
    row_separator="|",
    row_right="|",
    top_left="+",
    top_separator="+",
    top_right="+",
    divider_left="+",
    divider_separator="+",
    divider_right="+",
    bottom_left="+",
    bottom_separator="+",
    bottom_right="+",
    horizontal="-",
)
UNICODE_TABLE_FRAME = TableFrame(
    row_left="│",
    row_separator="│",
    row_right="│",
    top_left="╭",
    top_separator="┬",
    top_right="╮",
    divider_left="├",
    divider_separator="┼",
    divider_right="┤",
    bottom_left="╰",
    bottom_separator="┴",
    bottom_right="╯",
    horizontal="─",
)


def print_json(data: Any) -> None:
    payload = json.dumps(data, indent=2, sort_keys=True)
    if color_enabled(sys.stdout):
        payload = colorize_json(payload)
    print(payload)


def print_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    if not rows:
        print(stylize("No results.", "dim"))
        return
    width = shutil.get_terminal_size((120, 24)).columns
    style = table_style(sys.stdout)
    text_rows = [[_clip(str(value), 80) for value in row] for row in rows]
    columns = list(zip(headers, *text_rows, strict=False))
    widths = [max(len(str(value)) for value in column) for column in columns]
    widths = _fit_table_widths(widths, width, _table_extra_width(style, len(widths)))
    if style != "plain":
        frame = UNICODE_TABLE_FRAME if style == "unicode" else ASCII_TABLE_FRAME
        print(
            stylize(
                _format_border(widths, frame.top_left, frame.top_separator, frame.top_right, frame),
                "dim",
            )
        )
        print(stylize(_format_framed_row(headers, widths, frame), "bold"))
        print(
            stylize(
                _format_border(
                    widths, frame.divider_left, frame.divider_separator, frame.divider_right, frame
                ),
                "dim",
            )
        )
        for row in text_rows:
            print(_format_framed_row(row, widths, frame))
        print(
            stylize(
                _format_border(
                    widths, frame.bottom_left, frame.bottom_separator, frame.bottom_right, frame
                ),
                "dim",
            )
        )
        return
    print(stylize(_format_row(headers, widths), "bold"))
    print(stylize(_format_row(["-" * item for item in widths], widths), "dim"))
    for row in text_rows:
        print(_format_row(row, widths))


def print_data_table(data: Any, *, columns: Sequence[str] | None = None) -> None:
    records = _records_from_data(data)
    if isinstance(records, dict):
        if columns:
            selected = list(columns)
            print_table(
                selected,
                [[_cell_value(_record_value(records, column)) for column in selected]],
            )
            return
        print_table(["key", "value"], [[key, _cell_value(value)] for key, value in records.items()])
        return
    if not records:
        print("No results.")
        return
    if all(isinstance(item, dict) for item in records):
        dict_records = [item for item in records if isinstance(item, dict)]
        selected_columns = list(columns) if columns else _table_columns(dict_records)
        print_table(
            selected_columns,
            [
                [_cell_value(_record_value(record, column)) for column in selected_columns]
                for record in dict_records
            ],
        )
        return
    print_table(["value"], [[_cell_value(value)] for value in records])


def print_error(message: str) -> None:
    print(stylize(f"error: {message}", "red", stream=sys.stderr), file=sys.stderr)


def print_notice(message: str) -> None:
    print(stylize(message, "dim", stream=sys.stderr), file=sys.stderr)


def stylize(text: str, style: str, *, stream: Any = None) -> str:
    target = stream if stream is not None else sys.stdout
    code = STYLES.get(style)
    if not code or not color_enabled(target):
        return text
    return f"{code}{text}{RESET}"


def color_enabled(stream: Any) -> bool:
    color = os.environ.get("HARNESS_COLOR", "auto").lower()
    if color in {"never", "0", "false", "no"} or "NO_COLOR" in os.environ:
        return False
    if color in {"always", "1", "true", "yes"} or os.environ.get("CLICOLOR_FORCE"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)()) and os.environ.get("TERM") != "dumb"


def animation_enabled(stream: Any = sys.stderr) -> bool:
    value = os.environ.get("HARNESS_ANIMATION", "auto").lower()
    if value in {"never", "0", "false", "no"}:
        return False
    if value in {"always", "1", "true", "yes"}:
        return True
    return bool(getattr(stream, "isatty", lambda: False)()) and os.environ.get("TERM") != "dumb"


def status_enabled(stream: Any = sys.stderr) -> bool:
    value = os.environ.get("HARNESS_STATUS", "auto").lower()
    if value in {"never", "0", "false", "no"}:
        return False
    if value in {"always", "1", "true", "yes"}:
        return True
    return bool(getattr(stream, "isatty", lambda: False)()) and os.environ.get("TERM") != "dumb"


def unicode_enabled(stream: Any = sys.stderr) -> bool:
    if os.environ.get("HARNESS_ASCII"):
        return False
    encoding = (getattr(stream, "encoding", None) or "").lower()
    return "utf" in encoding


def table_style(stream: Any = sys.stdout) -> str:
    value = os.environ.get("HARNESS_TABLE_STYLE", "auto").lower()
    if value in {"plain", "pipe", "pipes", "0", "false", "no"}:
        return "plain"
    if value in {"ascii", "box", "boxed"}:
        return "ascii"
    if value in {"unicode", "rounded", "rich"}:
        return "ascii" if os.environ.get("HARNESS_ASCII") else "unicode"
    if value not in {"", "auto"}:
        return "plain"
    if not bool(getattr(stream, "isatty", lambda: False)()) or os.environ.get("TERM") == "dumb":
        return "plain"
    if unicode_enabled(stream):
        return "unicode"
    return "ascii"


def glyph(name: str, *, stream: Any = sys.stderr) -> str:
    if not unicode_enabled(stream):
        return {"ok": "+", "fail": "x", "wait": "*"}.get(name, "*")
    return {"ok": "\u2713", "fail": "\u2717", "wait": "\u25d2"}.get(name, "\u25d2")


def colorize_json(payload: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group("key") is not None:
            return stylize(match.group("key"), "cyan")
        if match.group("string") is not None:
            return stylize(match.group("string"), "green")
        if match.group("number") is not None:
            return stylize(match.group("number"), "magenta")
        if match.group("bool") is not None:
            return stylize(match.group("bool"), "yellow")
        if match.group("null") is not None:
            return stylize(match.group("null"), "dim")
        return match.group(0)

    return JSON_TOKEN_RE.sub(replace, payload)


def format_http_status(status: int, *, stream: Any = sys.stdout) -> str:
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = ""
    text = f"HTTP {status}" + (f" {phrase}" if phrase else "")
    if 200 <= status < 400:
        return stylize(text, "green", stream=stream)
    if status >= 400:
        return stylize(text, "red", stream=stream)
    return stylize(text, "yellow", stream=stream)


class CallStatus:
    def __init__(self, method: str, url: str):
        self.method = method
        self.label = _request_label(method, url)
        self.status: int | None = None
        self._start = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status_enabled = status_enabled(sys.stderr)
        self._animated = self._status_enabled and animation_enabled(sys.stderr)

    def __enter__(self) -> CallStatus:
        self._start = time.monotonic()
        if self._animated:
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if not self._status_enabled:
            return
        elapsed = time.monotonic() - self._start
        if self._animated:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=0.3)
            sys.stderr.write("\r\033[K")
        if exc is not None:
            print(
                f"{stylize(glyph('fail'), 'red', stream=sys.stderr)} "
                f"{self.label} failed after {elapsed:.1f}s",
                file=sys.stderr,
            )
            return
        status = self.status or 0
        ok = 200 <= status < 400
        symbol = glyph("ok" if ok else "fail")
        style = "green" if ok else "red"
        print(
            f"{stylize(symbol, style, stream=sys.stderr)} "
            f"{self.label} -> {format_http_status(status, stream=sys.stderr)} "
            f"in {elapsed:.1f}s",
            file=sys.stderr,
        )

    def done(self, status: int) -> None:
        self.status = status

    def _animate(self) -> None:
        frames = ["-", "\\", "|", "/"]
        if unicode_enabled(sys.stderr):
            frames = ["\u25d0", "\u25d3", "\u25d1", "\u25d2"]
        index = 0
        while not self._stop.is_set():
            elapsed = time.monotonic() - self._start
            frame = stylize(frames[index % len(frames)], "cyan", stream=sys.stderr)
            sys.stderr.write(f"\r\033[K{frame} {self.label} ... {elapsed:.1f}s")
            sys.stderr.flush()
            index += 1
            self._stop.wait(0.12)


def _format_row(row: Sequence[Any], widths: Sequence[int]) -> str:
    cells = []
    for value, width in zip(row, widths, strict=False):
        cells.append(_clip(str(value), width).ljust(width))
    return " | ".join(cells).rstrip()


def _format_framed_row(row: Sequence[Any], widths: Sequence[int], frame: TableFrame) -> str:
    cells = []
    for value, width in zip(row, widths, strict=False):
        cells.append(f" {_clip(str(value), width).ljust(width)} ")
    return f"{frame.row_left}{frame.row_separator.join(cells)}{frame.row_right}"


def _format_border(
    widths: Sequence[int],
    left: str,
    separator: str,
    right: str,
    frame: TableFrame,
) -> str:
    cells = [frame.horizontal * (width + 2) for width in widths]
    return f"{left}{separator.join(cells)}{right}"


def _table_extra_width(style: str, column_count: int) -> int:
    if column_count <= 0:
        return 0
    if style == "plain":
        return 3 * (column_count - 1)
    return (3 * column_count) + 1


def _fit_table_widths(widths: Sequence[int], terminal_width: int, extra_width: int) -> list[int]:
    fitted = list(widths)
    while fitted and sum(fitted) + extra_width > terminal_width:
        candidates = [index for index, width in enumerate(fitted) if width > 16]
        if not candidates:
            break
        largest = max(candidates, key=lambda index: fitted[index])
        overflow = sum(fitted) + extra_width - terminal_width
        fitted[largest] = max(16, fitted[largest] - overflow)
    return fitted


def _clip(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def _request_label(method: str, url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    return f"{method.upper()} {path}"


def _records_from_data(data: Any) -> list[Any] | dict[str, Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "items", "content", "results", "resources", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        for value in data.values():
            if isinstance(value, list):
                return value
        return data
    return [data]


def _table_columns(records: Sequence[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key, value in record.items():
            if key in seen:
                continue
            if isinstance(value, dict | list):
                continue
            ordered.append(key)
            seen.add(key)
    if not ordered:
        for record in records:
            for key in record:
                if key not in seen:
                    ordered.append(key)
                    seen.add(key)
    preferred = [key for key in PREFERRED_TABLE_COLUMNS if key in seen]
    rest = [key for key in ordered if key not in preferred]
    return [*preferred, *rest][:8] or ["value"]


def _record_value(record: dict[str, Any], column: str) -> Any:
    if column in record:
        return record[column]
    current: Any = record
    for part in column.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _cell_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
