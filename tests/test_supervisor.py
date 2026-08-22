"""Supervisor generation and dry-run safety tests.

Covers the README support-matrix evidence for launchd / systemd / windows-task:

- rendered artifacts are deterministic and structurally correct;
- ``install --dry-run`` never touches a real or outside-isolation service
  definition path and never invokes launchctl/systemctl/schtasks;
- a real (non-dry-run) install for a non-launchd target fails closed.
"""

from __future__ import annotations

import json
import pathlib
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _helpers  # noqa: F401  (sys.path bootstrap)

from iron_triangle import supervisor
from iron_triangle.supervisor import ServiceDefinition

BRIDGE = _helpers.ROOT / "scripts" / "iron_triangle_bridge.py"

DEFN = ServiceDefinition(
    label="io.iron-triangle.test",
    program=[sys.executable, "/tmp/bridge", "--config", "/tmp/runtime.json", "daemon"],
    state_dir="/tmp/state",
    log_out="/tmp/state/out.log",
    log_err="/tmp/state/err.log",
)


class RendererTests(unittest.TestCase):
    def test_launchd_render_is_valid_plist_xml(self):
        payload = plistlib.loads(supervisor.render_launchd(DEFN))
        self.assertEqual(payload["Label"], "io.iron-triangle.test")
        self.assertTrue(payload["KeepAlive"])
        self.assertEqual(payload["ProgramArguments"][-1], "daemon")

    def test_systemd_render_contains_required_sections(self):
        unit = supervisor.render_systemd(DEFN)
        for fragment in ("[Unit]", "[Service]", "[Install]", "ExecStart=", "WantedBy=default.target"):
            self.assertIn(fragment, unit)
        self.assertIn("Restart=always", unit)

    def test_windows_render_is_a_schtasks_plan(self):
        plan = supervisor.render_windows_task(DEFN)
        self.assertIn("schtasks /Create", plan["command"])
        self.assertIn("io.iron-triangle.test", plan["command"])
        self.assertTrue(plan["restart_on_failure"])

    def test_plans_are_deterministic(self):
        config = {"supervisor": {"target": "launchd"}}
        first = supervisor.plan_install("systemd", config, DEFN)
        second = supervisor.plan_install("systemd", config, DEFN)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_uninstall_plans_cover_all_targets(self):
        config: dict = {}
        self.assertIn("bootout", [part for cmd in supervisor.plan_uninstall("launchd", config, DEFN)["commands"] for part in cmd])
        self.assertIn("disable", [part for cmd in supervisor.plan_uninstall("systemd", config, DEFN)["commands"] for part in cmd])
        self.assertIn("schtasks /Delete", supervisor.plan_uninstall("windows-task", config, DEFN)["commands"][0][1])


class DryRunNoSystemContactTests(unittest.TestCase):
    """In-process: dry-run must not execute any external command."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _config_path(self, target: str) -> pathlib.Path:
        config = {
            "schema_version": 2,
            "adapters": {
                "kimi-code": {
                    "base_url": "http://session-api.invalid/api/v1",
                    "token_file": str(self.home / "token"),
                }
            },
            "state_dir": str(self.home / "state"),
            "notifications": False,
            "supervisor": {
                "target": target,
                "label": "io.iron-triangle.test",
                "path": str(self.home / "Library" / "LaunchAgents" / "io.iron-triangle.test.plist"),
            },
        }
        path = self.home / "runtime.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def _run_main(self, *args: str) -> tuple[int, str, str]:
        from iron_triangle import cli

        out_path = self.home / "stdout.txt"
        err_path = self.home / "stderr.txt"
        with open(out_path, "w", encoding="utf-8") as sink_out, open(err_path, "w", encoding="utf-8") as sink_err:
            with mock.patch.object(subprocess, "run", side_effect=AssertionError("external command attempted")):
                with mock.patch("sys.stdout", sink_out), mock.patch("sys.stderr", sink_err):
                    code = cli.main(["--config", str(self._config_path("launchd")), *args])
        return code, out_path.read_text(encoding="utf-8"), err_path.read_text(encoding="utf-8")

    def test_dry_run_executes_no_external_command_and_writes_nothing(self):
        for target in ("launchd", "systemd", "windows-task"):
            with self.subTest(target=target):
                code, out, _err = self._run_main("install", "--dry-run", "--target", target)
                self.assertEqual(code, 0, out + _err)
                payload = json.loads(out)
                self.assertTrue(payload["dry_run"])
                # No service definition file anywhere in the isolated home.
                self.assertFalse((self.home / "Library" / "LaunchAgents").exists())
                self.assertFalse((self.home / ".config" / "systemd").exists())

    def test_non_launchd_real_install_fails_closed_without_execution(self):
        for target in ("systemd", "windows-task"):
            with self.subTest(target=target):
                code, out, err = self._run_main("install", "--target", target)
                self.assertEqual(code, 2, out + err)
                self.assertIn("dry-run", err)
                self.assertFalse((self.home / ".config" / "systemd").exists())


class CliDryRunOutputTests(unittest.TestCase):
    """Subprocess level: generated plans match the support-matrix claims."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.temp.name)
        self.config_path = self.home / "runtime.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "adapters": {
                        "kimi-code": {
                            "base_url": "http://session-api.invalid/api/v1",
                            "token_file": str(self.home / "token"),
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
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BRIDGE), "--config", str(self.config_path), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_launchd_dry_run_renders_plist_xml_inside_isolation(self):
        result = self.cli("install", "--dry-run", "--target", "launchd")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["rendered"].startswith("<?xml"))
        write_commands = [cmd for cmd in payload["commands"] if cmd and cmd[0] == "write"]
        self.assertEqual(
            pathlib.Path(write_commands[0][1]).resolve(),
            (self.home / "Library" / "LaunchAgents" / "io.iron-triangle.test.plist").resolve(),
        )
        flat = [part for cmd in payload["commands"] if cmd and cmd[0] != "write" for part in cmd]
        self.assertIn("launchctl", flat)
        self.assertFalse((self.home / "Library" / "LaunchAgents").exists())

    def test_systemd_dry_run_renders_unit_with_service_and_install(self):
        result = self.cli("install", "--dry-run", "--target", "systemd")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        for fragment in ("[Service]", "WantedBy=default.target", "ExecStart="):
            self.assertIn(fragment, payload["rendered"])
        flat = [part for cmd in payload["commands"] for part in cmd]
        self.assertIn("systemctl", flat)
        self.assertIn("--user", flat)

    def test_windows_task_dry_run_renders_schtasks_command(self):
        result = self.cli("install", "--dry-run", "--target", "windows-task")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        flat = [part for cmd in payload["commands"] for part in cmd]
        self.assertTrue(any("schtasks /Create" in part for part in flat))
        self.assertIn("schtasks", payload["rendered"])

    def test_real_install_for_systemd_fails_closed_via_cli(self):
        result = self.cli("install", "--target", "systemd")
        self.assertEqual(result.returncode, 2)
        self.assertIn("dry-run", result.stderr)
        self.assertFalse((self.home / ".config" / "systemd").exists())

    def test_uninstall_dry_run_plans_for_each_target(self):
        for target, marker in (("launchd", "bootout"), ("systemd", "disable"), ("windows-task", "schtasks /Delete")):
            with self.subTest(target=target):
                result = self.cli("uninstall", "--dry-run", "--target", target)
                self.assertEqual(result.returncode, 0, result.stderr)
                flat = [part for cmd in json.loads(result.stdout)["commands"] for part in cmd]
                self.assertTrue(any(marker in part for part in flat), flat)


if __name__ == "__main__":
    unittest.main()
