from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
from collections.abc import Sequence
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
    text_rows = [[_clip(str(value), 80) for value in row] for row in rows]
    columns = list(zip(headers, *text_rows, strict=False))
    widths = [max(len(str(value)) for value in column) for column in columns]
    total = sum(widths) + (3 * (len(widths) - 1))
    if total > width and widths:
        overflow = total - width
        largest = max(range(len(widths)), key=lambda idx: widths[idx])
        widths[largest] = max(16, widths[largest] - overflow)
    print(stylize(_format_row(headers, widths), "bold"))
    print(stylize(_format_row(["-" * item for item in widths], widths), "dim"))
    for row in text_rows:
        print(_format_row(row, widths))


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


def unicode_enabled(stream: Any = sys.stderr) -> bool:
    if os.environ.get("HARNESS_ASCII"):
        return False
    encoding = (getattr(stream, "encoding", None) or "").lower()
    return "utf" in encoding


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
        self._enabled = animation_enabled(sys.stderr)

    def __enter__(self) -> CallStatus:
        self._start = time.monotonic()
        if self._enabled:
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        elapsed = time.monotonic() - self._start
        if self._enabled:
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
