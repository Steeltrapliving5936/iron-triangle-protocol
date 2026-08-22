"""Runner: executes policy actions against a backend and the durable store.

This module replaces the inline watcher logic of the v0.1 monolith. The
policy is pure; everything here is I/O orchestration.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from . import i18n, policy, prompts, store
from .backend import BridgeBackend
from .errors import EventStreamTruncated
from .util import exclusive_lock, utc_now


def dispatch_id(run: dict[str, Any], role: str) -> str:
    run["dispatch_counter"] = int(run.get("dispatch_counter", 0)) + 1
    return f"it_{run['run_id'].replace('-', '_')}_{role}_{run['dispatch_counter']}"


def notify(config: dict[str, Any], run: dict[str, Any], kind: str) -> None:
    if not config.get("notifications", True):
        return
    if sys.platform != "darwin":
        return
    import json

    title, message = i18n.notification(i18n.run_language(run), run["run_id"], kind)
    script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)


def observe_role(
    backend: BridgeBackend,
    config: dict[str, Any],
    run: dict[str, Any],
    role: str,
) -> policy.RoleObservation:
    binding = run[role]
    session_id = binding["session_id"]
    try:
        session = backend.observe(session_id)
    except Exception:
        # Transport down: leave the run untouched this pass; watch_once logs it.
        raise
    pending = session.get("pending_interaction")
    if pending in (None, "none"):
        pending = None
    offset = run.get(f"{role}_event_offset")
    truncated = False
    ended = False
    try:
        ended = backend.turn_ended(session_id, offset)
    except EventStreamTruncated:
        truncated = True
    summary_ended = int(session.get("last_seq", 0)) > int(run.get(f"{role}_baseline_seq", 0))
    return policy.RoleObservation(
        busy=bool(session.get("busy")),
        turn_ended=bool(ended or summary_ended),
        truncated=truncated,
        pending_interaction=pending,
    )


def build_policy_input(config: dict[str, Any], run: dict[str, Any], backend: BridgeBackend) -> policy.PolicyInput:
    language = i18n.run_language(run)
    inp = policy.PolicyInput(
        phase=str(run.get("phase", "launching")),
        review_round=int(run.get("review_round", 0)),
        pending_dispatch=run.get("pending_dispatch"),
        language=language,
    )
    if inp.phase == "await-executor":
        inp = policy.PolicyInput(
            phase=inp.phase,
            executor=observe_role(backend, config, run, "executor"),
            reviewer=inp.reviewer,
            review_round=inp.review_round,
            pending_dispatch=inp.pending_dispatch,
            language=language,
        )
    elif inp.phase == "await-reviewer":
        status, record = store.load_decision(config, run["run_id"], inp.review_round)
        if status == "ready" and int(record.get("review_round", -1)) != inp.review_round:
            status = "mismatch"
        inp = policy.PolicyInput(
            phase=inp.phase,
            executor=inp.executor,
            reviewer=observe_role(backend, config, run, "reviewer"),
            review_round=inp.review_round,
            decision_status=status,
            decision=record,
            pending_dispatch=inp.pending_dispatch,
            language=language,
        )
    return inp


def contract_review_round(run: dict[str, Any], text_key: str) -> int:
    """The review round the dispatched text tells its reader to decide on.

    The reviewer contract must reference the round about to start; every other
    dispatch (executor contract, raw messages) carries the current round.
    """
    round_now = int(run.get("review_round", 0))
    return round_now + 1 if text_key == "reviewer-contract" else round_now


def dispatch_text(run: dict[str, Any], action: policy.Dispatch, bridge_path: pathlib.Path, config_path: pathlib.Path) -> str:
    if action.text_key == "executor-contract":
        return prompts.executor_prompt(run)
    if action.text_key == "reviewer-contract":
        # The reviewer contract must reference the round about to start.
        bumped = dict(run)
        bumped["review_round"] = contract_review_round(run, action.text_key)
        return prompts.reviewer_prompt(bumped, bridge_path, config_path)
    return action.literal


def execute_actions(
    *,
    config: dict[str, Any],
    config_path: pathlib.Path,
    bridge_path: pathlib.Path,
    run: dict[str, Any],
    backend: BridgeBackend,
    actions: list[Any],
    expected_phase: str | None = None,
) -> None:
    """Apply a policy action list to the durable run record in place."""
    for action in actions:
        if isinstance(action, policy.Dispatch):
            role = action.role
            baseline = backend.baseline(run[role]["session_id"])
            offset = store.event_stream_offset(config, backend.adapter_id, run[role]["session_id"])
            prompt_id = dispatch_id(run, role)
            run["pending_dispatch"] = {
                "role": role,
                "prompt_id": prompt_id,
                "baseline_seq": baseline,
                "event_offset": offset,
                # Persist the round the sent text references so a manual ack
                # can reconcile durable state with what actually went out.
                "contract_review_round": contract_review_round(run, action.text_key),
                "recorded_at": utc_now(),
            }
            delivery = backend.dispatch(
                binding=_binding_from(run[role]),
                text=dispatch_text(run, action, bridge_path, config_path),
                prompt_id=prompt_id,
            )
            post = policy.apply_delivery(_snapshot_input(config, run, backend), role, delivery.status, expected_phase or f"await-{role}")
            if delivery.status == policy.DELIVERY_ACCEPTED:
                run["pending_dispatch"] = None
                run["last_delivery"] = {
                    "role": role,
                    "prompt_id": delivery.prompt_id or prompt_id,
                    "accepted_at": utc_now(),
                    "status": "accepted",
                }
                run[f"{role}_baseline_seq"] = baseline
                run[f"{role}_event_offset"] = offset
                run["last_progress_at"] = utc_now()
                store.run_event(config, run["run_id"], "dispatch_accepted", role=role, prompt_id=prompt_id)
                execute_actions(
                    config=config,
                    config_path=config_path,
                    bridge_path=bridge_path,
                    run=run,
                    backend=backend,
                    actions=post,
                )
            else:
                # Delivery did not reach the destination: apply the fail-closed
                # post-actions and abort the rest of the queue so a stale
                # follow-up Transition cannot overwrite the suspension.
                kind = "dispatch_unknown" if delivery.status == policy.DELIVERY_UNKNOWN else "dispatch_rejected"
                store.run_event(config, run["run_id"], kind, role=role, detail=delivery.detail)
                execute_actions(
                    config=config,
                    config_path=config_path,
                    bridge_path=bridge_path,
                    run=run,
                    backend=backend,
                    actions=post,
                )
                return
        elif isinstance(action, policy.Transition):
            for key, value in action.extra.items():
                if key == "round_next":
                    run["round"] = int(run.get("round", 1)) + 1
                else:
                    run[key] = value
            run["phase"] = action.phase
        elif isinstance(action, policy.Outbox):
            store.write_outbox(config, run, action.kind, action.message)
            notify(config, run, action.kind)
        elif isinstance(action, policy.LedgerAppend):
            store.append_ledger(config, run["run_id"], action.text)


def _binding_from(record: dict[str, Any]):
    from .backend import Binding

    return Binding(
        role=record.get("role", ""),
        adapter=record.get("adapter", ""),
        session_id=record["session_id"],
        title=record.get("title", ""),
        created=bool(record.get("created")),
        model=record.get("model", ""),
        thinking=record.get("thinking"),
        permission_mode=record.get("permission_mode", "auto"),
    )


def _snapshot_input(config: dict[str, Any], run: dict[str, Any], backend: BridgeBackend) -> policy.PolicyInput:
    return policy.PolicyInput(phase=str(run.get("phase")), review_round=int(run.get("review_round", 0)))


def step_run(
    *,
    config: dict[str, Any],
    config_path: pathlib.Path,
    bridge_path: pathlib.Path,
    run: dict[str, Any],
    backend: BridgeBackend,
    idle_limit_seconds: float | None = None,
) -> bool:
    """One watcher pass over one run. Returns True when state changed."""
    before = (run.get("phase"), run.get("review_round"), run.get("round"))
    inp = build_policy_input(config, run, backend)
    actions = policy.decide(inp)
    execute_actions(
        config=config,
        config_path=config_path,
        bridge_path=bridge_path,
        run=run,
        backend=backend,
        actions=actions,
    )

    if not actions and idle_limit_seconds is not None and run.get("phase") in policy.ACTIVE_PHASES:
        last = run.get("last_progress_at")
        if last:
            try:
                idle = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
            except ValueError:
                idle = None
            wake = policy.heartbeat(inp, idle, idle_limit_seconds, wake_sent=bool(run.get("wake_sent")))
            if wake:
                run["wake_sent"] = True
                execute_actions(
                    config=config,
                    config_path=config_path,
                    bridge_path=bridge_path,
                    run=run,
                    backend=backend,
                    actions=wake,
                    expected_phase="await-reviewer",
                )

    after = (run.get("phase"), run.get("review_round"), run.get("round"))
    return before != after


def watch_once(
    config: dict[str, Any],
    config_path: pathlib.Path,
    bridge_path: pathlib.Path,
    backend: BridgeBackend | None = None,
    idle_limit_seconds: float | None = None,
) -> int:
    if backend is None:
        from .sessionapi import SessionApiBackend

        backend = SessionApiBackend(config)
    changed_count = 0
    for candidate in store.iter_runs(config):
        phase = candidate.get("phase")
        if phase not in policy.ACTIVE_PHASES and not candidate.get("pending_dispatch"):
            continue
        lock = store.run_dir(config, candidate["run_id"]) / "run.lock"
        with exclusive_lock(lock):
            run = store.load_run(config, candidate["run_id"])
            try:
                changed = step_run(
                    config=config,
                    config_path=config_path,
                    bridge_path=bridge_path,
                    run=run,
                    backend=backend,
                    idle_limit_seconds=idle_limit_seconds,
                )
            except EventStreamTruncated as exc:
                # Fail closed at the runner level too, in case observation
                # raised outside the policy path.
                message = str(exc)
                store.append_ledger(
                    config,
                    run["run_id"],
                    f"NEEDS_ARBITER: open | {message} | inspect event stream and choose next action",
                )
                run["phase"] = "suspended"
                run["suspension_reason"] = "event-stream-truncation"
                run["arbiter_reason"] = message
                store.write_outbox(config, run, "NEEDS_ARBITER", message)
                store.save_run(config, run)
                changed_count += 1
                continue
            except Exception as exc:
                store.run_event(config, run["run_id"], "watch_error", error=repr(exc))
                continue
            if changed:
                store.save_run(config, run)
                changed_count += 1
    return changed_count


def idle_limit_from_config(config: dict[str, Any]) -> float | None:
    value = config.get("idle_wake_seconds")
    if value is None:
        return None
    try:
        limit = float(value)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None
