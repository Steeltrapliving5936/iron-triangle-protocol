"""Install generated platform skills with deterministic read-back receipts."""

from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import tempfile
from typing import Any

from .errors import BridgeError
from .util import expand_path, utc_now

PLATFORMS = ("codex", "claude", "kimi", "cursor")
LOCAL_BINDING = pathlib.Path("references/local-runtime.md")


def repository_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def source_skill(platform: str) -> pathlib.Path:
    if platform not in PLATFORMS:
        raise BridgeError(f"unsupported skill platform: {platform}")
    path = repository_root() / "skills" / platform / "iron-triangle"
    if not (path / "SKILL.md").is_file():
        raise BridgeError(f"generated {platform} skill is missing: {path}")
    return path


def default_skill_root(platform: str, *, environ: dict[str, str] | None = None, home: pathlib.Path | None = None) -> pathlib.Path:
    env = os.environ if environ is None else environ
    user_home = pathlib.Path.home() if home is None else home
    if platform == "codex":
        base = pathlib.Path(env["CODEX_HOME"]) if env.get("CODEX_HOME") else user_home / ".codex"
        return (base / "skills").resolve()
    if platform == "claude":
        base = pathlib.Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else user_home / ".claude"
        return (base / "skills").resolve()
    if platform == "kimi":
        base = pathlib.Path(env["KIMI_CODE_HOME"]) if env.get("KIMI_CODE_HOME") else user_home / ".kimi-code"
        return (base / "skills").resolve()
    if platform == "cursor":
        return (user_home / ".cursor" / "skills").resolve()
    raise BridgeError(f"unsupported skill platform: {platform}")


def _files(root: pathlib.Path):
    if not root.is_dir():
        return
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if relative == LOCAL_BINDING:
            continue
        yield relative, path


def tree_hash(root: pathlib.Path) -> str | None:
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    for relative, path in _files(root):
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _binding_text(config_path: pathlib.Path | None, bridge_path: pathlib.Path) -> str:
    if config_path is None:
        return (
            "# Local runtime binding\n\n"
            "Status: **unconfigured**. This installed skill contains the portable protocol only. "
            "Automatic cross-application dispatch is unavailable until the installer is rerun with "
            "a private runtime config. Do not substitute screen control.\n"
        )
    return (
        "# Local runtime binding\n\n"
        "Status: **configured by the local installer**. This file is private installation state; "
        "never copy it into the public repository.\n\n"
        "Use this exact argv prefix for every bridge command:\n\n"
        "```text\n"
        f"python3\n{bridge_path}\n--config\n{config_path}\n"
        "```\n\n"
        "For a Kimi Code target, run `preflight` and then `launch`; use `status --pending`, "
        "`approvals`, `resolve-approval`, and `arbiter --decision` for lifecycle operations. "
        "Never use Computer Use, UI clicking, window focus, or typed screen automation as a "
        "dispatch, delivery receipt, approval, stop, or recovery mechanism. If this binding fails, "
        "report degraded mode and fail closed.\n"
    )


def _binding_hash(path: pathlib.Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def skill_status(
    platform: str,
    *,
    target_root: pathlib.Path | None = None,
    config_path: pathlib.Path | None = None,
    bridge_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    source = source_skill(platform)
    root = (target_root or default_skill_root(platform)).resolve()
    target = root / "iron-triangle"
    bridge = (bridge_path or (repository_root() / "scripts" / "iron_triangle_bridge.py")).resolve()
    expected_binding = _binding_text(config_path.resolve() if config_path else None, bridge)
    binding_path = target / LOCAL_BINDING
    actual_binding = binding_path.read_text(encoding="utf-8") if binding_path.is_file() else None
    source_digest = tree_hash(source)
    installed_digest = tree_hash(target)
    return {
        "platform": platform,
        "source": str(source),
        "target": str(target),
        "installed": target.is_dir(),
        "source_hash": source_digest,
        "installed_hash": installed_digest,
        "core_match": bool(source_digest and source_digest == installed_digest),
        "runtime_binding": "configured" if actual_binding and "Status: **configured" in actual_binding else "unconfigured",
        "runtime_binding_match": actual_binding == expected_binding,
        "runtime_binding_hash": _binding_hash(binding_path),
    }


def install_skill(
    platform: str,
    *,
    target_root: pathlib.Path | None = None,
    config_path: pathlib.Path | None = None,
    bridge_path: pathlib.Path | None = None,
    replace: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = source_skill(platform)
    root = (target_root or default_skill_root(platform)).resolve()
    target = root / "iron-triangle"
    bridge = (bridge_path or (repository_root() / "scripts" / "iron_triangle_bridge.py")).resolve()
    config = config_path.resolve() if config_path else None
    if config is not None and not config.is_file():
        raise BridgeError(f"private runtime config not found: {config}")
    before = skill_status(
        platform,
        target_root=root,
        config_path=config,
        bridge_path=bridge,
    )
    if before["core_match"] and before["runtime_binding_match"]:
        return {"changed": False, "dry_run": dry_run, **before}
    if target.exists() and not replace:
        raise BridgeError(
            f"installed {platform} skill differs at {target}; rerun with --replace to create a backup and update it"
        )
    if dry_run:
        return {
            "changed": True,
            "dry_run": True,
            "platform": platform,
            "source": str(source),
            "target": str(target),
            "would_backup": target.exists(),
            "runtime_binding": "configured" if config else "unconfigured",
        }

    root.mkdir(parents=True, exist_ok=True)
    staging_parent = pathlib.Path(tempfile.mkdtemp(prefix=".iron-triangle-install-", dir=root))
    staged = staging_parent / "iron-triangle"
    backup: pathlib.Path | None = None
    try:
        shutil.copytree(source, staged)
        binding_path = staged / LOCAL_BINDING
        binding_path.parent.mkdir(parents=True, exist_ok=True)
        binding_path.write_text(_binding_text(config, bridge), encoding="utf-8")
        if target.exists():
            stamp = utc_now().replace(":", "").replace("+", "_")
            backup = root / f"iron-triangle.backup-{stamp}"
            target.rename(backup)
        try:
            staged.rename(target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                backup.rename(target)
            raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)

    after = skill_status(
        platform,
        target_root=root,
        config_path=config,
        bridge_path=bridge,
    )
    if not after["core_match"] or not after["runtime_binding_match"]:
        raise BridgeError(f"installed {platform} skill failed hash/read-back verification")
    return {"changed": True, "dry_run": False, "backup": str(backup) if backup else None, **after}
