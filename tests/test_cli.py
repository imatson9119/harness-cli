from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from harness_cli.cli import main, parse_call_options
from harness_cli.config import HarnessConfig
from harness_cli.manifest import load_manifest


class CliTests(unittest.TestCase):
    def test_api_list_search_prints_operation(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "list", "--search", "list-roles-acc", "--limit", "1"])

        self.assertEqual(status, 0)
        self.assertIn("list-roles-acc", stdout.getvalue())

    def test_dynamic_call_parses_kebab_case_parameters(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]

        options = parse_call_options(operation, ["--limit", "5", "--dry-run"], HarnessConfig())

        self.assertTrue(options.dry_run)
        self.assertEqual(options.param_values["limit"], "5")


if __name__ == "__main__":
    unittest.main()

