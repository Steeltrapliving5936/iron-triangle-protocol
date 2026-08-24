"""CLI product-surface lifecycle tests, fully isolated from the real system.

install/uninstall run with --dry-run only; every path in the config points
into a temporary HOME-equivalent directory. No launchctl/systemctl call is
ever made by this suite.
"""

from __future__ import annotations

import argparse
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
        self.assertEqual(payload["tool_version"], "0.3.2")
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

    def test_skill_install_and_status_have_hash_verified_readback(self):
        target_root = self.home / "codex-skills"
        install = self.cli(
            "skills",
            "install",
            "--platform",
            "codex",
            "--target-root",
            str(target_root),
        )
        self.assertEqual(install.returncode, 0, install.stderr)
        installed = json.loads(install.stdout)[0]
        self.assertTrue(installed["core_match"])
        self.assertTrue(installed["runtime_binding_match"])
        self.assertEqual(installed["runtime_binding"], "configured")

        status = self.cli(
            "skills",
            "status",
            "--platform",
            "codex",
            "--target-root",
            str(target_root),
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        readback = json.loads(status.stdout)[0]
        self.assertEqual(readback["source_hash"], readback["installed_hash"])
        self.assertTrue(readback["runtime_binding_match"])

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


class DaemonSelfRetireTests(unittest.TestCase):
    """The supervised daemon must retire on code change so the supervisor
    relaunches with the updated bridge; fully in-process and isolated."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.mod_a = self.root / "mod_a.py"
        self.mod_b = self.root / "mod_b.py"
        self.mod_a.write_text("a = 1\n", encoding="utf-8")
        self.mod_b.write_text("b = 2\n", encoding="utf-8")
        self.state = self.root / "state"
        self.config: dict = {"state_dir": str(self.state), "poll_interval_seconds": 2}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_bridge_identity_is_stable_and_change_sensitive(self):
        from iron_triangle.cli import bridge_identity

        baseline = bridge_identity([self.mod_a, self.mod_b])
        self.assertEqual(baseline, bridge_identity([self.mod_b, self.mod_a]))
        self.mod_b.write_text("b = 3\n", encoding="utf-8")
        self.assertNotEqual(baseline, bridge_identity([self.mod_a, self.mod_b]))
        missing = self.root / "gone.py"
        self.assertNotEqual(bridge_identity([missing]), bridge_identity([]))

    def test_bridge_identity_covers_tool_version(self):
        from unittest import mock

        from iron_triangle import cli

        baseline = cli.bridge_identity([self.mod_a])
        with mock.patch.object(cli, "TOOL_VERSION", "0.0.0-test"):
            self.assertNotEqual(baseline, cli.bridge_identity([self.mod_a]))

    def test_daemon_retires_between_passes_when_code_changes(self):
        from unittest import mock

        from iron_triangle import cli

        passes: list[int] = []

        def fake_watch_set(bridge_path):
            return [self.mod_a, self.mod_b]

        def fake_watch_once(*args, **kwargs):
            passes.append(1)
            return len(passes)

        def fake_sleep(_seconds):
            # After the first full pass, simulate an upgrade landing on disk.
            if len(passes) == 1:
                self.mod_b.write_text("b = 3\n", encoding="utf-8")

        with (
            mock.patch.object(cli, "daemon_watch_set", fake_watch_set),
            mock.patch.object(cli, "watch_once", fake_watch_once),
            mock.patch("time.sleep", fake_sleep),
        ):
            cli.cmd_daemon(argparse.Namespace(), self.config, self.root / "runtime.json")

        self.assertEqual(len(passes), 1, "daemon must finish the pass, then exit — not abandon it midway")
        lines = (self.state / "daemon-errors.jsonl").read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines]
        self.assertEqual(events[-1]["kind"], "bridge-identity-changed")

    def test_daemon_keeps_running_while_identity_holds(self):
        from unittest import mock

        from iron_triangle import cli

        passes: list[int] = []

        def fake_watch_set(bridge_path):
            return [self.mod_a]

        def fake_watch_once(*args, **kwargs):
            passes.append(1)
            return len(passes)

        sleeps: list[int] = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) >= 3:
                raise KeyboardInterrupt  # escape the infinite loop

        with (
            mock.patch.object(cli, "daemon_watch_set", fake_watch_set),
            mock.patch.object(cli, "watch_once", fake_watch_once),
            mock.patch("time.sleep", fake_sleep),
        ):
            with self.assertRaises(KeyboardInterrupt):
                cli.cmd_daemon(argparse.Namespace(), self.config, self.root / "runtime.json")

        self.assertEqual(len(passes), 3)


if __name__ == "__main__":
    unittest.main()
