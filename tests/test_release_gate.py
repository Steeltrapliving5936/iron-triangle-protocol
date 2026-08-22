"""Release-path integrity: nothing the release workflow references may dangle.

The CI workflow and the release-gates document are the executable definition
of a release. This suite pins every in-repository path they reference to an
existing file or directory, so a rename cannot silently break the first
remote run.
"""

from __future__ import annotations

import pathlib
import re
import unittest

import _helpers  # noqa: F401  (sys.path bootstrap)

ROOT = _helpers.ROOT

REPO_PATH_PATTERN = re.compile(r"(?:scripts|src|skills|schemas|docs|tests)/[A-Za-z0-9][A-Za-z0-9._/-]*")
TRAILING_PUNCTUATION = ".,;)']\"`"


def referenced_repo_paths(text: str) -> list[str]:
    found: list[str] = []
    for match in REPO_PATH_PATTERN.findall(text):
        path = match.rstrip(TRAILING_PUNCTUATION)
        if path not in found:
            found.append(path)
    return found


class ReleasePathTests(unittest.TestCase):
    def test_ci_workflow_exists_and_references_live_paths(self) -> None:
        workflow = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(workflow.is_file(), workflow)
        text = workflow.read_text(encoding="utf-8")
        for candidate in referenced_repo_paths(text):
            self.assertTrue(
                (ROOT / candidate).exists(),
                f"CI workflow references missing path: {candidate}",
            )

    def test_ci_workflow_names_the_five_skill_directories(self) -> None:
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for skill in (
            "skills/iron-triangle",
            "skills/codex/iron-triangle",
            "skills/claude/iron-triangle",
            "skills/kimi/iron-triangle",
            "skills/cursor/iron-triangle",
        ):
            self.assertIn(skill, text)

    def test_cross_version_matrix_is_defined(self) -> None:
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        versions = re.findall(r'python-version:\s*\["([^"]+)",\s*"([^"]+)"\]', text)
        self.assertTrue(versions, "expected a python-version matrix entry")
        for pair in versions:
            for version in pair:
                self.assertRegex(version, r"^3\.\d+$")

    def test_release_gates_document_references_live_paths_only(self) -> None:
        text = (ROOT / "docs" / "release-gates.md").read_text(encoding="utf-8")
        for candidate in referenced_repo_paths(text):
            self.assertTrue(
                (ROOT / candidate).exists(),
                f"release-gates doc references missing path: {candidate}",
            )

    def test_top_level_documents_shipped_by_readme_exist(self) -> None:
        for name in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE"):
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
