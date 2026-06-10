from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from harness_cli.render import (
    CallStatus,
    colorize_json,
    format_http_status,
    print_data_table,
    print_json,
    print_table,
    stylize,
)


class TtyStringIO(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


class RenderTests(unittest.TestCase):
    def test_no_color_disables_styles(self) -> None:
        with patch.dict(os.environ, {"NO_COLOR": "1", "HARNESS_COLOR": "always"}, clear=True):
            self.assertEqual(stylize("plain", "red"), "plain")

    def test_harness_color_always_enables_styles(self) -> None:
        with patch.dict(os.environ, {"HARNESS_COLOR": "always"}, clear=True):
            self.assertIn("\033[31m", stylize("red", "red"))
            self.assertIn("\033[32m", format_http_status(200))

    def test_call_status_can_emit_final_line_without_animation(self) -> None:
        stderr = TtyStringIO()

        with (
            patch.dict(
                os.environ,
                {
                    "HARNESS_ANIMATION": "never",
                    "HARNESS_COLOR": "never",
                    "HARNESS_STATUS": "always",
                },
                clear=True,
            ),
            patch("harness_cli.render.sys.stderr", stderr),
            CallStatus("GET", "https://app.harness.io/v1/roles?limit=1") as status,
        ):
            status.done(200)

        output = stderr.getvalue()
        self.assertIn("GET /v1/roles -> HTTP 200 OK in", output)
        self.assertNotIn("...", output)

    def test_call_status_can_be_disabled_even_if_animation_is_forced(self) -> None:
        stderr = TtyStringIO()

        with (
            patch.dict(
                os.environ,
                {
                    "HARNESS_ANIMATION": "always",
                    "HARNESS_COLOR": "never",
                    "HARNESS_STATUS": "never",
                },
                clear=True,
            ),
            patch("harness_cli.render.sys.stderr", stderr),
            CallStatus("GET", "https://app.harness.io/v1/roles") as status,
        ):
            status.done(200)

        self.assertEqual(stderr.getvalue(), "")

    def test_print_json_stays_plain_without_tty(self) -> None:
        stdout = io.StringIO()

        with patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout):
            print_json({"ok": True})

        self.assertEqual(stdout.getvalue(), '{\n  "ok": true\n}\n')

    def test_json_colorizer_highlights_keys_and_values(self) -> None:
        with patch.dict(os.environ, {"HARNESS_COLOR": "always"}, clear=True):
            output = colorize_json('{"ok": true, "name": "demo"}')

        self.assertIn('\033[36m"ok"\033[0m', output)
        self.assertIn("\033[33mtrue\033[0m", output)
        self.assertIn('\033[32m"demo"\033[0m', output)

    def test_print_data_table_unwraps_common_list_payloads(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            print_data_table(
                {
                    "data": [
                        {"identifier": "one", "name": "First", "nested": {"ignored": True}},
                        {"identifier": "two", "name": "Second"},
                    ]
                }
            )

        output = stdout.getvalue()
        self.assertIn("identifier", output)
        self.assertIn("one", output)
        self.assertIn("Second", output)

    def test_print_data_table_unwraps_harness_data_content_payloads(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            print_data_table(
                {
                    "status": "SUCCESS",
                    "correlationId": "corr",
                    "data": {
                        "content": [
                            {"identifier": "pipe-one", "name": "First"},
                            {"identifier": "pipe-two", "name": "Second"},
                        ]
                    },
                }
            )

        output = stdout.getvalue()
        self.assertIn("identifier", output)
        self.assertIn("pipe-one", output)
        self.assertIn("Second", output)
        self.assertNotIn("correlationId", output)

    def test_print_table_stays_plain_without_tty(self) -> None:
        stdout = io.StringIO()

        with patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout):
            print_table(["name", "status"], [["svc", "ok"]])

        output = stdout.getvalue()
        self.assertIn("name | status", output)
        self.assertNotIn("╭", output)
        self.assertNotIn("+------", output)

    def test_print_table_can_force_unicode_frame(self) -> None:
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"HARNESS_TABLE_STYLE": "unicode"}, clear=True),
            redirect_stdout(stdout),
        ):
            print_table(["name", "status"], [["svc", "ok"]])

        output = stdout.getvalue()
        self.assertIn("╭", output)
        self.assertIn("┬", output)
        self.assertIn("│ name │ status │", output)
        self.assertIn("╰", output)

    def test_print_table_can_force_ascii_frame(self) -> None:
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"HARNESS_TABLE_STYLE": "ascii"}, clear=True),
            redirect_stdout(stdout),
        ):
            print_table(["name", "status"], [["svc", "ok"]])

        output = stdout.getvalue()
        self.assertIn("+------+--------+", output)
        self.assertIn("| name | status |", output)

    def test_print_table_wide_mode_preserves_long_cells(self) -> None:
        stdout = io.StringIO()
        long_value = "create-account-scoped-role-assignments"

        with redirect_stdout(stdout):
            print_table(["operation"], [[long_value]], fit_width=False, max_cell_width=None)

        output = stdout.getvalue()
        self.assertIn(long_value, output)
        self.assertNotIn("...", output)

    def test_harness_ascii_overrides_forced_unicode_table(self) -> None:
        stdout = io.StringIO()

        with (
            patch.dict(
                os.environ,
                {"HARNESS_TABLE_STYLE": "unicode", "HARNESS_ASCII": "1"},
                clear=True,
            ),
            redirect_stdout(stdout),
        ):
            print_table(["name"], [["svc"]])

        output = stdout.getvalue()
        self.assertIn("+------+", output)
        self.assertNotIn("╭", output)

    def test_print_data_table_uses_requested_columns_and_nested_values(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            print_data_table(
                {
                    "data": [
                        {
                            "identifier": "one",
                            "name": "First",
                            "metadata": {"status": "active"},
                            "ignored": "noise",
                        },
                        {
                            "identifier": "two",
                            "name": "Second",
                            "metadata": {"status": "paused"},
                            "ignored": "more-noise",
                        },
                    ]
                },
                columns=["identifier", "metadata.status"],
            )

        output = stdout.getvalue()
        self.assertIn("identifier", output)
        self.assertIn("metadata.status", output)
        self.assertIn("active", output)
        self.assertIn("paused", output)
        self.assertNotIn("ignored", output)
        self.assertNotIn("noise", output)

    def test_print_data_table_expands_array_columns_from_root(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            print_data_table(
                {
                    "status": "SUCCESS",
                    "correlationId": "corr",
                    "data": {
                        "content": [
                            {"name": "First", "metadata": {"status": "active"}},
                            {"name": "Second", "metadata": {"status": "paused"}},
                        ]
                    },
                },
                columns=["status", "data.content[].name", "data.content[].metadata.status"],
            )

        output = stdout.getvalue()
        self.assertIn("data.content[].name", output)
        self.assertIn("First", output)
        self.assertIn("Second", output)
        self.assertIn("active", output)
        self.assertIn("paused", output)
        self.assertEqual(output.count("SUCCESS"), 2)

    def test_print_data_table_renders_objects_as_key_value_rows(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            print_data_table({"identifier": "svc", "enabled": True})

        output = stdout.getvalue()
        self.assertIn("key", output)
        self.assertIn("identifier", output)
        self.assertIn("svc", output)


if __name__ == "__main__":
    unittest.main()
