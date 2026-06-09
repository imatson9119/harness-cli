from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from harness_cli.config import HarnessConfig
from harness_cli.http import (
    CallOptions,
    PreparedRequest,
    RequestError,
    Response,
    prepare_request,
    render_curl,
    render_response,
    send_paginated_request,
    send_request,
)
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

    def test_redacted_headers_mask_common_secret_header_names(self) -> None:
        request = PreparedRequest(
            "GET",
            "https://app.harness.io/v1/roles",
            {
                "Authorization": "Bearer harness-secret-token",
                "Content-Type": "application/json",
                "X-API-Key": "manual-secret-token",
                "X-Client-Token": "client-secret-token",
            },
            None,
        )

        headers = request.redacted_headers()

        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertNotIn("harness-secret-token", headers["Authorization"])
        self.assertNotIn("manual-secret-token", headers["X-API-Key"])
        self.assertNotIn("client-secret-token", headers["X-Client-Token"])
        self.assertIn("Bear...oken", headers["Authorization"])

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

    def test_prepare_request_rejects_invalid_host_override(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]
        config = HarnessConfig(api_key="harness-secret-token")

        with self.assertRaisesRegex(ValueError, "host must be an http"):
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
                    host="app.harness.io",
                ),
            )

    def test_prepare_request_rejects_query_in_host_override(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]
        config = HarnessConfig(api_key="harness-secret-token")

        with self.assertRaisesRegex(ValueError, "query or fragment"):
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
                    host="https://app.harness.io?debug=true",
                ),
            )

    def test_prepare_request_maps_account_to_harness_account_header(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["uploadSignature"]
        config = HarnessConfig(api_key="harness-secret-token", account="acc")

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
                dry_run=True,
            ),
        )

        self.assertEqual(request.headers["Harness-Account"], "acc")

    def test_prepare_request_maps_profile_account_to_account_id_query(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["getSamlLoginTest"]
        config = HarnessConfig(api_key="harness-secret-token", account="acc")

        request = prepare_request(
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

        parsed = urlsplit(request.url)
        self.assertEqual(parsed.path, "/ng/api/authentication-settings/saml-login-test")
        self.assertEqual(parse_qs(parsed.query), {"accountId": ["acc"]})

    def test_prepare_request_maps_profile_account_to_snake_path_and_query(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["CreateAlert"]
        config = HarnessConfig(api_key="harness-secret-token", account="acc")

        request = prepare_request(
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

        parsed = urlsplit(request.url)
        self.assertEqual(parsed.path, "/gateway/lw/api/accounts/acc/alerts")
        self.assertEqual(parse_qs(parsed.query), {"accountIdentifier": ["acc"]})

    def test_prepare_request_maps_profile_scope_to_snake_identifier_queries(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["AddOciArtifactTags"]
        config = HarnessConfig(
            api_key="harness-secret-token",
            account="acc",
            org="org",
            project="proj",
        )

        request = prepare_request(
            operation,
            config,
            CallOptions(
                path_values={},
                query_values={},
                header_values={},
                param_values={"registry_identifier": "reg"},
                body=None,
                content_type=None,
                dry_run=True,
            ),
        )

        parsed = urlsplit(request.url)
        self.assertEqual(parsed.path, "/har/api/v2/oci/tags")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "account_identifier": ["acc"],
                "org_identifier": ["org"],
                "project_identifier": ["proj"],
                "registry_identifier": ["reg"],
            },
        )

    def test_prepare_request_explicit_query_overrides_profile_scope_defaults(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["getSamlLoginTest"]
        config = HarnessConfig(api_key="harness-secret-token", account="profile-acc")

        request = prepare_request(
            operation,
            config,
            CallOptions(
                path_values={},
                query_values={"accountId": ["manual-acc"]},
                header_values={},
                param_values={},
                body=None,
                content_type=None,
                dry_run=True,
            ),
        )

        parsed = urlsplit(request.url)
        self.assertEqual(parse_qs(parsed.query), {"accountId": ["manual-acc"]})

    def test_prepare_request_explicit_header_overrides_profile_account_header(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["uploadSignature"]
        config = HarnessConfig(api_key="harness-secret-token", account="profile-acc")

        request = prepare_request(
            operation,
            config,
            CallOptions(
                path_values={},
                query_values={},
                header_values={"Harness-Account": "manual-acc"},
                param_values={"org": "org", "project": "proj"},
                body=None,
                content_type=None,
                dry_run=True,
            ),
        )

        self.assertEqual(request.headers["Harness-Account"], "manual-acc")

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

    def test_prepare_request_rejects_missing_upload_file_cleanly(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["uploadSignature"]
        config = HarnessConfig(api_key="harness-secret-token")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            self.assertRaisesRegex(ValueError, "Could not read upload file"),
        ):
            prepare_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={"org": "org", "project": "proj"},
                    body=None,
                    content_type=None,
                    file_values={"signature": [str(Path(temp_dir) / "missing.sig")]},
                    dry_run=True,
                ),
            )

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

    def test_prepare_request_validates_body_json_inline_input(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["create-role-acc"]
        config = HarnessConfig(api_key="harness-secret-token")

        request = prepare_request(
            operation,
            config,
            CallOptions(
                path_values={},
                query_values={},
                header_values={},
                param_values={},
                body='{"identifier":"demo"}',
                content_type=None,
                body_json=True,
                dry_run=True,
            ),
        )

        self.assertEqual(request.headers["Content-Type"], "application/json")
        self.assertEqual(request.body, b'{"identifier":"demo"}')

    def test_prepare_request_validates_body_json_file_input(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["create-role-acc"]
        config = HarnessConfig(api_key="harness-secret-token")

        with tempfile.TemporaryDirectory() as temp_dir:
            body_path = Path(temp_dir) / "role.json"
            body_path.write_text('{"identifier":"demo"}', encoding="utf-8")

            request = prepare_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={},
                    body=f"@{body_path}",
                    content_type=None,
                    body_json=True,
                    dry_run=True,
                ),
            )

        self.assertEqual(request.body, b'{"identifier":"demo"}')

    def test_prepare_request_rejects_missing_body_file_cleanly(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["create-role-acc"]
        config = HarnessConfig(api_key="harness-secret-token")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            self.assertRaisesRegex(ValueError, "Could not read body file"),
        ):
            prepare_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={},
                    body=f"@{Path(temp_dir) / 'missing.json'}",
                    content_type=None,
                    dry_run=True,
                ),
            )

    def test_prepare_request_rejects_invalid_body_json(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["create-role-acc"]
        config = HarnessConfig(api_key="harness-secret-token")

        with self.assertRaisesRegex(ValueError, "--body-json received invalid JSON"):
            prepare_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={},
                    body="{nope",
                    content_type=None,
                    body_json=True,
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

    def test_render_response_rejects_unwritable_output_file_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
                self.assertRaisesRegex(ValueError, "Could not write output file"),
            ):
                render_response(
                    Response(status=200, headers={}, body=b"binary-data"),
                    include=False,
                    output="json",
                    output_file=temp_dir,
                )

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_render_response_can_print_json_as_table(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            render_response(
                Response(
                    status=200,
                    headers={},
                    body=b'{"data":[{"identifier":"svc","name":"Service","status":"ok"}]}',
                ),
                include=False,
                output="table",
            )

        output = stdout.getvalue()
        self.assertIn("identifier", output)
        self.assertIn("Service", output)

    def test_render_response_can_print_selected_table_columns(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            render_response(
                Response(
                    status=200,
                    headers={},
                    body=(
                        b'{"data":[{"identifier":"svc","name":"Service",'
                        b'"metadata":{"status":"ok"},"ignored":"noise"}]}'
                    ),
                ),
                include=False,
                output="table",
                table_columns=("identifier", "metadata.status"),
            )

        output = stdout.getvalue()
        self.assertIn("identifier", output)
        self.assertIn("metadata.status", output)
        self.assertIn("svc", output)
        self.assertIn("ok", output)
        self.assertNotIn("ignored", output)
        self.assertNotIn("noise", output)

    def test_render_curl_redacts_api_key_and_includes_body(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            render_curl(
                PreparedRequest(
                    "POST",
                    "https://app.harness.io/v1/roles",
                    {
                        "Content-Type": "application/json",
                        "x-api-key": "harness-secret-token",
                    },
                    b'{"name":"Demo"}',
                )
            )

        output = stdout.getvalue()
        self.assertIn("curl -X POST", output)
        self.assertIn("https://app.harness.io/v1/roles", output)
        self.assertIn("Content-Type: application/json", output)
        self.assertIn("--data-raw", output)
        self.assertNotIn("harness-secret-token", output)
        self.assertIn("harn...oken", output)

    def test_send_request_converts_transport_errors(self) -> None:
        request = PreparedRequest("GET", "https://app.harness.io/v1/roles?limit=1", {}, None)

        with (
            patch(
                "harness_cli.http.urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ),
            self.assertRaisesRegex(RequestError, "GET /v1/roles failed: offline"),
        ):
            send_request(request, timeout=30.0)

    def test_send_paginated_request_aggregates_page_limit_responses(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["list-roles-acc"]
        config = HarnessConfig(api_key="harness-secret-token")
        seen_urls: list[str] = []

        def fake_send(request: PreparedRequest, *, timeout: float) -> Response:
            seen_urls.append(request.url)
            page = len(seen_urls) - 1
            if page == 0:
                body = {"data": [{"identifier": "one"}, {"identifier": "two"}], "totalPages": 2}
            else:
                body = {"data": [{"identifier": "three"}], "totalPages": 2}
            return Response(
                status=200,
                headers={"Content-Type": "application/json"},
                body=json.dumps(body).encode("utf-8"),
            )

        with patch("harness_cli.http.send_request", fake_send):
            response = send_paginated_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={},
                    body=None,
                    content_type=None,
                    all_pages=True,
                    all_page_size=2,
                ),
                timeout=30.0,
            )

        parsed_urls = [urlsplit(url) for url in seen_urls]
        self.assertEqual([url.path for url in parsed_urls], ["/v1/roles", "/v1/roles"])
        self.assertEqual(
            [parse_qs(url.query) for url in parsed_urls],
            [
                {"page": ["0"], "limit": ["2"]},
                {"page": ["1"], "limit": ["2"]},
            ],
        )
        self.assertEqual(
            json.loads(response.body.decode("utf-8")),
            [{"identifier": "one"}, {"identifier": "two"}, {"identifier": "three"}],
        )

    def test_send_paginated_request_supports_page_size_parameters(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["getEnvironmentList"]
        config = HarnessConfig(api_key="harness-secret-token", account="acc")
        seen_urls: list[str] = []

        def fake_send(request: PreparedRequest, *, timeout: float) -> Response:
            seen_urls.append(request.url)
            body = {"data": [{"identifier": "one"}, {"identifier": "two"}]}
            if len(seen_urls) > 1:
                body = {"data": [{"identifier": "three"}]}
            return Response(
                status=200,
                headers={"Content-Type": "application/json"},
                body=json.dumps(body).encode("utf-8"),
            )

        with patch("harness_cli.http.send_request", fake_send):
            response = send_paginated_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={},
                    body=None,
                    content_type=None,
                    all_pages=True,
                    all_page_size=2,
                ),
                timeout=30.0,
            )

        parsed_urls = [urlsplit(url) for url in seen_urls]
        self.assertEqual([url.path for url in parsed_urls], ["/ng/api/environmentsV2"] * 2)
        self.assertEqual(
            [parse_qs(url.query) for url in parsed_urls],
            [
                {"accountIdentifier": ["acc"], "page": ["0"], "size": ["2"]},
                {"accountIdentifier": ["acc"], "page": ["1"], "size": ["2"]},
            ],
        )
        self.assertEqual(
            json.loads(response.body.decode("utf-8")),
            [{"identifier": "one"}, {"identifier": "two"}, {"identifier": "three"}],
        )

    def test_send_paginated_request_supports_page_page_size_parameters(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["Exemptions#ListExemptions"]
        config = HarnessConfig(api_key="harness-secret-token")
        seen_urls: list[str] = []

        def fake_send(request: PreparedRequest, *, timeout: float) -> Response:
            seen_urls.append(request.url)
            body = {"data": [{"identifier": "first"}]}
            return Response(
                status=200,
                headers={"Content-Type": "application/json"},
                body=json.dumps(body).encode("utf-8"),
            )

        with patch("harness_cli.http.send_request", fake_send):
            response = send_paginated_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={"accountId": "acc"},
                    body=None,
                    content_type=None,
                    all_pages=True,
                    all_page_size=2,
                ),
                timeout=30.0,
            )

        parsed = urlsplit(seen_urls[0])
        self.assertEqual(parsed.path, "/sto/api/v2/exemptions")
        self.assertEqual(
            parse_qs(parsed.query), {"accountId": ["acc"], "page": ["0"], "pageSize": ["2"]}
        )
        self.assertEqual(json.loads(response.body.decode("utf-8")), [{"identifier": "first"}])

    def test_send_paginated_request_supports_offset_page_size_parameters(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["getList"]
        config = HarnessConfig(api_key="harness-secret-token")
        seen_urls: list[str] = []

        def fake_send(request: PreparedRequest, *, timeout: float) -> Response:
            seen_urls.append(request.url)
            body = {"data": [{"identifier": "one"}, {"identifier": "two"}]}
            if len(seen_urls) > 1:
                body = {"data": [{"identifier": "three"}]}
            return Response(
                status=200,
                headers={"Content-Type": "application/json"},
                body=json.dumps(body).encode("utf-8"),
            )

        with patch("harness_cli.http.send_request", fake_send):
            response = send_paginated_request(
                operation,
                config,
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={
                        "accountId": "acc",
                        "orgIdentifier": "org",
                        "projectIdentifier": "proj",
                    },
                    body=None,
                    content_type=None,
                    all_pages=True,
                    all_page_size=2,
                ),
                timeout=30.0,
            )

        parsed_urls = [urlsplit(url) for url in seen_urls]
        self.assertEqual([url.path for url in parsed_urls], ["/cv/api/monitored-service/list"] * 2)
        self.assertEqual(
            [parse_qs(url.query) for url in parsed_urls],
            [
                {
                    "accountId": ["acc"],
                    "orgIdentifier": ["org"],
                    "projectIdentifier": ["proj"],
                    "offset": ["0"],
                    "pageSize": ["2"],
                },
                {
                    "accountId": ["acc"],
                    "orgIdentifier": ["org"],
                    "projectIdentifier": ["proj"],
                    "offset": ["2"],
                    "pageSize": ["2"],
                },
            ],
        )
        self.assertEqual(
            json.loads(response.body.decode("utf-8")),
            [{"identifier": "one"}, {"identifier": "two"}, {"identifier": "three"}],
        )

    def test_send_paginated_request_rejects_non_paginated_operations(self) -> None:
        manifest = load_manifest()
        operation = manifest.by_operation_id["get-role-acc"]

        with self.assertRaisesRegex(ValueError, "--all requires"):
            send_paginated_request(
                operation,
                HarnessConfig(api_key="harness-secret-token"),
                CallOptions(
                    path_values={},
                    query_values={},
                    header_values={},
                    param_values={"role": "admin"},
                    body=None,
                    content_type=None,
                    all_pages=True,
                ),
                timeout=30.0,
            )


if __name__ == "__main__":
    unittest.main()
