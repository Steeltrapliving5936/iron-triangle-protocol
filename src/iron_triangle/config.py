"""Runtime configuration loading, validation, and migration.

The public repository never contains real endpoints, credentials, or private
bindings; those live only in a user-managed runtime config file. This module
owns the versioned shape of that file:

- schema version 1 (legacy, implicit): flat launch_agent_* keys;
- schema version 2 (current): adds ``schema_version`` and a ``supervisor``
  object; legacy keys are migrated automatically.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

from . import CONFIG_SCHEMA_VERSION, i18n
from .errors import BridgeError
from .util import utc_now

VALID_PERMISSION_MODES = {"manual", "auto", "yolo"}
VALID_SUPERVISOR_TARGETS = {"auto", "launchd", "systemd", "windows-task"}


def detect_schema_version(config: dict[str, Any]) -> int:
    version = config.get("schema_version", 1)
    if not isinstance(version, int) or version < 1:
        raise BridgeError(f"config schema_version must be a positive integer, got {version!r}")
    if version > CONFIG_SCHEMA_VERSION:
        raise BridgeError(
            f"config schema_version {version} is newer than this tool supports "
            f"({CONFIG_SCHEMA_VERSION}); upgrade the tool first"
        )
    return version


def migrate_config(config: dict[str, Any], *, from_version: int | None = None) -> tuple[dict[str, Any], list[str]]:
    """Return ``(migrated_config, change_notes)`` at CONFIG_SCHEMA_VERSION.

    Pure function: it never writes files. ``upgrade`` persists the result with
    a timestamped backup next to the source config.
    """
    working = copy.deepcopy(config)
    version = from_version or detect_schema_version(working)
    notes: list[str] = []
    if version < 2:
        supervisor = dict(working.get("supervisor") or {})
        for old_key, new_key in (("launch_agent_label", "label"), ("launch_agent_path", "path")):
            if old_key in working:
                supervisor.setdefault(new_key, working.pop(old_key))
                notes.append(f"moved {old_key} into supervisor.{new_key}")
        supervisor.setdefault("target", "auto")
        working["supervisor"] = supervisor
        working["schema_version"] = 2
        notes.append("set schema_version to 2")
    return working, notes


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BridgeError(message)


def validate_config(config: dict[str, Any]) -> None:
    """Structural validation aligned with schemas/runtime-config.schema.json."""
    _require(isinstance(config, dict), "config root must be a JSON object")
    version = detect_schema_version(config)
    _require(version == CONFIG_SCHEMA_VERSION, f"run `upgrade` first: config schema {version} != {CONFIG_SCHEMA_VERSION}")

    adapters = config.get("adapters")
    _require(isinstance(adapters, dict) and adapters, "config must define a non-empty adapters map")
    for name, adapter in adapters.items():
        _require(isinstance(adapter, dict), f"adapters.{name} must be an object")
        for key in ("base_url", "token_file"):
            _require(bool(adapter.get(key)), f"config missing adapters.{name}.{key}")
        _require(
            isinstance(adapter.get("base_url"), str) and adapter["base_url"].startswith(("http://", "https://")),
            f"adapters.{name}.base_url must be an http(s) URL",
        )

    _require(bool(config.get("state_dir")), "config missing state_dir")

    poll = config.get("poll_interval_seconds", 15)
    _require(isinstance(poll, int) and poll >= 2, "poll_interval_seconds must be an integer >= 2")

    notifications = config.get("notifications", True)
    _require(isinstance(notifications, bool), "notifications must be a boolean")

    language = config.get("language")
    _require(
        language is None or language in i18n.RESPONSE_LANGUAGES,
        f"language must be one of {list(i18n.RESPONSE_LANGUAGES)} when present",
    )

    supervisor = config.get("supervisor", {})
    _require(isinstance(supervisor, dict), "supervisor must be an object when present")
    target = supervisor.get("target", "auto")
    _require(target in VALID_SUPERVISOR_TARGETS, f"supervisor.target must be one of {sorted(VALID_SUPERVISOR_TARGETS)}")
    label = supervisor.get("label")
    _require(label is None or (isinstance(label, str) and label.strip()), "supervisor.label must be a non-empty string when present")


def load_config(path: pathlib.Path) -> dict[str, Any]:
    """Load a config file and return it at the current schema version.

    Legacy configs are migrated in memory only; nothing is written unless the
    ``upgrade`` command runs. Validation always applies to the migrated form.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(f"private runtime config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BridgeError(f"invalid JSON in runtime config: {exc}") from exc
    if not isinstance(raw, dict):
        raise BridgeError("runtime config root must be a JSON object")
    migrated, _notes = migrate_config(raw)
    validate_config(migrated)
    return migrated


def upgrade_config_file(path: pathlib.Path) -> dict[str, Any]:
    """Migrate the config file in place with a timestamped backup."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(f"private runtime config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BridgeError(f"invalid JSON in runtime config: {exc}") from exc
    from_version = detect_schema_version(raw)
    migrated, notes = migrate_config(raw, from_version=from_version)
    validate_config(migrated)
    if from_version == CONFIG_SCHEMA_VERSION:
        return {"path": str(path), "changed": False, "from_version": from_version, "to_version": CONFIG_SCHEMA_VERSION, "notes": []}
    backup = path.with_name(f"{path.name}.bak-{utc_now().replace(':', '')}")
    backup.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.write_text(json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "changed": True, "backup": str(backup), "from_version": from_version, "to_version": CONFIG_SCHEMA_VERSION, "notes": notes}
