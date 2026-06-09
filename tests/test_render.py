from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from harness_cli.render import colorize_json, format_http_status, print_json, stylize


class RenderTests(unittest.TestCase):
    def test_no_color_disables_styles(self) -> None:
        with patch.dict(os.environ, {"NO_COLOR": "1", "HARNESS_COLOR": "always"}, clear=True):
            self.assertEqual(stylize("plain", "red"), "plain")

    def test_harness_color_always_enables_styles(self) -> None:
        with patch.dict(os.environ, {"HARNESS_COLOR": "always"}, clear=True):
            self.assertIn("\033[31m", stylize("red", "red"))
            self.assertIn("\033[32m", format_http_status(200))

    def test_print_json_stays_plain_without_tty(self) -> None:
        stdout = io.StringIO()

        with patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout):
            print_json({"ok": True})

        self.assertEqual(stdout.getvalue(), '{\n  "ok": true\n}\n')

    def test_json_colorizer_highlights_keys_and_values(self) -> None:
        with patch.dict(os.environ, {"HARNESS_COLOR": "always"}, clear=True):
            output = colorize_json('{"ok": true, "name": "demo"}')

        self.assertIn("\033[36m\"ok\"\033[0m", output)
        self.assertIn("\033[33mtrue\033[0m", output)
        self.assertIn("\033[32m\"demo\"\033[0m", output)


if __name__ == "__main__":
    unittest.main()
