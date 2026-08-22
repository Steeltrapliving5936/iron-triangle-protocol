#!/usr/bin/env python3
"""Release gate: scan git object metadata for desensitization violations.

The file sanitizer only sees working-tree contents; commit author/committer
fields and annotated-tag tagger fields live in git objects and were never
covered — a real name and a `.local` address leaked through them once.
This gate parses the metadata of every commit in the given revision range
plus every annotated tag reachable from the given refs, runs the same
desensitization rules over each identity field, and exits non-zero with a
per-object report when anything trips.

Usage:
    python3 scripts/check_git_metadata.py <range>            # e.g. origin/main..HEAD
    python3 scripts/check_git_metadata.py HEAD --tags        # HEAD plus all tags
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from iron_triangle.sanitizer import scan_text  # noqa: E402


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"git metadata gate: git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _scan(kind: str, ref: str, field: str, value: str) -> list[str]:
    hits = scan_text(value)
    return [f"{kind} {ref} field {field}: [{h[0]}] {h[2]}" for h in hits]


def scan_range(rev_range: str) -> list[str]:
    findings: list[str] = []
    fmt = "%H%x09%an%x09%ae%x09%cn%x09%ce"
    out = _git("log", f"--format={fmt}", rev_range)
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, an, ae, cn, ce = line.split("\t")
        for field, value in (("author_name", an), ("author_email", ae), ("committer_name", cn), ("committer_email", ce)):
            findings.extend(_scan("commit", sha[:9], field, value))
    return findings


def scan_tag(ref: str) -> list[str]:
    findings: list[str] = []
    obj_type = _git("cat-file", "-t", ref).strip()
    if obj_type != "tag":
        return findings
    tag = _git("cat-file", "tag", ref)
    tagger_line = next((ln for ln in tag.splitlines() if ln.startswith("tagger ")), "")
    if not tagger_line:
        findings.append(f"tag {ref}: no tagger line found in tag object")
        return findings
    # tagger format: "Name <email> timestamp"
    identity = tagger_line[len("tagger "):].rsplit(" ", 2)[0]
    name, _, email = identity.partition("<")
    findings.extend(_scan("tag", ref, "tagger_name", name.strip()))
    findings.extend(_scan("tag", ref, "tagger_email", email.strip().rstrip(">")))
    return findings


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    rev_range = argv[1]
    findings = scan_range(rev_range)
    if "--tags" in argv:
        refs = _git("for-each-ref", "--format=%(refname:short)", "refs/tags/").splitlines()
        for ref in refs:
            findings.extend(scan_tag(ref))
    if findings:
        print(f"git metadata gate FAILED: {len(findings)} hit(s)")
        for item in findings:
            print(f"  {item}")
        return 1
    print(f"git metadata gate passed: 0 hits ({rev_range}" + (", tags" if "--tags" in argv else "") + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
