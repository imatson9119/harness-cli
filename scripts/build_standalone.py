#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import stat
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "hctl.pyz"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the standalone hctl zipapp.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with tempfile.TemporaryDirectory() as temp_dir:
        app_dir = Path(temp_dir) / "app"
        shutil.copytree(ROOT / "src" / "harness_cli", app_dir / "harness_cli")
        zipapp.create_archive(
            app_dir,
            target=output,
            interpreter="/usr/bin/env python3",
            main="harness_cli.__main__:main",
            compressed=True,
        )

    output.chmod(output.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
