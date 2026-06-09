from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from harness_cli.cli import main, parse_call_options
from harness_cli.config import HarnessConfig
from harness_cli.http import RequestError, Response
from harness_cli.manifest import load_manifest


class CliTests(unittest.TestCase):
    def test_api_list_search_prints_operation(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "list", "--search", "list-roles-acc", "--limit", "1"])

        self.assertEqual(status, 0)
        self.assertIn("list-roles-acc", stdout.getvalue())

    def test_api_info_prints_manifest_metadata(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "info"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("operation_count", output)
        self.assertIn("source_hash", output)

    def test_global_profile_and_config_select_command_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "current_profile": "prod",
                        "profiles": {
                            "prod": {"account": "prod-account"},
                            "stage": {"account": "stage-account"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                status = main(
                    [
                        "--config",
                        str(config_path),
                        "--profile",
                        "stage",
                        "auth",
                        "status",
                    ]
                )

        data = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(data["profile"], "stage")
        self.assertEqual(data["account"], "stage-account")

    def test_global_profile_override_restores_environment(self) -> None:
        with patch.dict(os.environ, {"HARNESS_PROFILE": "prod"}, clear=True):
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                status = main(["--profile", "stage", "--version"])

            self.assertEqual(status, 0)
            self.assertEqual(os.environ["HARNESS_PROFILE"], "prod")

    def test_api_body_prints_request_template(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "body", "create-role-acc"])

        data = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(data["identifier"], "example_role")
        self.assertIn("permissions", data)

    def test_api_body_json_prints_template_metadata(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "body", "create-role-acc", "--json"])

        data = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(data["operation_id"], "create-role-acc")
        self.assertEqual(data["content_type"], "application/json")
        self.assertEqual(data["body"]["identifier"], "example_role")

    def test_api_body_writes_request_template_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "role.json"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = main(["api", "body", "create-role-acc", "--output-file", str(output_path)])

            data = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Wrote", stderr.getvalue())
        self.assertEqual(data["identifier"], "example_role")

    def test_api_list_filters_to_body_operations_in_group(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "api",
                    "list",
                    "--group",
                    "account-roles",
                    "--has-body",
                    "--json",
                ]
            )

        operations = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(operations)
        self.assertTrue(all(item["group"] == "account-roles" for item in operations))
        self.assertTrue(all(item["request_body"] is not None for item in operations))
        self.assertIn("create-role-acc", {item["operation_id"] for item in operations})

    def test_api_list_filters_by_path_substring(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "list", "--path", "/v1/roles", "--json"])

        operations = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(operations)
        self.assertTrue(all("/v1/roles" in item["path"] for item in operations))

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
        self.assertEqual(options.query_values["limit"], ["5"])

    def test_dynamic_call_repeats_query_parameter_flags(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["listFilesAndFolders"]

        options = parse_call_options(
            operation,
            [
                "--account-identifier",
                "acc",
                "--identifiers",
                "one",
                "--identifiers",
                "two",
            ],
            HarnessConfig(),
        )

        self.assertEqual(options.query_values["accountIdentifier"], ["acc"])
        self.assertEqual(options.query_values["identifiers"], ["one", "two"])

    def test_dynamic_call_parses_pagination_helpers(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]

        options = parse_call_options(
            operation,
            ["--all", "--all-page-size", "100", "--max-pages", "3"],
            HarnessConfig(),
        )

        self.assertTrue(options.all_pages)
        self.assertEqual(options.all_page_size, 100)
        self.assertEqual(options.max_pages, 3)

    def test_pagination_tuning_flags_require_all(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]

        with self.assertRaisesRegex(ValueError, "require --all"):
            parse_call_options(operation, ["--max-pages", "3"], HarnessConfig())

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

    def test_completion_lists_api_body_action(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "bo", "--", "api"])

        self.assertEqual(status, 0)
        self.assertIn("body\n", stdout.getvalue())

    def test_completion_lists_global_options(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "--p", "--"])

        self.assertEqual(status, 0)
        self.assertIn("--profile\n", stdout.getvalue())

    def test_completion_resumes_after_global_profile(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "ap", "--", "--profile", "prod"])

        self.assertEqual(status, 0)
        self.assertIn("api\n", stdout.getvalue())

    def test_completion_lists_api_list_groups(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "account-", "--", "api", "list", "--group"])

        self.assertEqual(status, 0)
        self.assertIn("account-roles\n", stdout.getvalue())

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

    def test_api_describe_prints_examples_and_pagination_hint(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "describe", "list-roles-acc"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("Pagination: Supports --all", output)
        self.assertIn("Examples:", output)
        self.assertIn("harness account-roles list-roles-acc --all --output table", output)

    def test_api_describe_prints_body_template_hint(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "describe", "create-role-acc"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("Body template: harness api body create-role-acc", output)

    def test_operation_help_prints_required_account_alias(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["artifact-signing", "upload-signature", "--help"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("--account ACCOUNT", output)
        self.assertIn("--file file=@path", output)

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

    def test_init_writes_output_mode_and_prints_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            env = {"HARNESS_CONFIG": str(config_path)}

            with patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    status = main(
                        [
                            "init",
                            "--non-interactive",
                            "--profile",
                            "sandbox",
                            "--api-key",
                            "secret-token",
                            "--account",
                            "acc",
                            "--output",
                            "table",
                        ]
                    )

            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(status, 0)
            self.assertIn("Profile sandbox is ready", stdout.getvalue())
            self.assertEqual(data["profiles"]["sandbox"]["default_output"], "table")

    def test_transport_errors_print_clean_cli_message(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        env = {"HARNESS_API_KEY": "secret-token"}

        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "harness_cli.cli.send_request",
                side_effect=RequestError("GET /v1/roles failed: offline"),
            ),
            redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = main(["account-roles", "list-roles-acc", "--limit", "1"])

        combined = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(status, 1)
        self.assertIn("error: GET /v1/roles failed: offline", stderr.getvalue())
        self.assertNotIn("Traceback", combined)

    def test_doctor_network_check_reports_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "current_profile": "default",
                        "profiles": {
                            "default": {
                                "api_key": "secret-token",
                                "host": "https://app.harness.io",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config_path.chmod(0o600)
            stdout = io.StringIO()

            with (
                patch.dict(os.environ, {"HARNESS_CONFIG": str(config_path)}, clear=True),
                patch(
                    "harness_cli.cli.send_request",
                    return_value=Response(status=200, headers={}, body=b"{}"),
                ),
                redirect_stdout(stdout),
            ):
                status = main(["doctor", "--network", "--json"])

        data = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(data["network_check"]["ok"])
        self.assertEqual(data["network_check"]["path"], "/v1/version")

    def test_doctor_network_check_reports_transport_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "current_profile": "default",
                        "profiles": {
                            "default": {
                                "api_key": "secret-token",
                                "host": "https://app.harness.io",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config_path.chmod(0o600)
            stdout = io.StringIO()

            with (
                patch.dict(os.environ, {"HARNESS_CONFIG": str(config_path)}, clear=True),
                patch(
                    "harness_cli.cli.send_request",
                    side_effect=RequestError("GET /v1/version failed: offline"),
                ),
                redirect_stdout(stdout),
            ):
                status = main(["doctor", "--network", "--json"])

        data = json.loads(stdout.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(data["network_check"]["ok"])
        self.assertIn("Network check failed", data["issues"][0])


if __name__ == "__main__":
    unittest.main()
