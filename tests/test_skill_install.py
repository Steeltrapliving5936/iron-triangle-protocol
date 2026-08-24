"""Atomic platform-skill installation and read-back receipts."""

from __future__ import annotations

import pathlib
import tempfile
import unittest

import _helpers  # noqa: F401

from iron_triangle import skill_install
from iron_triangle.errors import BridgeError


class SkillInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.target_root = self.root / "skills"
        self.config = self.root / "runtime.json"
        self.config.write_text("{}\n", encoding="utf-8")
        self.bridge = _helpers.ROOT / "scripts" / "iron_triangle_bridge.py"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_default_roots_follow_platform_environment_contracts(self) -> None:
        home = self.root / "home"
        env = {
            "CODEX_HOME": str(self.root / "codex-data"),
            "CLAUDE_CONFIG_DIR": str(self.root / "claude-data"),
            "KIMI_CODE_HOME": str(self.root / "kimi-data"),
        }
        self.assertEqual(skill_install.default_skill_root("codex", environ=env, home=home), (self.root / "codex-data/skills").resolve())
        self.assertEqual(skill_install.default_skill_root("claude", environ=env, home=home), (self.root / "claude-data/skills").resolve())
        self.assertEqual(skill_install.default_skill_root("kimi", environ=env, home=home), (self.root / "kimi-data/skills").resolve())
        self.assertEqual(skill_install.default_skill_root("cursor", environ=env, home=home), (home / ".cursor/skills").resolve())

    def test_install_writes_private_binding_and_verifies_core_hash(self) -> None:
        result = skill_install.install_skill(
            "codex",
            target_root=self.target_root,
            config_path=self.config,
            bridge_path=self.bridge,
        )
        self.assertTrue(result["changed"])
        self.assertTrue(result["core_match"])
        self.assertTrue(result["runtime_binding_match"])
        binding = self.target_root / "iron-triangle/references/local-runtime.md"
        text = binding.read_text(encoding="utf-8")
        self.assertIn(str(self.config.resolve()), text)
        self.assertIn("Never use Computer Use", text)

    def test_status_detects_stale_installed_core(self) -> None:
        skill_install.install_skill(
            "codex", target_root=self.target_root, config_path=self.config, bridge_path=self.bridge
        )
        target = self.target_root / "iron-triangle/SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\nstale\n", encoding="utf-8")
        status = skill_install.skill_status(
            "codex", target_root=self.target_root, config_path=self.config, bridge_path=self.bridge
        )
        self.assertFalse(status["core_match"])

    def test_differing_install_requires_replace_and_creates_backup(self) -> None:
        skill_install.install_skill(
            "codex", target_root=self.target_root, config_path=self.config, bridge_path=self.bridge
        )
        target = self.target_root / "iron-triangle/SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\nstale\n", encoding="utf-8")
        with self.assertRaisesRegex(BridgeError, "--replace"):
            skill_install.install_skill(
                "codex", target_root=self.target_root, config_path=self.config, bridge_path=self.bridge
            )
        result = skill_install.install_skill(
            "codex",
            target_root=self.target_root,
            config_path=self.config,
            bridge_path=self.bridge,
            replace=True,
        )
        self.assertTrue(result["core_match"])
        self.assertTrue(pathlib.Path(result["backup"]).is_dir())


if __name__ == "__main__":
    unittest.main()
