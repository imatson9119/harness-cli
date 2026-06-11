#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness_cli.search import build_search_index_data  # noqa: E402

DEFAULT_MANIFEST_PATH = ROOT / "src" / "harness_cli" / "data" / "operations.json"
DEFAULT_OUTPUT_PATH = ROOT / "src" / "harness_cli" / "data" / "search_index.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the generated hctl search index.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    operations = manifest["operations"]
    source_hash = manifest["source_hash"]
    search_index = build_search_index_data(operations, source_hash)
    args.output.write_text(json.dumps(search_index, separators=(",", ":")) + "\n")
    print(f"Wrote {args.output}")
    print(f"Operations: {len(operations)}")
    print(f"Terms: {len(search_index['vocabulary'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
