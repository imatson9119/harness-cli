from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_cli.config import (
    current_profile_name,
    list_profiles,
    load_config,
    remove_profile,
    set_config_value,
    use_profile,
    write_config_file,
)


class ConfigTests(unittest.TestCase):
    def test_write_config_file_uses_profile_document_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            write_config_file(
                {
                    "host": "https://example.harness.io",
                    "api_key": "secret-token",
                    "account": "acc",
                },
                config_path,
                profile="prod",
            )

            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(data["current_profile"], "prod")
            self.assertEqual(data["profiles"]["prod"]["account"], "acc")
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)

    def test_load_config_reads_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "current_profile": "stage",
                        "profiles": {
                            "prod": {"account": "prod-account"},
                            "stage": {"account": "stage-account"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config.profile, "stage")
            self.assertEqual(config.host, "https://app.harness.io")
            self.assertEqual(config.account, "stage-account")

    def test_harness_profile_environment_selects_profile(self) -> None:
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

            with patch.dict(os.environ, {"HARNESS_PROFILE": "stage"}, clear=True):
                config = load_config(config_path)

            self.assertEqual(config.profile, "stage")
            self.assertEqual(config.account, "stage-account")

    def test_profile_management_helpers_create_switch_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            use_profile("prod", config_path)
            set_config_value("account", "prod-account", config_path)
            use_profile("stage", config_path)

            self.assertEqual(current_profile_name(config_path), "stage")
            self.assertEqual(sorted(list_profiles(config_path)), ["prod", "stage"])

            remove_profile("stage", config_path)

            self.assertEqual(current_profile_name(config_path), "prod")
            self.assertEqual(sorted(list_profiles(config_path)), ["prod"])

    def test_malformed_profiles_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text('{"profiles":[]}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "profiles"):
                list_profiles(config_path)


if __name__ == "__main__":
    unittest.main()
