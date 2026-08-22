#!/usr/bin/env python3
"""Validate skill directories against the Agent Skills open specification.

Implements the checks from https://agentskills.io/specification with the
standard library only (a constrained YAML-subset parser for frontmatter):

- required ``name``: 1-64 chars, lowercase alnum + hyphens, no leading,
  trailing, or consecutive hyphens, and equal to the parent directory name;
- required ``description``: 1-1024 chars;
- optional ``license`` (string), ``compatibility`` (<=500 chars),
  ``metadata`` (string-to-string map), ``allowed-tools`` (string);
- body non-empty; body >= 500 lines produces a warning;
- relative file references in the body resolve inside the skill directory.

Usage:
    python3 scripts/validate_skill.py <skill-dir> [<skill-dir> ...]

Exit 0 when every skill passes; exit 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KNOWN_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
LINK_PATTERN = re.compile(r"\]\(([^)#]+)\)")
BACKTICK_PATH_PATTERN = re.compile(r"`((?:references|assets|scripts)/[A-Za-z0-9._/-]+)`")


def parse_frontmatter(text: str) -> tuple[dict[str, object], list[str]]:
    """Parse the YAML subset used by our skills; returns (data, errors)."""
    errors: list[str] = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, ["missing YAML frontmatter"]
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, ["unterminated YAML frontmatter"]

    data: dict[str, object] = {}
    key: str | None = None
    nested_key: str | None = None
    block_mode: str | None = None
    block_lines: list[str] = []

    def flush_block() -> None:
        nonlocal block_mode, block_lines
        if key is None or block_mode is None:
            return
        if block_mode.startswith(">"):
            data[key] = " ".join(part.strip() for part in block_lines)
        else:
            data[key] = "\n".join(block_lines)
        block_mode = None
        block_lines = []

    for raw in lines[1:end]:
        if not raw.strip():
            continue
        indented = raw[:1].isspace()
        if indented and block_mode is not None:
            block_lines.append(raw.strip())
            continue
        if indented and key is not None:
            stripped = raw.strip()
            if ":" in stripped and nested_key is not None:
                sub_key, _, sub_value = stripped.partition(":")
                current = data.get(key)
                if isinstance(current, dict):
                    current[sub_key.strip()] = sub_value.strip().strip('"')
                continue
            # continuation of a plain scalar we cannot handle
            errors.append(f"unsupported indented line: {raw.strip()!r}")
            continue
        flush_block()
        nested_key = None
        stripped = raw.strip()
        if ":" not in stripped:
            errors.append(f"malformed frontmatter line: {stripped!r}")
            continue
        name, _, value = stripped.partition(":")
        name = name.strip()
        value = value.strip()
        key = name
        if value in {">-", ">", "|-", "|"}:
            block_mode = value
            block_lines = []
            data[name] = ""
        elif value == "":
            data[name] = {}
            nested_key = name
        else:
            data[name] = value.strip("'\"")

    flush_block()

    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        data["metadata"] = {str(k): str(v) for k, v in metadata.items()}
    return data, errors


def validate_skill(skill_dir: pathlib.Path) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return {"skill": str(skill_dir), "ok": False, "errors": ["SKILL.md not found"], "warnings": []}
    text = skill_md.read_text(encoding="utf-8")
    data, parse_errors = parse_frontmatter(text)
    errors.extend(parse_errors)

    name = data.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        errors.append(f"name must match {NAME_PATTERN.pattern}, got {name!r}")
    elif len(name) > 64:
        errors.append("name exceeds 64 characters")
    elif name != skill_dir.resolve().name:
        errors.append(f"name {name!r} must match the parent directory name {skill_dir.resolve().name!r}")

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("description is required and must be non-empty")
    elif len(description) > 1024:
        errors.append(f"description exceeds 1024 characters ({len(description)})")

    compatibility = data.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str) or not compatibility.strip():
            errors.append("compatibility must be a non-empty string when present")
        elif len(compatibility) > 500:
            errors.append("compatibility exceeds 500 characters")

    metadata = data.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("metadata must be a string-to-string map")

    allowed_tools = data.get("allowed-tools")
    if allowed_tools is not None and not isinstance(allowed_tools, str):
        errors.append("allowed-tools must be a space-separated string")

    for unknown in sorted(set(data) - KNOWN_KEYS):
        warnings.append(f"unknown frontmatter key: {unknown}")

    body_start = text.split("---", 2)
    body = body_start[2] if len(body_start) == 3 else ""
    body_lines = [line for line in body.splitlines() if line.strip()]
    if not body_lines:
        errors.append("body is empty")
    elif len(body_lines) >= 500:
        warnings.append(f"body has {len(body_lines)} non-empty lines; keep SKILL.md under 500 (move detail to references/)")

    referenced: set[str] = set()
    for pattern in (LINK_PATTERN, BACKTICK_PATH_PATTERN):
        for candidate in pattern.findall(body):
            candidate = candidate.strip()
            if candidate.startswith(("http://", "https://")):
                continue
            referenced.add(candidate)
    for reference in sorted(referenced):
        target = (skill_dir / reference).resolve()
        # Path.is_relative_to compares path components flavour-aware, so this
        # also holds on Windows backslash paths; a str.startswith check with a
        # hardcoded "/" would flag every reference as an escape there.
        if not target.is_relative_to(skill_dir.resolve()):
            errors.append(f"reference escapes the skill directory: {reference}")
        elif not target.exists():
            errors.append(f"reference does not resolve: {reference}")

    return {"skill": str(skill_dir), "ok": not errors, "errors": errors, "warnings": warnings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skills", nargs="+", help="skill directories to validate")
    args = parser.parse_args(argv)
    reports = [validate_skill(pathlib.Path(skill)) for skill in args.skills]
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0 if all(report["ok"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
