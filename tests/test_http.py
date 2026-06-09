from __future__ import annotations

import unittest

from harness_cli.config import HarnessConfig
from harness_cli.http import CallOptions, prepare_request
from harness_cli.manifest import load_manifest


class HttpTests(unittest.TestCase):
    def test_prepare_request_injects_query_and_redacts_key(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]
        config = HarnessConfig(api_key="harness-secret-token")

        request = prepare_request(
            operation,
            config,
            CallOptions(
                path_values={},
                query_values={},
                header_values={},
                param_values={"limit": "10"},
                body=None,
                content_type=None,
                dry_run=True,
            ),
        )

        self.assertEqual(request.method, "GET")
        self.assertEqual(request.url, "https://app.harness.io/v1/roles?limit=10")
        self.assertEqual(request.headers["x-api-key"], "harness-secret-token")
        self.assertNotEqual(request.redacted_headers()["x-api-key"], "harness-secret-token")

    def test_prepare_request_requires_missing_path_parameters(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["get-role-acc"]
        config = HarnessConfig(api_key="harness-secret-token")

        with self.assertRaisesRegex(ValueError, "role"):
            prepare_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={},
                    body=None,
                    content_type=None,
                    dry_run=True,
                ),
            )


if __name__ == "__main__":
    unittest.main()

