"""CLI product-surface lifecycle tests, fully isolated from the real system.

install/uninstall run with --dry-run only; every path in the config points
into a temporary HOME-equivalent directory. No launchctl/systemctl call is
ever made by this suite.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import _helpers  # noqa: F401  (sys.path bootstrap)

BRIDGE = _helpers.ROOT / "scripts" / "iron_triangle_bridge.py"


class CliLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.temp.name)
        self.config_path = self.home / "runtime.json"
        config = {
            "schema_version": 2,
            "adapters": {
                "kimi-code": {
                    "base_url": "http://session-api.invalid/api/v1",
                    "token_file": str(self.home / "token"),
                    "default_executor_model": "executor-a",
                    "default_reviewer_model": "reviewer-b",
                }
            },
            "state_dir": str(self.home / "state"),
            "notifications": False,
            "supervisor": {
                "target": "launchd",
                "label": "io.iron-triangle.test",
                "path": str(self.home / "Library" / "LaunchAgents" / "io.iron-triangle.test.plist"),
            },
        }
        self.config_path.write_text(json.dumps(config), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BRIDGE), "--config", str(self.config_path), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_version_reports_tool_and_schema(self):
        result = self.cli("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tool_version"], "0.3.1")
        self.assertEqual(payload["config_schema_version"], 2)

    def test_install_dry_run_renders_plan_without_system_contact(self):
        result = self.cli("install", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["target"], "launchd")
        rendered = payload["rendered"]
        self.assertIn("io.iron-triangle.test", rendered)
        self.assertIn("daemon", rendered)
        # The plan's write target lives inside the isolated home only.
        write_commands = [cmd for cmd in payload["commands"] if cmd and cmd[0] == "write"]
        self.assertEqual(len(write_commands), 1)
        expected = (self.home / "Library" / "LaunchAgents" / "io.iron-triangle.test.plist").resolve()
        self.assertEqual(pathlib.Path(write_commands[0][1]).resolve(), expected)
        # Dry-run must not create the real service definition file.
        self.assertFalse((self.home / "Library" / "LaunchAgents").exists())

    def test_install_dry_run_is_deterministic(self):
        first = self.cli("install", "--dry-run").stdout
        second = self.cli("install", "--dry-run").stdout
        self.assertEqual(first, second)

    def test_doctor_passes_in_isolated_home(self):
        (self.home / "token").write_text("x", encoding="utf-8")
        result = self.cli("doctor")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        names = {check["name"] for check in payload["checks"]}
        self.assertLessEqual({"python", "config", "state_dir", "supervisor"}, names)

    def test_doctor_fails_closed_on_broken_config(self):
        self.config_path.write_text("{not json", encoding="utf-8")
        result = self.cli("doctor")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])

    def test_status_lists_no_runs_initially(self):
        result = self.cli("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_repair_is_idempotent_and_writes_only_inside_state_dir(self):
        first = self.cli("repair")
        self.assertEqual(first.returncode, 0, first.stderr)
        payload_first = json.loads(first.stdout)
        self.assertTrue(payload_first["ok"])
        reference = self.home / "state" / "service" / "io.iron-triangle.test.plist"
        self.assertTrue(reference.exists())
        content = reference.read_bytes()
        second = self.cli("repair")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertTrue(json.loads(second.stdout)["ok"])
        self.assertEqual(reference.read_bytes(), content)  # stable output

    def test_uninstall_dry_run_plans_bootout_and_removal(self):
        result = self.cli("uninstall", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"])
        flat = [part for cmd in payload["commands"] for part in cmd]
        self.assertIn("bootout", flat)

    def test_full_lifecycle_roundtrip(self):
        for command in (
            ["install", "--dry-run"],
            ["doctor"],
            ["status"],
            ["repair"],
            ["status"],
            ["uninstall", "--dry-run"],
        ):
            result = self.cli(*command)
            self.assertEqual(result.returncode, 0, f"{command}: {result.stderr}")

    def test_upgrade_migrates_legacy_config_file_with_backup(self):
        legacy = self.home / "legacy-runtime.json"
        legacy.write_text(
            json.dumps(
                {
                    "adapters": self._adapter(),
                    "state_dir": str(self.home / "state"),
                    "launch_agent_label": "io.iron-triangle.bridge",
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(BRIDGE), "--config", str(legacy), "upgrade"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["changed"])
        migrated = json.loads(legacy.read_text(encoding="utf-8"))
        self.assertEqual(migrated["supervisor"]["label"], "io.iron-triangle.bridge")
        backups = list(self.home.glob("legacy-runtime.json.bak-*"))
        self.assertEqual(len(backups), 1)

    def _adapter(self) -> dict:
        return {
            "kimi-code": {
                "base_url": "http://session-api.invalid/api/v1",
                "token_file": str(self.home / "token"),
            }
        }


if __name__ == "__main__":
    unittest.main()
