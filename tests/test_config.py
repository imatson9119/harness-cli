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
    unset_config_value,
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

    def test_custom_profile_values_are_preserved_and_loaded_as_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            write_config_file(
                {
                    "host": "https://example.harness.io",
                    "account": "acc",
                    "pipelineIdentifier": "release_pipe",
                    "limit": 25,
                    "dryRun": False,
                    "service_token": "secret-token",
                },
                config_path,
                profile="prod",
            )

            data = json.loads(config_path.read_text(encoding="utf-8"))
            config = load_config(config_path)

            self.assertEqual(data["profiles"]["prod"]["pipelineIdentifier"], "release_pipe")
            self.assertEqual(data["profiles"]["prod"]["limit"], 25)
            self.assertFalse(data["profiles"]["prod"]["dryRun"])
            self.assertEqual(
                config.variables,
                {
                    "pipelineIdentifier": "release_pipe",
                    "limit": "25",
                    "dryRun": "false",
                    "service_token": "secret-token",
                },
            )
            self.assertNotIn("secret-token", str(config.redacted()))

    def test_config_set_and_unset_accept_custom_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            set_config_value("pipelineIdentifier", "release_pipe", config_path)
            self.assertEqual(
                load_config(config_path).variables["pipelineIdentifier"], "release_pipe"
            )

            unset_config_value("pipelineIdentifier", config_path)
            self.assertNotIn("pipelineIdentifier", load_config(config_path).variables)

    def test_config_keys_cannot_contain_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            with self.assertRaisesRegex(ValueError, "Config keys"):
                set_config_value("pipeline identifier", "release_pipe", config_path)

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

    def test_empty_config_file_behaves_like_missing_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("  \n", encoding="utf-8")

            config = load_config(config_path)

            self.assertEqual(config.profile, "default")
            self.assertEqual(config.host, "https://app.harness.io")

    def test_host_is_normalized_when_written_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            set_config_value("host", "https://example.harness.io/", config_path)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(data["profiles"]["default"]["host"], "https://example.harness.io")
            self.assertEqual(load_config(config_path).host, "https://example.harness.io")

    def test_invalid_host_is_rejected_when_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            with self.assertRaisesRegex(ValueError, "host must be an http"):
                set_config_value("host", "app.harness.io", config_path)

    def test_host_with_query_is_rejected_when_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            with self.assertRaisesRegex(ValueError, "query or fragment"):
                set_config_value("host", "https://app.harness.io?debug=true", config_path)

    def test_invalid_host_environment_is_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"HARNESS_HOST": "app.harness.io"}, clear=True),
            self.assertRaisesRegex(ValueError, "host must be an http"),
        ):
            load_config()

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

    def test_invalid_default_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            with self.assertRaisesRegex(ValueError, "default_output"):
                set_config_value("default_output", "xml", config_path)


if __name__ == "__main__":
    unittest.main()
