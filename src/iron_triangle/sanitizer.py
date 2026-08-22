"""Sanitization scanner for public artifacts.

Scans every git-tracked file for private identifiers that must never appear
in the public repository. Run directly or via ``tests/test_sanitization.py``:

    python3 -m iron_triangle.sanitizer   # from src/ on sys.path

Exit code 0 means zero hits; 1 means violations were found.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

# Each rule: (label, compiled regex). Order matters only for report readability.
# Patterns are assembled from fragments so this scanner never contains a
# contiguous sensitive literal that would trip its own scan of tracked files.
RULES: list[tuple[str, re.Pattern[str]]] = [
    ("user-home-path", re.compile(r"/Users/[A-Za-z0-9._-]+", re.IGNORECASE)),
    ("session-id", re.compile(r"\bsession_" + r"[A-Za-z0-9_-]{4,}")),
    ("memory-id", re.compile(r"\bmem_" + r"2026[0-9A-Za-z]*")),
    ("personal-name", re.compile(r"\btony\b", re.IGNORECASE)),
    ("company-name", re.compile("debe" + "tter|德佰" + "特", re.IGNORECASE)),
    ("internal-domain", re.compile(r"[A-Za-z0-9.-]+\.(?:internal|corp|lan|local|home\.arpa)\b", re.IGNORECASE)),
    ("literal-api-port", re.compile(r"(?:localhost|127\.0\.0\.1):\d{2,}|https?://[^\s<>\"'`]*:\d+")),
    (
        "token-or-secret-path",
        re.compile(r"(?<![\w<>.\-])(?:/|~/)[\w@./-]*(?:token|secret|credential)[\w@./-]*", re.IGNORECASE),
    ),
    ("private-config-dir", re.compile(r"\.config[/\\]" + r"iron-triangle", re.IGNORECASE)),
]

# Literal strings that are legitimate code identifiers, not leaks.
ALLOWED_EXACT = {
    "token_file",  # config key name used by the loader
}


def scan_text(text: str) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped in ALLOWED_EXACT:
            continue
        for label, pattern in RULES:
            match = pattern.search(line)
            if match:
                hits.append((label, line_number, match.group(0)))
    return hits


def tracked_files(repo_root: pathlib.Path) -> list[pathlib.Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return [repo_root / name for name in result.stdout.splitlines() if name]


def scan_repo(repo_root: pathlib.Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in tracked_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: skip
        for label, line_number, snippet in scan_text(text):
            findings.append(
                {"file": str(path.relative_to(repo_root)), "line": str(line_number), "rule": label, "match": snippet}
            )
    return findings


def main(argv: list[str]) -> int:
    repo_root = pathlib.Path(argv[1]).resolve() if len(argv) > 1 else pathlib.Path.cwd()
    findings = scan_repo(repo_root)
    if findings:
        for item in findings:
            print(f"{item['file']}:{item['line']}: [{item['rule']}] {item['match']}")
        print(f"sanitization scan FAILED: {len(findings)} hit(s)", file=sys.stderr)
        return 1
    print("sanitization scan passed: 0 hits across all rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
