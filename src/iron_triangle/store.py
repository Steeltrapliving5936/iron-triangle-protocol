"""Durable state: run records, session event streams, ledger, decisions, outbox.

All orchestration state lives outside model context, under the private
``state_dir`` from the runtime config. Writes are atomic or append-only; the
ledger is never rewritten.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Any, Iterator

from .errors import BridgeError, EventStreamTruncated
from .util import atomic_json, append_jsonl, expand_path, utc_now

MARKER_PATTERN = re.compile(r"^(NEEDS_ARBITER|ROUND_CLOSURE_PASS):(.*)$", flags=re.MULTILINE)
LEDGER_SEQUENCE_PATTERN = re.compile(r"^## R-(\d+)\b", flags=re.MULTILINE)


def state_dir(config: dict[str, Any]) -> pathlib.Path:
    return expand_path(config["state_dir"])


def run_dir(config: dict[str, Any], run_id: str) -> pathlib.Path:
    if pathlib.Path(run_id).name != run_id or not run_id:
        raise BridgeError(f"invalid run id: {run_id!r}")
    return state_dir(config) / "runs" / run_id


def run_file(config: dict[str, Any], run_id: str) -> pathlib.Path:
    return run_dir(config, run_id) / "run.json"


def load_run(config: dict[str, Any], run_id: str) -> dict[str, Any]:
    try:
        return json.loads(run_file(config, run_id).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(f"run not found: {run_id}") from exc


def save_run(config: dict[str, Any], run: dict[str, Any]) -> None:
    run["updated_at"] = utc_now()
    atomic_json(run_file(config, run["run_id"]), run)


def run_event(config: dict[str, Any], run_id: str, kind: str, **fields: Any) -> None:
    append_jsonl(run_dir(config, run_id) / "events.jsonl", {"observed_at": utc_now(), "kind": kind, **fields})


def iter_runs(config: dict[str, Any]) -> Iterator[dict[str, Any]]:
    root = state_dir(config) / "runs"
    if not root.exists():
        return
    for path in sorted(root.glob("*/run.json")):
        try:
            yield json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue


def run_dir_from_record(run: dict[str, Any]) -> pathlib.Path:
    return pathlib.Path(run["ledger_path"]).parent


# --- session event streams -------------------------------------------------


def event_stream_path(config: dict[str, Any], adapter_id: str, session_id: str) -> pathlib.Path | None:
    configured = config.get("adapters", {}).get(adapter_id, {}).get("event_dir")
    if not configured:
        return None
    if pathlib.Path(session_id).name != session_id:
        raise BridgeError("invalid session identifier for event stream")
    return expand_path(str(configured)) / f"{session_id}.jsonl"


def event_stream_offset(config: dict[str, Any], adapter_id: str, session_id: str) -> int | None:
    path = event_stream_path(config, adapter_id, session_id)
    if path is None:
        return None
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def turn_ended_after(config: dict[str, Any], adapter_id: str, session_id: str, offset: int | None) -> bool:
    """True when a ``turn.ended`` event appears beyond ``offset``.

    Raises BridgeError when the stream shrank: an append-only invariant was
    broken and the watcher must stop fail-closed.
    """
    path = event_stream_path(config, adapter_id, session_id)
    if path is None or offset is None or not path.exists():
        return False
    try:
        with path.open("rb") as handle:
            current_size = path.stat().st_size
            if current_size < offset:
                raise EventStreamTruncated(f"session event stream was truncated: {session_id}")
            handle.seek(offset)
            for raw_line in handle:
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if event.get("envelope", {}).get("type") == "turn.ended":
                    return True
    except OSError as exc:
        raise BridgeError(f"cannot read session event stream: {exc}") from exc
    return False


# --- ledger ----------------------------------------------------------------


def append_ledger(config: dict[str, Any], run_id: str, text: str) -> None:
    path = run_dir(config, run_id) / "ledger.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n\n")
        handle.flush()
        os.fsync(handle.fileno())


def next_ledger_sequence(config: dict[str, Any], run_id: str) -> int:
    try:
        text = run_dir(config, run_id).joinpath("ledger.md").read_text(encoding="utf-8")
    except FileNotFoundError:
        return 1
    values = [int(value) for value in LEDGER_SEQUENCE_PATTERN.findall(text)]
    return max(values, default=0) + 1


def extract_markers(ledger_text: str) -> list[dict[str, str]]:
    """Column-one protocol markers only; indented or quoted lines are ignored."""
    markers = []
    for line in ledger_text.splitlines():
        match = MARKER_PATTERN.match(line)
        if match:
            markers.append({"marker": match.group(1), "payload": match.group(2).strip()})
    return markers


# --- reviewer decisions ------------------------------------------------------


def decision_file(config: dict[str, Any], run_id: str, review_round: int) -> pathlib.Path:
    return run_dir(config, run_id) / f"review-decision-{review_round}.json"


def load_decision(config: dict[str, Any], run_id: str, review_round: int) -> tuple[str, dict[str, Any] | None]:
    """Return ``(status, record)`` where status is absent|ready|malformed."""
    path = decision_file(config, run_id, review_round)
    if not path.exists():
        return "absent", None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "malformed", None
    if not isinstance(record, dict):
        return "malformed", None
    return "ready", record


# --- arbiter outbox ----------------------------------------------------------


def write_outbox(config: dict[str, Any], run: dict[str, Any], kind: str, message: str) -> None:
    item = {
        "run_id": run["run_id"],
        "kind": kind,
        "message": message,
        "ledger_path": run["ledger_path"],
        "created_at": utc_now(),
    }
    append_jsonl(state_dir(config) / "arbiter-outbox.jsonl", item)
    run_event(config, run["run_id"], "arbiter_outbox", outbox_kind=kind)
