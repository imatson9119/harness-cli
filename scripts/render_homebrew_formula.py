#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Homebrew formula for hctl.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if len(args.sha256) != 64 or any(char not in "0123456789abcdef" for char in args.sha256):
        raise ValueError("--sha256 must be a lowercase SHA-256 hex digest")
    if args.version not in args.url:
        raise ValueError("--version must appear in --url so Homebrew can infer the stable version")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        FORMULA.format(version=args.version, url=args.url, sha256=args.sha256),
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    return 0


FORMULA = """class Hctl < Formula
  desc "Polished OpenAPI-backed command-line interface for Harness APIs"
  homepage "https://github.com/imatson9119/harness-cli"
  url "{url}"
  sha256 "{sha256}"
  license "MIT"

  depends_on "python@3.13"

  def install
    libexec.install "hctl.pyz"
    (bin/"hctl").write <<~EOS
      #!/bin/bash
      exec "#{{Formula["python@3.13"].opt_bin}}/python3.13" "#{{libexec}}/hctl.pyz" "$@"
    EOS
  end

  test do
    assert_match "hctl #{{version}}", shell_output("#{{bin}}/hctl --version")
    assert_match "operation_count", shell_output("#{{bin}}/hctl api info --json")
  end
end
"""


if __name__ == "__main__":
    raise SystemExit(main())
