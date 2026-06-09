from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from harness_cli.config import HarnessConfig
from harness_cli.http import CallOptions, Response, prepare_request, render_response
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

    def test_prepare_request_builds_multipart_file_body(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["uploadSignature"]
        config = HarnessConfig(api_key="harness-secret-token")

        with tempfile.TemporaryDirectory() as temp_dir:
            upload_path = Path(temp_dir) / "signature.txt"
            upload_path.write_text("signed", encoding="utf-8")

            request = prepare_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={"org": "org", "project": "proj"},
                    body=None,
                    content_type=None,
                    form_values={"note": ["release"]},
                    file_values={"signature": [str(upload_path)]},
                    dry_run=True,
                ),
            )

        body = request.body or b""
        self.assertIn("multipart/form-data; boundary=", request.headers["Content-Type"])
        self.assertIn(b'name="note"', body)
        self.assertIn(b"release", body)
        self.assertIn(b'filename="signature.txt"', body)
        self.assertIn(b"signed", body)

    def test_prepare_request_rejects_body_mixed_with_form_fields(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["create-role-acc"]
        config = HarnessConfig(api_key="harness-secret-token")

        with self.assertRaisesRegex(ValueError, "either --body"):
            prepare_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={},
                    body="{}",
                    content_type=None,
                    form_values={"name": ["demo"]},
                    dry_run=True,
                ),
            )

    def test_render_response_writes_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "response.bin"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                render_response(
                    Response(status=200, headers={}, body=b"binary-data"),
                    include=False,
                    output="json",
                    output_file=str(output_path),
                )

            self.assertEqual(output_path.read_bytes(), b"binary-data")
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("Wrote", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
