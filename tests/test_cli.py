from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

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

        options = parse_call_options(
            operation,
            ["--limit", "5", "--output", "table", "--dry-run"],
            HarnessConfig(),
        )

        self.assertTrue(options.dry_run)
        self.assertEqual(options.output, "table")
        self.assertEqual(options.param_values["limit"], "5")

    def test_dynamic_call_parses_form_and_file_parameters(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["uploadSignature"]

        options = parse_call_options(
            operation,
            [
                "--org",
                "org",
                "--project",
                "proj",
                "--form",
                "note=release",
                "--file",
                "sig=@sig.txt",
            ],
            HarnessConfig(),
        )

        self.assertEqual(options.param_values["org"], "org")
        self.assertEqual(options.param_values["project"], "proj")
        self.assertEqual(options.form_values["note"], ["release"])
        self.assertEqual(options.file_values["sig"], ["@sig.txt"])

    def test_completion_script_prints_bash_function(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["completion", "bash"])

        self.assertEqual(status, 0)
        output = stdout.getvalue()
        self.assertIn("_harness_complete", output)
        self.assertIn("complete -F _harness_complete harness", output)

    def test_completion_scripts_keep_shell_quotes_balanced(self) -> None:
        for shell, expected in [
            ("zsh", '_harness "$@"'),
            ("fish", 'complete -c harness -f -a "(__harness_complete)"'),
        ]:
            with self.subTest(shell=shell):
                stdout = io.StringIO()

                with redirect_stdout(stdout):
                    status = main(["completion", shell])

                self.assertEqual(status, 0)
                self.assertIn(expected, stdout.getvalue())

    def test_completion_lists_matching_top_level_groups(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "account-", "--"])

        self.assertEqual(status, 0)
        self.assertIn("account-roles\n", stdout.getvalue())

    def test_completion_lists_group_operations(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "list", "--", "account-roles"])

        self.assertEqual(status, 0)
        self.assertIn("list-roles-acc\n", stdout.getvalue())

    def test_completion_respects_explicit_empty_current_word(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "", "--", "account-roles"])

        self.assertEqual(status, 0)
        self.assertIn("list-roles-acc\n", stdout.getvalue())

    def test_completion_lists_operation_flags(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "__complete",
                    "--current",
                    "--lim",
                    "--",
                    "account-roles",
                    "list-roles-acc",
                ]
            )

        self.assertEqual(status, 0)
        self.assertIn("--limit\n", stdout.getvalue())

    def test_profile_commands_manage_config_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            env = {"HARNESS_CONFIG": str(config_path)}

            with patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(
                        main(
                            [
                                "init",
                                "--non-interactive",
                                "--profile",
                                "prod",
                                "--api-key",
                                "secret-token",
                                "--account",
                                "acc",
                            ]
                        ),
                        0,
                    )

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    status = main(["profile", "list"])

                self.assertEqual(status, 0)
                self.assertIn("prod", stdout.getvalue())
                self.assertIn("yes", stdout.getvalue())

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    status = main(["profile", "current"])

                self.assertEqual(status, 0)
                self.assertEqual(stdout.getvalue().strip(), "prod")


if __name__ == "__main__":
    unittest.main()
