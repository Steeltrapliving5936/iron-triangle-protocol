"""Security canary: the sanitizer must catch every forbidden rule end to end.

The unit fixtures in ``test_sanitization.py`` exercise ``scan_text`` per rule.
This canary goes one step further and proves the full repo-scan path —
``git ls-files`` discovery, file reading, rule matching, and the CLI exit
contract — against a synthetic repository that plants one canary file per
forbidden rule, while the public tree itself scans zero.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest

import _helpers  # noqa: F401  (sys.path bootstrap)

from iron_triangle import sanitizer

# Canary fixtures, fragment-composed so this test file itself never contains a
# contiguous sensitive literal. One file per rule in sanitizer.RULES.
CANARY_FILES = {
    "canary-user-home.txt": ("/Use" + "rs/some" + "body", "user-home-path"),
    "canary-session-id.txt": ("session_" + "ab12cd34", "session-id"),
    "canary-memory-id.txt": ("mem_" + "20260818", "memory-id"),
    "canary-personal-name.txt": ("contact To" + "ny please", "personal-name"),
    "canary-company-name.txt": ("debe" + "tter", "company-name"),
    "canary-internal-domain.txt": ("svc" + ".corp" + ".internal", "internal-domain"),
    "canary-api-port.txt": ("http://127.0.0.1" + ":8765/api/v1", "literal-api-port"),
    "canary-token-path.txt": ("~/.config/ap" + "p/token.json", "token-or-secret-path"),
    "canary-config-dir.txt": (".config/" + "iron-triangle/runtime.json", "private-config-dir"),
}


def build_canary_repo(root: pathlib.Path) -> None:
    """A minimal git repository whose index holds one canary file per rule."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name, (text, _rule) in CANARY_FILES.items():
        (root / name).write_text(text + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)


class SecurityCanaryTests(unittest.TestCase):
    def test_rule_inventory_is_fully_covered_by_the_canary(self) -> None:
        # A new sanitizer rule without a canary file must fail here first.
        self.assertEqual(
            {rule for _file, (_text, rule) in CANARY_FILES.items()},
            {label for label, _pattern in sanitizer.RULES},
        )

    def test_canary_repo_scan_hits_every_rule_on_its_own_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp) / "canary-repo"
            build_canary_repo(root)
            findings = sanitizer.scan_repo(root)
        by_file: dict[str, set[str]] = {}
        for finding in findings:
            by_file.setdefault(finding["file"], set()).add(finding["rule"])
        for name, (_text, rule) in CANARY_FILES.items():
            self.assertIn(rule, by_file.get(name, set()), f"{name} did not trip {rule}")

    def test_canary_cli_exits_nonzero_and_names_every_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp) / "canary-repo"
            build_canary_repo(root)
            result = subprocess.run(
                [str(sys_executable()), str(sanitizer_path()), str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1, result.stdout)
        for _name, (_text, rule) in CANARY_FILES.items():
            self.assertIn(f"[{rule}]", result.stdout, rule)
        self.assertIn("FAILED", result.stdout + result.stderr)

    def test_public_tree_scan_is_zero_via_cli(self) -> None:
        result = subprocess.run(
            [str(sys_executable()), str(sanitizer_path()), str(_helpers.ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 hits", result.stdout)


def sys_executable():
    import sys

    return sys.executable


def sanitizer_path() -> pathlib.Path:
    return _helpers.SRC / "iron_triangle" / "sanitizer.py"


if __name__ == "__main__":
    unittest.main()
