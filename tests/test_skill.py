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

    def test_every_skill_declares_cost_partition_and_decision_summary(self):
        """Mechanism 10 operationalized without adding an eleventh mechanism."""
        for skill_dir in [CANONICAL, *GENERATED]:
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Arbiter cost partition", text, skill_dir)
            self.assertIn("decision-summary block", text, skill_dir)
            self.assertIn("at most 10 lines", text, skill_dir)
            self.assertIn("do not exempt the cost partition", text, skill_dir)
            self.assertIn("Two consecutive execution-layer actions", text, skill_dir)
            self.assertIn("documented bridge commands", text, skill_dir)
            self.assertIn("MUST NOT call vendor session APIs", text, skill_dir)
            self.assertIn("do not add an eleventh mechanism", text, skill_dir)
            workflow = (skill_dir / "references" / "workflow.md").read_text(encoding="utf-8")
            self.assertIn("decision-summary block of at most 10 lines", workflow, skill_dir)
            self.assertEqual(workflow.count("Ten required mechanisms"), 1, skill_dir)
            template = (skill_dir / "references" / "templates.md").read_text(encoding="utf-8")
            self.assertIn("Decision summary", template, skill_dir)
            self.assertIn("Conclusion:", template, skill_dir)
            self.assertIn("Key figures:", template, skill_dir)
            self.assertIn("Decisions needed:", template, skill_dir)

    def test_public_skills_keep_generalized_markers_and_existing_contracts(self):
        """Sync must not weaken honesty, markers, failure controls, or briefing."""
        for skill_dir in [CANONICAL, *GENERATED]:
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("NEEDS_ARBITER:", text, skill_dir)
            self.assertIn("ROUND_CLOSURE_PASS:", text, skill_dir)
            self.assertNotIn("NEEDS_FABLE:", text, skill_dir)
            self.assertIn("open question", text, skill_dir)
            self.assertIn("never label executor self-review as independent", text, skill_dir)
            failures = (skill_dir / "references" / "failure-controls.md").read_text(encoding="utf-8")
            self.assertIn("Seven failure classes", failures, skill_dir)
            workflow = (skill_dir / "references" / "workflow.md").read_text(encoding="utf-8")
            for mechanism_line in (
                "Single append-only ledger",
                "Receipts for every claim",
                "Independent reproduction by the reviewer",
                "Fixed column-one escalation markers",
                "Fail closed on the affected line",
                "Pre-decision contract",
                "No silent second increase",
                "Real end-to-end acceptance",
                "Coordinated window rotation",
                "Arbiter involvement only for exceptions",
            ):
                self.assertIn(mechanism_line, workflow, skill_dir)

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


REQUIRED_SUMMARY_FIELDS = ("Conclusion", "Key figures", "Risks", "Decisions needed")
SUMMARY_LINE_LIMIT = 10


def parse_decision_summary(text: str) -> dict[str, str]:
    """Interpret a worker decision-summary block.

    The public template is the contract: a titled block of at most 10 lines
    with four labeled fields. The summary is intake for the arbiter, not
    evidence and not a substitute for receipts.
    """
    lines = [line.rstrip() for line in text.strip("\n").splitlines()]
    if not lines:
        raise ValueError("empty decision-summary block")
    if len(lines) > SUMMARY_LINE_LIMIT:
        raise ValueError(f"decision-summary exceeds {SUMMARY_LINE_LIMIT} lines")
    if lines[0].strip() != "Decision summary":
        raise ValueError("decision-summary must start with the title line")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        stripped = line.lstrip("- ").strip()
        if not stripped:
            continue
        name, separator, value = stripped.partition(":")
        if not separator:
            raise ValueError(f"unlabeled summary line: {stripped!r}")
        fields[name.strip()] = value.strip()
    missing = [name for name in REQUIRED_SUMMARY_FIELDS if name not in fields]
    if missing:
        raise ValueError(f"missing summary fields: {missing}")
    return {name: fields[name] for name in REQUIRED_SUMMARY_FIELDS}


class DecisionSummaryContractTests(unittest.TestCase):
    def test_canonical_template_example_parses(self):
        text = (CANONICAL / "references" / "templates.md").read_text(encoding="utf-8")
        start = text.index("```markdown\nDecision summary\n")
        fence = text.index("```", start + len("```markdown\n"))
        example = text[start + len("```markdown\n") : fence]
        parsed = parse_decision_summary(example)
        self.assertEqual(set(parsed), set(REQUIRED_SUMMARY_FIELDS))
        self.assertTrue(parsed["Conclusion"])
        self.assertLessEqual(len(example.strip("\n").splitlines()), SUMMARY_LINE_LIMIT)

    def test_parser_accepts_compact_block_and_rejects_violations(self):
        valid = (
            "Decision summary\n"
            "- Conclusion: 12/12 tests green\n"
            "- Key figures: sha256=abc, 12 tests\n"
            "- Risks: none\n"
            "- Decisions needed: none\n"
        )
        self.assertEqual(
            parse_decision_summary(valid)["Conclusion"],
            "12/12 tests green",
        )
        too_long = "Decision summary\n" + "".join(
            f"- padding {index}: x\n" for index in range(SUMMARY_LINE_LIMIT)
        )
        with self.assertRaisesRegex(ValueError, "exceeds"):
            parse_decision_summary(too_long)
        missing = (
            "Decision summary\n"
            "- Conclusion: done\n"
            "- Key figures: none\n"
            "- Risks: none\n"
        )
        with self.assertRaisesRegex(ValueError, "missing summary fields"):
            parse_decision_summary(missing)
        with self.assertRaisesRegex(ValueError, "empty"):
            parse_decision_summary("\n")


if __name__ == "__main__":
    unittest.main()
