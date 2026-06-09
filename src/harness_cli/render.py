from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Sequence
from typing import Any


def print_json(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def print_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    if not rows:
        print("No results.")
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
    print(_format_row(headers, widths))
    print(_format_row(["-" * item for item in widths], widths))
    for row in text_rows:
        print(_format_row(row, widths))


def print_error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


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
