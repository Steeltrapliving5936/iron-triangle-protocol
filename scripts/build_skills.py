#!/usr/bin/env python3
"""Generate platform skills from the canonical iron-triangle skill source.

Usage:
    python3 scripts/build_skills.py            # regenerate all outputs
    python3 scripts/build_skills.py --check    # verify outputs are up to date

The canonical source lives at ``skills/iron-triangle/``. Each generated skill
at ``skills/<platform>/iron-triangle/`` is a full copy of the canonical tree
plus a platform mapping section appended to ``SKILL.md``, so every generated
skill is self-contained once installed. Outputs are committed; this script is
the only sanctioned way to change them.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "skills" / "iron-triangle"
PLATFORMS = {
    "codex": ("Codex", "platform-codex.md"),
    "claude": ("Claude Code", "platform-claude-code.md"),
    "kimi": ("session-API runtimes (Kimi Code style)", "platform-kimi-session-api.md"),
    "cursor": ("interactive windows (Cursor style)", "platform-cursor.md"),
}

BANNER = "<!-- GENERATED from skills/iron-triangle by scripts/build_skills.py; do not edit directly. -->"


def split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if lines[0].strip() != "---":
        raise SystemExit("canonical SKILL.md must start with YAML frontmatter")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    return "\n".join(lines[: end + 1]), "\n".join(lines[end + 1 :]).lstrip("\n")


def render(platform_key: str, label: str, reference_file: str) -> dict[str, str]:
    source = (CANONICAL / "SKILL.md").read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(source)
    mapping = (CANONICAL / "references" / reference_file).read_text(encoding="utf-8").rstrip()
    # The inline mapping makes the generated skill self-sufficient even when
    # only SKILL.md is loaded; the copied references/ tree stays available too.
    generated = f"{frontmatter}\n{BANNER}\n\n{body.rstrip()}\n\n{mapping}\n"
    files: dict[str, str] = {"SKILL.md": generated}
    for path in sorted(CANONICAL.rglob("*")):
        if path.is_file() and path.name != "SKILL.md":
            relative = path.relative_to(CANONICAL)
            files[str(relative)] = path.read_text(encoding="utf-8")
    return files


def target_root(platform_key: str) -> pathlib.Path:
    return ROOT / "skills" / platform_key / "iron-triangle"


def build(*, check_only: bool) -> int:
    dirty = []
    for platform_key, (label, reference_file) in PLATFORMS.items():
        files = render(platform_key, label, reference_file)
        target = target_root(platform_key)
        if check_only:
            for relative, content in files.items():
                path = target / relative
                if not path.exists() or path.read_text(encoding="utf-8") != content:
                    dirty.append(f"{target.relative_to(ROOT)}/{relative}")
        else:
            if target.exists():
                shutil.rmtree(target)
            for relative, content in files.items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            print(f"generated {target.relative_to(ROOT)} ({len(files)} files)")
    if check_only:
        if dirty:
            print("generated skills are stale; run scripts/build_skills.py:", file=sys.stderr)
            for item in dirty:
                print(f"  {item}", file=sys.stderr)
            return 1
        print("generated skills are up to date")
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify instead of write")
    args = parser.parse_args(argv)
    return build(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
