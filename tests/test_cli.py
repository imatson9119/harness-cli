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


class TtyStringIO(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


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

    def test_api_groups_can_search_and_limit_json_output(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "groups", "--search", "pipeline", "--limit", "2", "--json"])

        groups = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(len(groups), 2)
        self.assertTrue(
            all("pipeline" in item["group"] or "Pipeline" in item["tag"] for item in groups)
        )

    def test_api_groups_rejects_non_positive_limit(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            status = main(["api", "groups", "--limit", "0"])

        self.assertEqual(status, 2)
        self.assertIn("--limit must be greater than zero", stderr.getvalue())

    def test_api_list_rejects_non_positive_limit(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            status = main(["api", "list", "--limit", "0"])

        self.assertEqual(status, 2)
        self.assertIn("--limit must be greater than zero", stderr.getvalue())

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

    def test_config_set_rejects_invalid_host_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch.dict(os.environ, {"HARNESS_CONFIG": str(config_path)}, clear=True),
                redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                status = main(["config", "set", "host", "app.harness.io"])

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("host must be an http(s) URL", stderr.getvalue())

    def test_config_commands_accept_custom_profile_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            env = {"HARNESS_CONFIG": str(config_path)}

            with patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    set_status = main(["config", "set", "pipelineIdentifier", "release_pipeline"])

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    get_status = main(["config", "get", "pipelineIdentifier"])

            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(set_status, 0)
            self.assertEqual(get_status, 0)
            self.assertEqual(stdout.getvalue().strip(), "release_pipeline")
            self.assertEqual(
                data["profiles"]["default"]["pipelineIdentifier"],
                "release_pipeline",
            )

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

    def test_api_body_prints_raw_yaml_string_template(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "api",
                    "body",
                    "create-account-scoped-connector",
                    "--content-type",
                    "application/yaml",
                ]
            )

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertTrue(output.startswith("connector:\n"), output)
        self.assertIn("identifier: example_connector", output)
        self.assertNotIn("\\n", output)
        self.assertNotIn('"connector:', output)

    def test_api_body_prints_structured_yaml_template(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "api",
                    "body",
                    "getAccessControlList",
                    "--content-type",
                    "application/yaml",
                ]
            )

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertTrue(output.startswith("permissions:\n"), output)
        self.assertIn("- permission: string", output)
        self.assertIn("resourceIdentifier: string", output)

    def test_api_body_json_metadata_keeps_yaml_body_wrapped(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "api",
                    "body",
                    "create-account-scoped-connector",
                    "--content-type",
                    "application/yaml",
                    "--json",
                ]
            )

        data = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(data["content_type"], "application/yaml")
        self.assertTrue(data["body"].startswith("connector:\n"))

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

    def test_api_body_writes_raw_yaml_template_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "connector.yaml"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = main(
                    [
                        "api",
                        "body",
                        "create-account-scoped-connector",
                        "--content-type",
                        "application/yaml",
                        "--output-file",
                        str(output_path),
                    ]
                )

            text = output_path.read_text(encoding="utf-8")

        self.assertEqual(status, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Wrote", stderr.getvalue())
        self.assertTrue(text.startswith("connector:\n"), text)
        self.assertNotIn("\\n", text)

    def test_api_body_rejects_unwritable_output_file_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = main(
                    [
                        "api",
                        "body",
                        "create-role-acc",
                        "--output-file",
                        temp_dir,
                    ]
                )

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Could not write output file", stderr.getvalue())

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

    def test_api_list_accepts_uppercase_method_filter(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "list", "--method", "GET", "--limit", "3", "--json"])

        operations = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(len(operations), 3)
        self.assertTrue(all(item["method"] == "get" for item in operations))

    def test_api_list_rejects_unknown_method_filter(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            status = main(["api", "list", "--method", "fetch"])

        self.assertEqual(status, 2)
        self.assertIn("--method must be one of:", stderr.getvalue())

    def test_api_list_rejects_unknown_group_with_suggestion(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            status = main(["api", "list", "--group", "accunt-roles"])

        self.assertEqual(status, 2)
        self.assertIn("Unknown API group: accunt-roles.", stderr.getvalue())
        self.assertIn("account-roles", stderr.getvalue())

    def test_api_list_wide_prints_full_operation_slugs(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "api",
                    "list",
                    "--search",
                    "Create a role assignment",
                    "--limit",
                    "1",
                    "--wide",
                ]
            )

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("create-account-scoped-role-assignments", output)
        self.assertNotIn("create-account-scoped...", output)

    def test_api_call_prints_dispatcher_help(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "call", "--help"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("Usage:", output)
        self.assertIn("hctl api call OPERATION [flags]", output)
        self.assertIn("--content-type value", output)
        self.assertIn("--timeout seconds", output)
        self.assertIn("--no-auth", output)

    def test_api_call_operation_help_matches_generated_surface(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "call", "list-roles-acc", "--help"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("Usage: hctl account-roles list-roles-acc [flags]", output)
        self.assertIn("hctl api call list-roles-acc [flags]", output)
        self.assertIn("Pagination: Supports --all", output)
        self.assertIn("--output json|raw|table", output)
        self.assertIn("--api-key KEY", output)
        self.assertIn("--columns a,b,c", output)
        self.assertIn("--body-template", output)

    def test_command_reference_documents_generic_call_flags(self) -> None:
        docs = (Path(__file__).resolve().parents[1] / "docs" / "commands.md").read_text(
            encoding="utf-8"
        )

        for flag in [
            "--path key=value",
            "--query key=value",
            "--header key=value",
            "--param key=value",
            "--body VALUE|@file|-",
            "--body-file path",
            "--body-json JSON",
            "--body-template",
            "--form key=value",
            "--file field=@path",
            "--content-type value",
            "--columns a,b,c",
            "--unwrap",
            "--jq path",
            "--output json|raw|table",
            "--output-file path",
            "--all",
            "--all-page-size 100",
            "--max-pages 50",
            "--curl",
            "--dry-run",
            "--include",
            "--timeout seconds",
            "--host http(s)-url",
            "--api-key KEY",
            "--no-auth",
        ]:
            self.assertIn(flag, docs)

    def test_api_call_operation_help_works_after_flags(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "call", "list-roles-acc", "--query", "limit=10", "--help"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("Usage: hctl account-roles list-roles-acc [flags]", output)
        self.assertIn("Pagination: Supports --all", output)

    def test_generated_operation_help_works_after_flags(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["account-roles", "list-roles-acc", "--limit", "10", "--help"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("Usage: hctl account-roles list-roles-acc [flags]", output)
        self.assertIn("--limit (query; optional; default: 30)", output)

    def test_help_value_for_body_remains_request_data(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "call", "create-role-acc", "--body", "help", "--dry-run"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("POST https://app.harness.io/v1/roles", output)
        self.assertIn("\nhelp\n", output)
        self.assertNotIn("Usage:", output)

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

    def test_body_json_defaults_content_type_and_marks_validation(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["create-role-acc"]

        options = parse_call_options(
            operation,
            ["--body-json", '{"identifier":"demo"}', "--dry-run"],
            HarnessConfig(),
        )

        self.assertTrue(options.body_json)
        self.assertEqual(options.body, '{"identifier":"demo"}')
        self.assertEqual(options.content_type, "application/json")

    def test_body_template_uses_generated_json_sample(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["create-role-acc"]

        options = parse_call_options(operation, ["--body-template", "--dry-run"], HarnessConfig())

        self.assertTrue(options.body_json)
        self.assertEqual(options.content_type, "application/json")
        self.assertIsNotNone(options.body)
        body = json.loads(options.body)
        self.assertEqual(body["identifier"], "example_role")
        self.assertIn("permissions", body)

    def test_body_template_uses_generated_yaml_sample(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["getAccessControlList"]

        options = parse_call_options(
            operation,
            ["--body-template", "--content-type", "application/yaml", "--dry-run"],
            HarnessConfig(),
        )

        self.assertFalse(options.body_json)
        self.assertEqual(options.content_type, "application/yaml")
        self.assertIsNotNone(options.body)
        self.assertTrue(options.body.startswith("permissions:\n"), options.body)
        self.assertIn("- permission: string", options.body)

    def test_body_template_rejects_other_body_inputs(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["create-role-acc"]

        with self.assertRaisesRegex(ValueError, "--body-template cannot be combined"):
            parse_call_options(
                operation,
                ["--body-template", "--body", "{}"],
                HarnessConfig(),
            )

    def test_body_json_invalid_input_prints_clean_error(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(["api", "call", "create-role-acc", "--body-json", "{nope", "--dry-run"])

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--body-json received invalid JSON", stderr.getvalue())

    def test_generated_call_can_dry_run_body_template(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "call", "create-role-acc", "--body-template", "--dry-run"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("POST https://app.harness.io/v1/roles", output)
        self.assertIn("Content-Type: application/json", output)
        self.assertIn('"identifier": "example_role"', output)

    def test_generated_call_can_dry_run_yaml_body_template(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "api",
                    "call",
                    "getAccessControlList",
                    "--body-template",
                    "--content-type",
                    "application/yaml",
                    "--dry-run",
                ]
            )

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("POST https://app.harness.io/authz/api/acl", output)
        self.assertIn("Content-Type: application/yaml", output)
        self.assertIn("permissions:\n", output)
        self.assertIn("- permission: string", output)

    def test_generated_call_rejects_missing_body_file_cleanly(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = main(
                [
                    "api",
                    "call",
                    "create-role-acc",
                    "--body",
                    f"@{Path(temp_dir) / 'missing.json'}",
                    "--dry-run",
                ]
            )

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Could not read body file", stderr.getvalue())

    def test_generated_call_rejects_missing_upload_file_cleanly(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = main(
                [
                    "artifact-signing",
                    "upload-signature",
                    "--org",
                    "org",
                    "--project",
                    "proj",
                    "--file",
                    f"signature=@{Path(temp_dir) / 'missing.sig'}",
                    "--dry-run",
                ]
            )

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Could not read upload file", stderr.getvalue())

    def test_table_columns_parse_for_table_output(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]

        options = parse_call_options(
            operation,
            ["--output", "table", "--columns", "identifier,name", "--columns", "createdAt"],
            HarnessConfig(),
        )

        self.assertEqual(options.output, "table")
        self.assertEqual(options.table_columns, ("identifier", "name", "createdAt"))

    def test_response_selection_flags_parse_for_calls(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]

        options = parse_call_options(
            operation,
            ["--unwrap", "--jq", "content[]", "--output", "table"],
            HarnessConfig(),
        )

        self.assertTrue(options.unwrap_response)
        self.assertEqual(options.jq_path, "content[]")
        self.assertEqual(options.output, "table")

    def test_table_columns_require_table_output(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]

        with self.assertRaisesRegex(ValueError, "--columns requires --output table"):
            parse_call_options(operation, ["--columns", "identifier,name"], HarnessConfig())

    def test_generated_call_can_print_curl_without_api_key(self) -> None:
        stdout = io.StringIO()

        with patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout):
            status = main(["account-roles", "list-roles-acc", "--limit", "1", "--curl"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("curl -X GET", output)
        self.assertIn("https://app.harness.io/v1/roles?limit=1", output)

    def test_unique_operation_slug_can_be_called_directly(self) -> None:
        stdout = io.StringIO()

        with patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout):
            status = main(["list-roles-acc", "--limit", "1", "--curl"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("curl -X GET", output)
        self.assertIn("https://app.harness.io/v1/roles?limit=1", output)

    def test_ambiguous_operation_prints_numbered_choices_noninteractive(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            patch.dict(os.environ, {}, clear=True),
        ):
            status = main(["api", "call", "get-pipeline", "--curl"])

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ambiguous operation 'get-pipeline'", stderr.getvalue())
        self.assertIn("1. pipelines/get-pipeline", stderr.getvalue())
        self.assertIn("2. pipeline/get-pipeline", stderr.getvalue())

    def test_ambiguous_operation_can_be_selected_interactively(self) -> None:
        stdout = io.StringIO()
        stderr = TtyStringIO()
        stdin = TtyStringIO("1\n")

        with (
            redirect_stdout(stdout),
            patch("harness_cli.cli.sys.stdin", stdin),
            patch("harness_cli.cli.sys.stderr", stderr),
            patch.dict(os.environ, {}, clear=True),
        ):
            status = main(
                [
                    "api",
                    "call",
                    "get-pipeline",
                    "--org",
                    "org",
                    "--project",
                    "proj",
                    "--pipeline",
                    "pipe",
                    "--curl",
                ]
            )

        self.assertEqual(status, 0)
        self.assertIn("Ambiguous operation 'get-pipeline'", stderr.getvalue())
        self.assertIn("/v1/orgs/org/projects/proj/pipelines/pipe", stdout.getvalue())

    def test_generated_call_rejects_invalid_host_override(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.dict(os.environ, {}, clear=True),
            redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = main(
                [
                    "account-roles",
                    "list-roles-acc",
                    "--host",
                    "app.harness.io",
                    "--curl",
                ]
            )

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("host must be an http(s) URL", stderr.getvalue())

    def test_generated_curl_preview_redacts_api_key(self) -> None:
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"HARNESS_API_KEY": "harness-secret-token"}, clear=True),
            redirect_stdout(stdout),
        ):
            status = main(["account-roles", "list-roles-acc", "--limit", "1", "--curl"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("x-api-key: harn...oken", output)
        self.assertNotIn("harness-secret-token", output)

    def test_generated_dry_run_redacts_manual_secret_headers(self) -> None:
        stdout = io.StringIO()

        with patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout):
            status = main(
                [
                    "account-roles",
                    "list-roles-acc",
                    "--header",
                    "Authorization=Bearer harness-secret-token",
                    "--header",
                    "X-API-Key=manual-secret-token",
                    "--dry-run",
                ]
            )

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("Authorization: Bear...oken", output)
        self.assertIn("X-API-Key: manu...oken", output)
        self.assertNotIn("harness-secret-token", output)
        self.assertNotIn("manual-secret-token", output)

    def test_pagination_tuning_flags_require_all(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]

        with self.assertRaisesRegex(ValueError, "require --all"):
            parse_call_options(operation, ["--max-pages", "3"], HarnessConfig())

    def test_curl_preview_cannot_combine_with_all_pages(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(["account-roles", "list-roles-acc", "--all", "--curl"])

        self.assertEqual(status, 2)
        self.assertIn("--curl cannot be combined with --all", stderr.getvalue())

    def test_call_timeout_rejects_non_positive_value(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(["account-roles", "list-roles-acc", "--timeout", "0", "--curl"])

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--timeout must be greater than zero", stderr.getvalue())

    def test_call_timeout_rejects_non_numeric_value(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(["account-roles", "list-roles-acc", "--timeout", "soon", "--curl"])

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--timeout must be a number of seconds", stderr.getvalue())

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
        self.assertIn("_hctl_complete", output)
        self.assertIn("complete -F _hctl_complete hctl", output)

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

    def test_completion_lists_api_group_search_flag(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "--se", "--", "api", "groups"])

        self.assertEqual(status, 0)
        self.assertIn("--search\n", stdout.getvalue())

    def test_completion_lists_api_list_wide_flag(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "--wi", "--", "api", "list"])

        self.assertEqual(status, 0)
        self.assertIn("--wide\n", stdout.getvalue())

    def test_completion_lists_doctor_fix_permissions(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "--fix", "--", "doctor"])

        self.assertEqual(status, 0)
        self.assertIn("--fix-permissions\n", stdout.getvalue())

    def test_completion_scripts_keep_shell_quotes_balanced(self) -> None:
        for shell, expected in [
            ("zsh", '_hctl "$@"'),
            ("fish", 'complete -c hctl -f -a "(__hctl_complete)"'),
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

    def test_completion_lists_matching_top_level_operation_shortcuts(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "list-roles", "--"])

        self.assertEqual(status, 0)
        self.assertIn("list-roles-acc\n", stdout.getvalue())

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

    def test_completion_lists_direct_operation_flags(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["__complete", "--current", "--lim", "--", "list-roles-acc"])

        self.assertEqual(status, 0)
        self.assertIn("--limit\n", stdout.getvalue())

    def test_completion_lists_api_call_content_types(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "__complete",
                    "--current",
                    "application/",
                    "--",
                    "api",
                    "call",
                    "create-role-acc",
                    "--content-type",
                ]
            )

        self.assertEqual(status, 0)
        self.assertIn("application/json\n", stdout.getvalue())

    def test_completion_lists_generated_call_content_types(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "__complete",
                    "--current",
                    "application/",
                    "--",
                    "account-roles",
                    "create-role-acc",
                    "--content-type",
                ]
            )

        self.assertEqual(status, 0)
        self.assertIn("application/json\n", stdout.getvalue())

    def test_api_describe_prints_examples_and_pagination_hint(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "describe", "list-roles-acc"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("Pagination: Supports --all", output)
        self.assertIn("Examples:", output)
        self.assertIn("hctl account-roles list-roles-acc --all --output table", output)

    def test_api_describe_prints_body_template_hint(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            status = main(["api", "describe", "create-role-acc"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("Body template: hctl api body create-role-acc", output)

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
            self.assertIn("api_key (required for calls)", stdout.getvalue())
            self.assertIn("account (optional default)", stdout.getvalue())
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

    def test_doctor_reports_loose_config_permissions_without_fixing(self) -> None:
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
            config_path.chmod(0o644)
            stdout = io.StringIO()

            with (
                patch.dict(os.environ, {"HARNESS_CONFIG": str(config_path)}, clear=True),
                redirect_stdout(stdout),
            ):
                status = main(["doctor", "--json"])
            mode = config_path.stat().st_mode & 0o777

        data = json.loads(stdout.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(data["fixed_permissions"])
        self.assertEqual(mode, 0o644)
        self.assertIn("Config file permissions are 644; expected 600.", data["issues"])

    def test_doctor_can_fix_config_permissions(self) -> None:
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
            config_path.chmod(0o644)
            stdout = io.StringIO()

            with (
                patch.dict(os.environ, {"HARNESS_CONFIG": str(config_path)}, clear=True),
                redirect_stdout(stdout),
            ):
                status = main(["doctor", "--fix-permissions", "--json"])
            mode = config_path.stat().st_mode & 0o777

        data = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(data["fixed_permissions"])
        self.assertEqual(data["issues"], [])
        self.assertEqual(mode, 0o600)

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
