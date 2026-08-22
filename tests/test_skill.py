"""Skill source, generator idempotency, and Agent Skills spec validation."""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

import _helpers  # noqa: F401  (sys.path bootstrap)

ROOT = _helpers.ROOT
CANONICAL = ROOT / "skills" / "iron-triangle"
GENERATED = [ROOT / "skills" / name / "iron-triangle" for name in ("codex", "claude", "kimi", "cursor")]


class SkillValidationTests(unittest.TestCase):
    def test_canonical_and_generated_skills_pass_spec_validation(self):
        from validate_skill import validate_skill

        for skill_dir in [CANONICAL, *GENERATED]:
            report = validate_skill(skill_dir)
            self.assertTrue(
                report["ok"],
                f"{skill_dir}: {report['errors']}",
            )

    def test_generated_skills_are_up_to_date(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_skills.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_every_skill_declares_trigger_phrases(self):
        description = (CANONICAL / "SKILL.md").read_text(encoding="utf-8")
        for phrase in ("铁三角", "启动铁三角", "iron triangle"):
            self.assertIn(phrase, description)

    def test_every_skill_declares_closure_briefing_and_language_automation(self):
        """Gap rulings: mandatory arbiter briefing + automatic response language."""
        for skill_dir in [CANONICAL, *GENERATED]:
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Arbiter closure briefing", text, skill_dir)
            self.assertIn("not a third technical reviewer", text, skill_dir)
            self.assertIn("explicit user authorization", text, skill_dir)
            self.assertIn("response_language", text, skill_dir)
            self.assertIn("never re-judge separately", text, skill_dir)
            template = (skill_dir / "references" / "templates.md").read_text(encoding="utf-8")
            self.assertIn("Continuation authority", template, skill_dir)

    def test_validator_rejects_bad_name(self):
        from validate_skill import validate_skill

        with tempfile.TemporaryDirectory() as temp:
            bad = pathlib.Path(temp) / "my_skill"
            bad.mkdir()
            (bad / "SKILL.md").write_text("---\nname: my_skill\ndescription: x\n---\nbody\n", encoding="utf-8")
            report = validate_skill(bad)
            self.assertFalse(report["ok"])
            self.assertTrue(any("name" in error for error in report["errors"]))

    def test_validator_requires_directory_name_match(self):
        from validate_skill import validate_skill

        with tempfile.TemporaryDirectory() as temp:
            bad = pathlib.Path(temp) / "other-name"
            bad.mkdir()
            (bad / "SKILL.md").write_text("---\nname: iron-triangle\ndescription: x\n---\nbody\n", encoding="utf-8")
            report = validate_skill(bad)
            self.assertFalse(report["ok"])

    def test_validator_rejects_dangling_reference(self):
        from validate_skill import validate_skill

        with tempfile.TemporaryDirectory() as temp:
            skill = pathlib.Path(temp) / "demo-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo-skill\ndescription: x\n---\nSee [missing](references/nope.md).\n",
                encoding="utf-8",
            )
            report = validate_skill(skill)
            self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()
