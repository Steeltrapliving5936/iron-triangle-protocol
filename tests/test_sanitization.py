"""Sanitization scan: every git-tracked file must have zero private hits.

Fixture strings are composed from fragments so this test file never contains
a contiguous sensitive literal that the scanner itself would flag.
"""

from __future__ import annotations

import unittest

import _helpers  # noqa: F401  (sys.path bootstrap)

from iron_triangle import sanitizer

# Fragment-composed fixtures (never contiguous in source).
USER_HOME = "/Use" + "rs/to" + "ny"
SESSION_ID = "session_" + "ab12cd34"
MEMORY_ID = "mem_" + "20260818"
PERSON = "To" + "ny"
COMPANY_EN = "debe" + "tter"
COMPANY_ZH = "德佰" + "特"
INTERNAL_DOMAIN = "svc" + ".corp" + ".internal"
LITERAL_PORT = "http://127.0.0.1" + ":8765/api/v1"
TOKEN_PATH = "~/.config/ap" + "p/token.json"


class RepoScanTests(unittest.TestCase):
    def test_repo_has_zero_sanitization_hits(self):
        findings = sanitizer.scan_repo(_helpers.ROOT)
        self.assertEqual(findings, [], "\n".join(str(f) for f in findings))


class RuleCoverageTests(unittest.TestCase):
    def test_scanner_catches_each_forbidden_class(self):
        expectations = [
            (USER_HOME, "user-home"),
            (SESSION_ID, "session-id"),
            (MEMORY_ID, "memory-id"),
            (PERSON, "personal-name"),
            (COMPANY_EN, "company-name"),
            (COMPANY_ZH, "company-name"),
            (INTERNAL_DOMAIN, "internal-domain"),
            (LITERAL_PORT, "literal-api-port"),
            (TOKEN_PATH, "token-or-secret"),
        ]
        for text, rule_family in expectations:
            hits = sanitizer.scan_text(text)
            self.assertTrue(hits, f"expected a hit for the composed fixture ({rule_family})")
            rules = {label for label, _, _ in hits}
            self.assertTrue(
                any(rule.startswith(rule_family) for rule in rules),
                f"expected rule family {rule_family}, got {rules}",
            )

    def test_legitimate_identifiers_are_not_flagged(self):
        for text in (
            'adapter["token_file"]',
            "http://session-api.invalid/api/v1",
            "~/Library/LaunchAgents/io.iron-triangle.bridge.plist",
            "<path-to-local-token-file>",
        ):
            self.assertEqual(sanitizer.scan_text(text), [], text)


if __name__ == "__main__":
    unittest.main()
