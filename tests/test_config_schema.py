"""Config schema, migration, and JSON Schema contract tests."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

import _helpers  # noqa: F401  (sys.path bootstrap)

from iron_triangle import CONFIG_SCHEMA_VERSION, config as config_mod

SCHEMA_PATH = _helpers.ROOT / "schemas" / "runtime-config.schema.json"
EXAMPLE_PATH = _helpers.ROOT / "examples" / "runtime-config.example.json"


class ExampleConfigTests(unittest.TestCase):
    def test_example_config_loads_and_validates(self):
        raw = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(raw.get("schema_version"), CONFIG_SCHEMA_VERSION)
        config_mod.validate_config(raw)  # raises on failure

    def test_schema_file_is_draft_2020_12_and_covers_validated_keys(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn("2020-12", schema["$schema"])
        self.assertEqual(schema["properties"]["schema_version"]["const"], CONFIG_SCHEMA_VERSION)
        for key in ("adapters", "state_dir"):
            self.assertIn(key, schema["required"])
        adapter_props = schema["properties"]["adapters"]["additionalProperties"]["properties"]
        # Every key the loader enforces has a place in the published schema.
        for key in ("base_url", "token_file", "event_dir", "permission_mode"):
            self.assertIn(key, adapter_props)
        for key in ("target", "label", "path"):
            self.assertIn(key, schema["properties"]["supervisor"]["properties"])


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def v1_config(self) -> dict:
        return {
            "adapters": {
                "kimi-code": {
                    "base_url": "http://session-api.invalid/api/v1",
                    "token_file": str(self.root / "token"),
                }
            },
            "state_dir": str(self.root / "state"),
            "launch_agent_label": "io.iron-triangle.bridge",
            "launch_agent_path": str(self.root / "Library" / "LaunchAgents" / "it.plist"),
        }

    def test_v1_migrates_in_memory_without_writing(self):
        raw = self.v1_config()
        migrated, notes = config_mod.migrate_config(raw)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["supervisor"]["label"], "io.iron-triangle.bridge")
        self.assertEqual(migrated["supervisor"]["path"], str(self.root / "Library" / "LaunchAgents" / "it.plist"))
        self.assertNotIn("launch_agent_label", migrated)
        self.assertNotIn("schema_version", raw)  # input untouched (pure function)

    def test_upgrade_writes_backup_and_is_idempotent(self):
        path = self.root / "runtime.json"
        path.write_text(json.dumps(self.v1_config()), encoding="utf-8")
        result = config_mod.upgrade_config_file(path)
        self.assertTrue(result["changed"])
        self.assertEqual(result["from_version"], 1)
        backup = pathlib.Path(result["backup"])
        self.assertTrue(backup.exists())
        migrated = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["supervisor"]["target"], "auto")
        second = config_mod.upgrade_config_file(path)
        self.assertFalse(second["changed"])

    def test_future_schema_version_fails_closed(self):
        from iron_triangle.errors import BridgeError

        raw = self.v1_config()
        raw["schema_version"] = CONFIG_SCHEMA_VERSION + 1
        with self.assertRaises(BridgeError):
            config_mod.migrate_config(raw)


if __name__ == "__main__":
    unittest.main()
