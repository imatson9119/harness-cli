from __future__ import annotations

import json
import unittest
from importlib import resources

from harness_cli.manifest import load_manifest
from harness_cli.search import validate_search_index_data
from scripts.validate_openapi_manifest import validate_manifest


class ManifestTests(unittest.TestCase):
    def test_generated_manifest_loads_many_harness_operations(self) -> None:
        manifest = load_manifest()

        self.assertGreaterEqual(manifest.operation_count, 2700)
        self.assertEqual(manifest.operation_count, len(manifest.operations))
        self.assertIn("account-roles", manifest.groups)
        self.assertIn("list-roles-acc", manifest.by_operation_id)

    def test_group_command_pairs_are_unique(self) -> None:
        manifest = load_manifest()
        pairs = [(operation.group, operation.command) for operation in manifest.operations]

        self.assertEqual(len(pairs), len(set(pairs)))

    def test_operation_can_be_resolved_by_group_command(self) -> None:
        manifest = load_manifest()
        operation = manifest.find_operation("account-roles/list-roles-acc")

        self.assertIsNotNone(operation)
        self.assertEqual(operation.operation_id, "list-roles-acc")
        self.assertEqual(operation.method, "get")
        self.assertEqual(operation.path, "/v1/roles")

    def test_generated_manifest_passes_integrity_validation(self) -> None:
        manifest = load_manifest()

        self.assertEqual(validate_manifest(manifest.raw), [])

    def test_bundled_search_index_matches_generated_manifest(self) -> None:
        manifest = load_manifest()
        search_index = json.loads(
            resources.files("harness_cli.data")
            .joinpath("search_index.json")
            .read_text(encoding="utf-8")
        )

        self.assertEqual(validate_search_index_data(manifest.raw, search_index), [])

    def test_search_handles_common_discovery_queries(self) -> None:
        manifest = load_manifest()
        cases = [
            ("list roles", 5, lambda operation: operation.command.startswith("list-roles")),
            ("role assignments", 5, lambda operation: operation.group == "role-assignments"),
            ("project secrets", 5, lambda operation: operation.group == "project-secret"),
            ("org connectors", 5, lambda operation: operation.group == "org-connector"),
            (
                "delete connector",
                5,
                lambda operation: (
                    operation.command.startswith("delete") and "connector" in operation.group
                ),
            ),
            (
                "create service",
                5,
                lambda operation: (
                    operation.command.startswith("create") and "service" in operation.command
                ),
            ),
            (
                "service overrides",
                5,
                lambda operation: (
                    "service-override" in operation.group
                    or "service-overrides" in operation.command
                ),
            ),
            (
                "rerun failed pipeline",
                5,
                lambda operation: (
                    operation.command.startswith(("rerun", "retry"))
                    and "pipeline" in f"{operation.group} {operation.command}"
                ),
            ),
            ("piplne execution", 5, lambda operation: operation.group.startswith("pipeline-")),
            (
                "pipeline input sets",
                5,
                lambda operation: operation.group == "pipeline-input-set",
            ),
            ("approval reject", 5, lambda operation: operation.group == "approvals"),
            (
                "delegates tokens",
                5,
                lambda operation: operation.group == "delegate-token-resource",
            ),
            (
                "environments",
                5,
                lambda operation: "environment" in f"{operation.group} {operation.command}",
            ),
            ("sbom score", 5, lambda operation: "sbom" in f"{operation.group} {operation.command}"),
            (
                "artifact provenance",
                5,
                lambda operation: "provenance" in operation.command,
            ),
            ("user groups", 5, lambda operation: operation.group == "user-group"),
            ("api keys", 5, lambda operation: "key" in f"{operation.group} {operation.command}"),
            (
                "chaos experiment run",
                5,
                lambda operation: "experiment" in operation.group and "run" in operation.command,
            ),
            ("audit trail", 5, lambda operation: operation.group.startswith("audit")),
            (
                "git repositories",
                5,
                lambda operation: "repository" in f"{operation.group} {operation.summary}".lower(),
            ),
        ]

        for query, limit, predicate in cases:
            with self.subTest(query=query):
                results = manifest.search(text=query)[:limit]
                rendered = [
                    f"{operation.group}/{operation.command}: {operation.summary}"
                    for operation in results
                ]

                self.assertTrue(any(predicate(operation) for operation in results), rendered)


if __name__ == "__main__":
    unittest.main()
