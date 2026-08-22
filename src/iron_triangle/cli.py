"""Unified product CLI for the Iron Triangle bridge.

Entry points:
- ``scripts/iron_triangle_bridge.py`` (backward-compatible shim);
- ``python3 -m iron_triangle``.

Command surface: preflight, models, sessions, launch, watch-once, daemon,
decide, status, resume, arbiter, install, uninstall, doctor, repair,
upgrade, version. All v0.1 commands keep their output shapes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import uuid
from typing import Any

from . import CONFIG_SCHEMA_VERSION, TOOL_VERSION, config as config_mod, i18n, policy, store, supervisor
from .errors import BridgeError
from .runner import execute_actions, idle_limit_from_config, watch_once
from .sessionapi import SessionApiBackend, default_thinking, model_label
from .util import append_jsonl, atomic_json, exclusive_lock, expand_path, utc_now


def _print_stderr(text: str) -> None:
    _utf8_safe_write(sys.stderr, text)


def _utf8_safe_write(stream: Any, text: str) -> None:
    """Write text to a stream whose codepage may not cover CJK narration.

    Windows consoles default to legacy codepages (cp1252 and friends); when
    the stream's encoding cannot represent the text, reconfigure it to UTF-8
    before writing so nothing is partially emitted or lost."""
    encoding = (getattr(stream, "encoding", None) or "utf-8").replace("-", "").lower()
    if encoding != "utf8":
        try:
            "\u4e2d\u6587".encode(stream.encoding)  # narration may contain CJK
        except UnicodeEncodeError:
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure:
                reconfigure(encoding="utf-8")
    stream.write(text + "\n")
    stream.flush()


def _print_json(value: Any) -> None:
    _utf8_safe_write(sys.stdout, json.dumps(value, ensure_ascii=False, indent=2))


# --- read-only inspection -----------------------------------------------------


def cmd_preflight(args: argparse.Namespace, config: dict[str, Any]) -> None:
    backend = SessionApiBackend(config)
    models = backend.client.models()
    sessions = backend.client.sessions()
    adapter_cfg = config["adapters"][backend.adapter_id]
    executor = backend.resolve_model(None, adapter_cfg.get("default_executor_model"))
    reviewer = backend.resolve_model(None, adapter_cfg.get("default_reviewer_model"))
    event_dir = adapter_cfg.get("event_dir")
    output = {
        "ok": True,
        "adapter": backend.adapter_id,
        "capability_tier": backend.probe().tier,
        "models_available": len(models),
        "sessions_visible": len(sessions),
        "defaults": {
            "executor": model_label(executor),
            "reviewer": model_label(reviewer),
        },
        "state_dir": str(store.state_dir(config)),
        "event_stream": {
            "configured": bool(event_dir),
            "available": bool(event_dir and expand_path(str(event_dir)).is_dir()),
        },
    }
    _print_json(output)


def cmd_models(args: argparse.Namespace, config: dict[str, Any]) -> None:
    items = SessionApiBackend(config).client.models()
    output = [
        {
            "model": item.get("model"),
            "display_name": item.get("display_name"),
            "support_efforts": item.get("support_efforts") or [],
            "default_effort": item.get("default_effort"),
        }
        for item in items
    ]
    _print_json(output)


def cmd_sessions(args: argparse.Namespace, config: dict[str, Any]) -> None:
    items = SessionApiBackend(config).client.sessions()
    output = [
        {"id": item.get("id"), "title": item.get("title"), "busy": item.get("busy")}
        for item in items
        if not args.match or args.match.casefold() in str(item.get("title", "")).casefold()
    ]
    _print_json(output)


def cmd_status(args: argparse.Namespace, config: dict[str, Any]) -> None:
    runs = list(store.iter_runs(config))
    if args.run_id:
        runs = [run for run in runs if run.get("run_id") == args.run_id]
    if args.pending:
        runs = [run for run in runs if run.get("phase") in policy.PENDING_PHASES]
    output = [
        {
            "run_id": run.get("run_id"),
            "phase": run.get("phase"),
            "cwd": run.get("cwd"),
            "executor": {"title": run.get("executor", {}).get("title"), "model": run.get("executor", {}).get("model")},
            "reviewer": {"title": run.get("reviewer", {}).get("title"), "model": run.get("reviewer", {}).get("model")},
            "ledger": run.get("ledger_path"),
            "arbiter_reason": run.get("arbiter_reason"),
            "updated_at": run.get("updated_at"),
        }
        for run in runs
    ]
    _print_json(output)


# --- launch --------------------------------------------------------------------


def cmd_launch(args: argparse.Namespace, config: dict[str, Any], config_path: pathlib.Path) -> None:
    cwd = expand_path(args.cwd)
    if not cwd.is_dir():
        raise BridgeError(f"workspace directory does not exist: {cwd}")
    task = args.task
    if args.task_file:
        task = expand_path(args.task_file).read_text(encoding="utf-8")
    if not task or not task.strip():
        raise BridgeError("task text is required")

    backend = SessionApiBackend(config)
    adapter_cfg = config["adapters"][backend.adapter_id]
    executor_model = backend.resolve_model(args.executor_model, adapter_cfg.get("default_executor_model"))
    reviewer_model = backend.resolve_model(args.reviewer_model, adapter_cfg.get("default_reviewer_model"))
    executor_thinking = default_thinking(executor_model, args.executor_thinking or adapter_cfg.get("default_executor_thinking"))
    reviewer_thinking = default_thinking(reviewer_model, args.reviewer_thinking or adapter_cfg.get("default_reviewer_thinking"))
    permission_mode = args.permission_mode or adapter_cfg.get("permission_mode", "auto")
    if permission_mode not in {"manual", "auto", "yolo"}:
        raise BridgeError("permission mode must be manual, auto, or yolo")
    language = i18n.resolve_run_language(config, getattr(args, "language", None), task)

    title = args.title or task.strip().splitlines()[0][:60]
    executor_title = args.executor_title or i18n.role_title(language, "executor", title)
    reviewer_title = args.reviewer_title or i18n.role_title(language, "reviewer", title)
    plan = {
        "arbiter": "current-window",
        "adapter": backend.adapter_id,
        "language": language,
        "cwd": str(cwd),
        "executor_model": model_label(executor_model),
        "executor_thinking": executor_thinking,
        "reviewer_model": model_label(reviewer_model),
        "reviewer_thinking": reviewer_thinking,
        "executor_session": args.executor_session or "<create-new>",
        "reviewer_session": args.reviewer_session or "<create-new>",
        "executor_title": executor_title,
        "reviewer_title": reviewer_title,
    }
    if args.dry_run:
        _print_json({"dry_run": True, "plan": plan})
        return

    run_id = f"it-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    directory = store.run_dir(config, run_id)
    directory.mkdir(parents=True, exist_ok=False)
    sessions = backend.client.sessions()
    executor_binding = backend.bind_or_create(
        role="executor",
        sessions=sessions,
        cwd=cwd,
        title=executor_title,
        model=executor_model,
        thinking=executor_thinking,
        permission_mode=permission_mode,
        existing=args.executor_session,
        language=language,
    )
    reviewer_binding = backend.bind_or_create(
        role="reviewer",
        sessions=sessions,
        cwd=cwd,
        title=reviewer_title,
        model=reviewer_model,
        thinking=reviewer_thinking,
        permission_mode=permission_mode,
        existing=args.reviewer_session,
        language=language,
    )
    if executor_binding.session_id == reviewer_binding.session_id:
        raise BridgeError("executor and reviewer must use distinct sessions/windows")

    run: dict[str, Any] = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "arbiter": {"binding": "originating-control-window", "delivery": "outbox-and-notification"},
        "language": language,
        "cwd": str(cwd),
        "task": task.strip(),
        "ledger_path": str(directory / "ledger.md"),
        "executor": dict(executor_binding.to_json(), role="executor"),
        "reviewer": dict(reviewer_binding.to_json(), role="reviewer"),
        "phase": "launching",
        "round": 1,
        "review_round": 0,
        "dispatch_counter": 0,
        "pending_dispatch": None,
        "last_delivery": None,
    }
    store.append_ledger(
        config,
        run_id,
        f"# Iron Triangle Ledger — {run_id}\n\n"
        + i18n.text(i18n.catalog_for(language), "ledger_launch", timestamp=utc_now(), task=task.strip()),
    )
    store.save_run(config, run)

    bridge_path = _bridge_entry_path()
    actions = [policy.Dispatch("executor", "executor-contract")]
    try:
        execute_actions(
            config=config,
            config_path=config_path,
            bridge_path=bridge_path,
            run=run,
            backend=backend,
            actions=actions,
            expected_phase="await-executor",
        )
    except BridgeError:
        raise
    if run.get("phase") != "await-executor":
        detail = run.get("arbiter_reason") or "initial executor dispatch did not reach the destination"
        store.save_run(config, run)
        raise BridgeError(detail)
    store.save_run(config, run)
    _print_json(
        {
            "launched": True,
            "run_id": run_id,
            "arbiter": "current-window",
            "executor": {"title": executor_binding.title, "model": executor_binding.model},
            "reviewer": {"title": reviewer_binding.title, "model": reviewer_binding.model},
            "ledger": run["ledger_path"],
            "phase": run["phase"],
        }
    )


def _bridge_entry_path() -> pathlib.Path:
    candidates = [
        pathlib.Path(__file__).resolve().parents[2] / "scripts" / "iron_triangle_bridge.py",
        pathlib.Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None,
    ]
    for candidate in candidates:
        if candidate and candidate.name.startswith("iron_triangle") and candidate.exists():
            return candidate
    return pathlib.Path(__file__).resolve()


# --- watcher -------------------------------------------------------------------


def cmd_watch_once(args: argparse.Namespace, config: dict[str, Any], config_path: pathlib.Path) -> None:
    count = watch_once(
        config,
        config_path,
        _bridge_entry_path(),
        idle_limit_seconds=idle_limit_from_config(config),
    )
    _print_json({"ok": True, "runs_changed": count})


def cmd_daemon(args: argparse.Namespace, config: dict[str, Any], config_path: pathlib.Path) -> None:
    import time

    directory = store.state_dir(config)
    interval = max(2, int(config.get("poll_interval_seconds", 15)))
    with exclusive_lock(directory / "daemon.lock", blocking=False):
        while True:
            try:
                watch_once(
                    config,
                    config_path,
                    _bridge_entry_path(),
                    idle_limit_seconds=idle_limit_from_config(config),
                )
            except Exception as exc:  # daemon boundary: record and survive
                append_jsonl(directory / "daemon-errors.jsonl", {"observed_at": utc_now(), "error": repr(exc)})
            time.sleep(interval)


# --- reviewer decision -----------------------------------------------------------


def cmd_decide(args: argparse.Namespace, config: dict[str, Any]) -> None:
    run = store.load_run(config, args.run_id)
    if run.get("phase") != "await-reviewer":
        raise BridgeError(f"run is not awaiting reviewer: {run.get('phase')}")
    if int(run.get("review_round", 0)) != args.review_round:
        raise BridgeError("review round does not match current run state")
    message = args.message
    if args.message_file:
        message = expand_path(args.message_file).read_text(encoding="utf-8")
    if not message or not message.strip():
        raise BridgeError("decision message is required")
    if args.decision in {"needs-arbiter", "closure-pass"} and not args.ledger_sequence:
        raise BridgeError("ledger sequence is required for escalation or closure")
    record = {
        "run_id": args.run_id,
        "review_round": args.review_round,
        "decision": args.decision,
        "ledger_sequence": args.ledger_sequence,
        "message": message.strip(),
        "recorded_at": utc_now(),
    }
    path = store.decision_file(config, args.run_id, args.review_round)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing == record:
            _print_json({"accepted": True, "idempotent": True, "path": str(path)})
            return
        raise BridgeError("a different decision already exists for this review round")
    atomic_json(path, record)
    store.run_event(config, args.run_id, "review_decision", decision=args.decision, review_round=args.review_round)
    _print_json({"accepted": True, "decision": args.decision, "path": str(path)})


# --- resume / arbiter -------------------------------------------------------------


def cmd_resume(args: argparse.Namespace, config: dict[str, Any]) -> None:
    lock = store.run_dir(config, args.run_id) / "run.lock"
    with exclusive_lock(lock):
        run = store.load_run(config, args.run_id)
        phase = run.get("phase")
        if phase == "blocked-input":
            run["phase"] = run.get("blocked_previous_phase")
            run.pop("blocked_role", None)
            run.pop("blocked_previous_phase", None)
            store.save_run(config, run)
            _print_json({"resumed": True, "run_id": args.run_id, "phase": run["phase"]})
            return
        if phase == "transport-unknown":
            pending = run.get("pending_dispatch") or {}
            if args.ack_prompt_id:
                if pending and pending.get("prompt_id") != args.ack_prompt_id:
                    raise BridgeError(
                        f"pending dispatch prompt_id mismatch: run has {pending.get('prompt_id')!r}"
                    )
                role = pending.get("role") or _role_for_phase(run)
                language = i18n.run_language(run)
                run[f"{role}_baseline_seq"] = int(pending.get("baseline_seq", run.get(f"{role}_baseline_seq", 0)))
                if "event_offset" in pending:
                    run[f"{role}_event_offset"] = pending["event_offset"]
                run["last_delivery"] = {
                    "role": role,
                    "prompt_id": args.ack_prompt_id,
                    "accepted_at": utc_now(),
                    "status": "accepted",
                    "acked_by": "manual-resume",
                }
                run["pending_dispatch"] = None
                run["phase"] = f"await-{role}"
                run["last_progress_at"] = utc_now()
                run.pop("arbiter_reason", None)
                store.append_ledger(
                    config,
                    args.run_id,
                    i18n.text(
                        i18n.catalog_for(language),
                        "ledger_recover_ack",
                        sequence=store.next_ledger_sequence(config, args.run_id),
                        timestamp=utc_now(),
                        prompt_id=args.ack_prompt_id,
                        role=role,
                    ),
                )
                store.save_run(config, run)
                _print_json({"resumed": True, "run_id": args.run_id, "phase": run["phase"], "mode": "ack"})
                return
            if args.retry_new:
                if not pending:
                    raise BridgeError("no pending dispatch to supersede")
                role = pending.get("role") or _role_for_phase(run)
                language = i18n.run_language(run)
                run["pending_dispatch"] = None
                run["superseded_dispatches"] = list(run.get("superseded_dispatches") or []) + [pending]
                run["phase"] = f"await-{role}"
                run.pop("arbiter_reason", None)
                store.append_ledger(
                    config,
                    args.run_id,
                    i18n.text(
                        i18n.catalog_for(language),
                        "ledger_recover_retry",
                        sequence=store.next_ledger_sequence(config, args.run_id),
                        timestamp=utc_now(),
                        prompt_id=pending.get("prompt_id"),
                        role=role,
                    ),
                )
                store.save_run(config, run)
                _print_json({"resumed": True, "run_id": args.run_id, "phase": run["phase"], "mode": "retry"})
                return
            raise BridgeError("transport-unknown requires --ack-prompt-id <prompt-id> or --retry-new after human verification")
        raise BridgeError(f"run is not resumable from this phase: {phase}")


def _role_for_phase(run: dict[str, Any]) -> str:
    if run.get("review_round", 0):
        return "reviewer"
    return "executor"


def cmd_arbiter(args: argparse.Namespace, config: dict[str, Any], config_path: pathlib.Path) -> None:
    message = args.message
    if args.message_file:
        message = expand_path(args.message_file).read_text(encoding="utf-8")
    lock = store.run_dir(config, args.run_id) / "run.lock"
    with exclusive_lock(lock):
        run = store.load_run(config, args.run_id)
        phase = run.get("phase")
        language = i18n.run_language(run)
        sequence = store.next_ledger_sequence(config, args.run_id)
        if args.decision == "accept":
            if phase != "await-final-acceptance":
                raise BridgeError(f"run is not awaiting final acceptance: {phase}")
            final_message = (message or i18n.text(i18n.catalog_for(language), "arbiter_accept_default")).strip()
            store.append_ledger(
                config,
                args.run_id,
                i18n.text(
                    i18n.catalog_for(language),
                    "ledger_final_acceptance",
                    sequence=sequence,
                    timestamp=utc_now(),
                    message=final_message,
                ),
            )
            run["phase"] = "complete"
            run["completed_at"] = utc_now()
            run["arbiter_reason"] = final_message
            store.run_event(config, args.run_id, "arbiter_acceptance", ledger_sequence=f"R-{sequence}")
        elif args.decision == "continue":
            if phase not in {"await-arbiter", "await-final-acceptance"}:
                raise BridgeError(f"run is not awaiting arbiter judgment: {phase}")
            if not message or not message.strip():
                raise BridgeError("continue decision requires an instruction message")
            # A mid-run language switch is registered here so every later
            # dispatch (executor raw messages and reviewer contracts alike)
            # inherits the new response_language together — never one role
            # silently splitting from the other.
            old_language = language
            switch_line = ""
            requested_language = getattr(args, "language", None)
            if requested_language is not None and i18n.normalize_language(requested_language) != old_language:
                run["language"] = i18n.normalize_language(requested_language)
                switch_line = (
                    "\n"
                    + i18n.text(
                        i18n.catalog_for(old_language),
                        "ledger_language_switch",
                        old=old_language,
                        new=run["language"],
                    )
                )
            backend = SessionApiBackend(config)
            actions = [policy.Dispatch("executor", "raw", literal=message.strip())]
            execute_actions(
                config=config,
                config_path=config_path,
                bridge_path=_bridge_entry_path(),
                run=run,
                backend=backend,
                actions=actions,
                expected_phase="await-executor",
            )
            if run.get("phase") != "await-executor":
                store.save_run(config, run)
                raise BridgeError(run.get("arbiter_reason") or "executor dispatch failed")
            prompt_id = (run.get("last_delivery") or {}).get("prompt_id", "<unknown>")
            store.append_ledger(
                config,
                args.run_id,
                i18n.text(
                    i18n.catalog_for(language),
                    "ledger_continuation",
                    sequence=sequence,
                    timestamp=utc_now(),
                    message=message.strip(),
                    prompt_id=prompt_id,
                )
                + switch_line,
            )
            run["round"] = int(run.get("round", 1)) + 1
            run["arbiter_reason"] = None
            store.run_event(config, args.run_id, "arbiter_continue", ledger_sequence=f"R-{sequence}")
        elif args.decision == "stop":
            if phase == "complete":
                raise BridgeError("run is already complete")
            final_message = (message or i18n.text(i18n.catalog_for(language), "arbiter_stop_default")).strip()
            store.append_ledger(
                config,
                args.run_id,
                i18n.text(
                    i18n.catalog_for(language),
                    "ledger_stop",
                    sequence=sequence,
                    timestamp=utc_now(),
                    message=final_message,
                ),
            )
            run["phase"] = "stopped"
            run["arbiter_reason"] = final_message
            store.run_event(config, args.run_id, "arbiter_stop", ledger_sequence=f"R-{sequence}")
        store.save_run(config, run)
    _print_json({"accepted": True, "run_id": args.run_id, "decision": args.decision, "phase": run["phase"]})


# --- product lifecycle: install / uninstall / doctor / repair / upgrade ----------


def cmd_install(args: argparse.Namespace, config: dict[str, Any], config_path: pathlib.Path) -> None:
    defn = supervisor.default_definition(config, config_path, _bridge_entry_path())
    target = supervisor.resolve_target(args.target, config)
    if args.dry_run:
        plan = supervisor.plan_install(target, config, defn)
        _print_json({"dry_run": True, **plan})
        return
    if target != "launchd":
        raise BridgeError(
            f"real installation is implemented for launchd only; target {target} supports generated plans via --dry-run"
        )
    result = supervisor.apply_install_launchd(config, defn)
    _print_json(result)


def cmd_uninstall(args: argparse.Namespace, config: dict[str, Any], config_path: pathlib.Path) -> None:
    defn = supervisor.default_definition(config, config_path, _bridge_entry_path())
    target = supervisor.resolve_target(args.target, config)
    if args.dry_run:
        plan = supervisor.plan_uninstall(target, config, defn)
        _print_json({"dry_run": True, **plan})
        return
    if target != "launchd":
        raise BridgeError(f"real uninstallation is implemented for launchd only; target {target} supports --dry-run plans")
    result = supervisor.apply_uninstall_launchd(config, defn)
    _print_json(result)


def cmd_doctor(args: argparse.Namespace, config_path: pathlib.Path) -> None:
    checks: list[dict[str, str]] = []

    def check(name: str, ok: bool, detail: str, warn: bool = False) -> None:
        status = ("warn" if warn else ("pass" if ok else "fail"))
        checks.append({"name": name, "status": status, "detail": detail})

    minor = sys.version_info
    check("python", (minor.major, minor.minor) >= (3, 9), f"python {minor.major}.{minor.minor}.{minor.micro}")

    config: dict[str, Any] | None = None
    try:
        config = config_mod.load_config(config_path)
        check("config", True, f"loaded at schema v{CONFIG_SCHEMA_VERSION}: {config_path}")
    except BridgeError as exc:
        check("config", False, str(exc))

    if config is not None:
        try:
            state = store.state_dir(config)
            probe_dir = state / "doctor-probe"
            probe_dir.mkdir(parents=True, exist_ok=True)
            probe_dir.rmdir()
            check("state_dir", True, f"writable: {state}")
        except OSError as exc:
            check("state_dir", False, f"not writable: {exc}")

        for adapter_id, adapter_cfg in sorted(config.get("adapters", {}).items()):
            event_dir = adapter_cfg.get("event_dir")
            configured = bool(event_dir)
            available = bool(event_dir and expand_path(str(event_dir)).is_dir())
            check(
                f"event_stream.{adapter_id}",
                available or not configured,
                "configured and present" if available else ("configured but missing" if configured else "not configured; summary-sequence fallback only"),
                warn=not configured,
            )

        target = supervisor.resolve_target(None, config)
        check("supervisor", True, f"native target: {target}")

        if args.live:
            for adapter_id in sorted(config.get("adapters", {})):
                live_config = dict(config)
                live_config["adapters"] = {adapter_id: config["adapters"][adapter_id]}
                try:
                    report = SessionApiBackend(live_config).probe()
                    check(
                        f"adapter.{adapter_id}",
                        report.api_reachable,
                        f"tier={report.tier} models={report.models_available} sessions={report.sessions_visible}"
                        + (("; " + "; ".join(report.notes)) if report.notes else ""),
                    )
                except BridgeError as exc:
                    check(f"adapter.{adapter_id}", False, str(exc))

    ok = all(item["status"] != "fail" for item in checks)
    _print_json(
        {
            "ok": ok,
            "tool_version": TOOL_VERSION,
            "config_schema_version": CONFIG_SCHEMA_VERSION,
            "checks": checks,
        }
    )
    if not ok:
        sys.exit(2)


def cmd_repair(args: argparse.Namespace, config: dict[str, Any], config_path: pathlib.Path) -> None:
    actions: list[str] = []
    state = store.state_dir(config)
    for relative in ("runs",):
        target_dir = state / relative
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
            actions.append(f"created {target_dir}")

    removed = 0
    for pattern_root in (state, state / "runs"):
        if pattern_root.exists():
            for tmp_file in pattern_root.glob("*.tmp"):
                tmp_file.unlink(missing_ok=True)
                removed += 1
    if removed:
        actions.append(f"removed {removed} stale .tmp files")

    broken: list[str] = []
    for run in store.iter_runs(config):
        try:
            path = store.run_dir(config, run["run_id"]) / "ledger.md"
            text = path.read_text(encoding="utf-8")
            sequences = [int(value) for value in re.findall(r"^## R-(\d+)\b", text, flags=re.MULTILINE)]
            if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
                broken.append(run["run_id"])
        except FileNotFoundError:
            broken.append(run["run_id"])
    if broken:
        actions.append("ledger anomalies detected (left untouched, fail-closed): " + ", ".join(broken))

    defn = supervisor.default_definition(config, config_path, _bridge_entry_path())
    target = supervisor.resolve_target(None, config)
    reference_dir = state / "service"
    reference_dir.mkdir(parents=True, exist_ok=True)
    if target == "launchd":
        reference = reference_dir / f"{defn.label}.plist"
        reference.write_bytes(supervisor.render_launchd(defn))
    else:
        reference = reference_dir / f"{defn.label}.service"
        reference.write_text(supervisor.render_systemd(defn), encoding="utf-8")
    actions.append(f"rendered service definition reference: {reference}")

    _print_json({"ok": True, "repaired": bool(actions), "actions": actions})


def cmd_upgrade(args: argparse.Namespace, config_path: pathlib.Path) -> None:
    result = config_mod.upgrade_config_file(config_path)
    _print_json(result)


def cmd_version(args: argparse.Namespace) -> None:
    _print_json(
        {
            "tool_version": TOOL_VERSION,
            "config_schema_version": CONFIG_SCHEMA_VERSION,
            "python": sys.version.split()[0],
            "platform": sys.platform,
        }
    )


# --- parser ------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Iron Triangle bridge and product CLI")
    parser.add_argument("--config", required=True, help="private runtime JSON config")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight")
    sub.add_parser("models")
    sessions = sub.add_parser("sessions")
    sessions.add_argument("--match")

    launch = sub.add_parser("launch")
    launch.add_argument("--task")
    launch.add_argument("--task-file")
    launch.add_argument("--cwd", required=True)
    launch.add_argument("--title")
    launch.add_argument("--executor-title")
    launch.add_argument("--reviewer-title")
    launch.add_argument("--executor-model")
    launch.add_argument("--reviewer-model")
    launch.add_argument("--executor-thinking")
    launch.add_argument("--reviewer-thinking")
    launch.add_argument("--executor-session", help="existing session ID or unique title fragment")
    launch.add_argument("--reviewer-session", help="existing session ID or unique title fragment")
    launch.add_argument("--permission-mode", choices=["manual", "auto", "yolo"])
    launch.add_argument(
        "--language",
        choices=list(i18n.RESPONSE_LANGUAGES),
        help="run response_language (explicit override; default: config, then task-language auto-detection, then en)",
    )
    launch.add_argument("--dry-run", action="store_true")

    sub.add_parser("watch-once")
    sub.add_parser("daemon")

    decide = sub.add_parser("decide")
    decide.add_argument("--run-id", required=True)
    decide.add_argument("--review-round", type=int, required=True)
    decide.add_argument("--decision", choices=["continue", "needs-arbiter", "closure-pass"], required=True)
    decide.add_argument("--ledger-sequence")
    decide.add_argument("--message")
    decide.add_argument("--message-file")

    status = sub.add_parser("status")
    status.add_argument("--run-id")
    status.add_argument("--pending", action="store_true")

    resume = sub.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--ack-prompt-id", help="confirm an unknown-state dispatch was delivered")
    resume.add_argument("--retry-new", action="store_true", help="authorize replacing an undelivered dispatch")

    arbiter = sub.add_parser("arbiter")
    arbiter.add_argument("--run-id", required=True)
    arbiter.add_argument("--decision", choices=["accept", "continue", "stop"], required=True)
    arbiter.add_argument("--message")
    arbiter.add_argument("--message-file")
    arbiter.add_argument(
        "--language",
        choices=list(i18n.RESPONSE_LANGUAGES),
        help="switch the run's response_language for both roles from this decision on",
    )

    install = sub.add_parser("install")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--target", choices=["auto", "launchd", "systemd", "windows-task"])

    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.add_argument("--target", choices=["auto", "launchd", "systemd", "windows-task"])

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--live", action="store_true", help="also probe configured adapters over the network")

    sub.add_parser("repair")

    sub.add_parser("upgrade")

    sub.add_parser("version")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = expand_path(args.config)
    try:
        if args.command == "version":
            cmd_version(args)
            return 0
        if args.command == "upgrade":
            cmd_upgrade(args, config_path)
            return 0
        if args.command == "doctor":
            cmd_doctor(args, config_path)
            return 0
        config = config_mod.load_config(config_path)
        if args.command == "preflight":
            cmd_preflight(args, config)
        elif args.command == "models":
            cmd_models(args, config)
        elif args.command == "sessions":
            cmd_sessions(args, config)
        elif args.command == "launch":
            cmd_launch(args, config, config_path)
        elif args.command == "watch-once":
            cmd_watch_once(args, config, config_path)
        elif args.command == "daemon":
            cmd_daemon(args, config, config_path)
        elif args.command == "decide":
            cmd_decide(args, config)
        elif args.command == "status":
            cmd_status(args, config)
        elif args.command == "resume":
            cmd_resume(args, config)
        elif args.command == "arbiter":
            cmd_arbiter(args, config, config_path)
        elif args.command == "install":
            cmd_install(args, config, config_path)
        elif args.command == "uninstall":
            cmd_uninstall(args, config, config_path)
        elif args.command == "repair":
            cmd_repair(args, config, config_path)
        else:
            parser.error(f"unknown command: {args.command}")
        return 0
    except (BridgeError, OSError, ValueError) as exc:
        _print_stderr(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
