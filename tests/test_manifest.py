from __future__ import annotations

import unittest

from harness_cli.manifest import load_manifest


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


if __name__ == "__main__":
    unittest.main()
