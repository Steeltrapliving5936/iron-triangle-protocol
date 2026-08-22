"""Shared helpers for the Iron Triangle test suites."""

from __future__ import annotations

import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (str(SRC), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from iron_triangle import store  # noqa: E402
from iron_triangle.backend import Binding, CapabilityReport, Delivery  # noqa: E402


def base_config(tmp: pathlib.Path, **extra) -> dict:
    config = {
        "schema_version": 2,
        "adapters": {
            "kimi-code": {
                "base_url": "http://session-api.invalid/api/v1",
                "token_file": str(tmp / "token"),
                "event_dir": str(tmp / "events"),
                "default_executor_model": "executor-a",
                "default_reviewer_model": "reviewer-b",
                "permission_mode": "auto",
            }
        },
        "state_dir": str(tmp / "state"),
        "poll_interval_seconds": 15,
        "notifications": False,
    }
    config.update(extra)
    return config


class FakeBackend:
    """In-memory BridgeBackend driving the real store/policy stack."""

    adapter_id = "kimi-code"

    def __init__(self, config: dict, fail_mode: str | None = None):
        self.config = config
        self.fail_mode = fail_mode
        self.sessions: dict[str, dict] = {}
        self.dispatches: list[dict] = []
        self.models_catalog = [
            {"model": "executor-a", "display_name": "Executor A", "support_efforts": [], "default_effort": None},
            {"model": "reviewer-b", "display_name": "Reviewer B", "support_efforts": [], "default_effort": None},
        ]

    # -- probe ------------------------------------------------------------------

    def probe(self) -> CapabilityReport:
        event_dir = self.config["adapters"][self.adapter_id].get("event_dir")
        return CapabilityReport(
            adapter_id=self.adapter_id,
            tier="automatic",
            api_reachable=True,
            models_available=len(self.models_catalog),
            sessions_visible=len(self.sessions),
            event_stream_configured=bool(event_dir),
            event_stream_available=bool(event_dir),
        )

    # -- catalog / binding --------------------------------------------------------

    def resolve_model(self, requested: str | None, default: str | None) -> dict:
        # Mirrors sessionapi.resolve_model tiers: exact name/display-name
        # match first, then a unique substring (fuzzy) match.
        query = (requested or default or "").strip()
        lowered = query.casefold()
        matches = [
            m
            for m in self.models_catalog
            if lowered in {str(m["model"]).casefold(), str(m["display_name"]).casefold()}
        ]
        if len(matches) != 1:
            fuzzy = [
                m
                for m in self.models_catalog
                if lowered in str(m["model"]).casefold() or lowered in str(m["display_name"]).casefold()
            ]
            if len(fuzzy) == 1:
                return fuzzy[0]
            raise ValueError(f"model not resolvable: {query!r}")
        return matches[0]

    def bind_or_create(self, *, role, sessions=None, cwd=None, title="", model, thinking=None, permission_mode="auto", existing=None, language="en"):
        if existing:
            session_id = existing
            created = False
        else:
            session_id = f"fake-{role}-{uuid.uuid4().hex[:6]}"
            created = True
        self.sessions[session_id] = {
            "id": session_id,
            "title": title,
            "busy": False,
            "last_seq": 0,
            "pending_interaction": "none",
        }
        return Binding(
            role=role,
            adapter=self.adapter_id,
            session_id=session_id,
            title=title,
            created=created,
            model=model["model"],
            thinking=thinking,
            permission_mode=permission_mode,
        )

    # -- observation -------------------------------------------------------------

    def baseline(self, session_id: str) -> int:
        return int(self.sessions[session_id].get("last_seq", 0))

    def observe(self, session_id: str) -> dict:
        return self.sessions[session_id]

    def turn_ended(self, session_id: str, offset: int | None) -> bool:
        return store.turn_ended_after(self.config, self.adapter_id, session_id, offset)

    # -- delivery ------------------------------------------------------------------

    def dispatch(self, *, binding: Binding, text: str, prompt_id: str) -> Delivery:
        self.dispatches.append({"session_id": binding.session_id, "role": binding.role, "prompt_id": prompt_id, "text": text})
        if self.fail_mode == "rejected":
            return Delivery(status="rejected", prompt_id=prompt_id, detail="HTTP 400")
        if self.fail_mode == "unknown":
            return Delivery(status="unknown", prompt_id=prompt_id, detail="transport timeout")
        self.sessions[binding.session_id]["busy"] = True
        return Delivery(status="accepted", prompt_id=prompt_id)

    # -- test conveniences ------------------------------------------------------

    def write_event(self, session_id: str, event: dict) -> None:
        import json

        event_dir = pathlib.Path(self.config["adapters"][self.adapter_id]["event_dir"])
        event_dir.mkdir(parents=True, exist_ok=True)
        with (event_dir / f"{session_id}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def end_turn(self, session_id: str, *, busy: bool = False) -> None:
        self.sessions[session_id]["busy"] = busy
        self.sessions[session_id]["last_seq"] = int(self.sessions[session_id].get("last_seq", 0)) + 1
        self.write_event(session_id, {"envelope": {"type": "turn.ended", "payload": {"turnId": 0}}})


def make_run(config: dict, backend: FakeBackend, tmp: pathlib.Path, *, task: str = "Bounded test task.", dispatch_now: bool = True) -> dict:
    """Create a run record the way `launch` does, without the CLI layer."""
    from iron_triangle.util import utc_now

    run_id = f"it-test-{uuid.uuid4().hex[:8]}"
    directory = store.run_dir(config, run_id)
    directory.mkdir(parents=True, exist_ok=False)
    executor = backend.bind_or_create(role="executor", cwd=tmp, title="[IT EXEC] t", model=backend.models_catalog[0])
    reviewer = backend.bind_or_create(role="reviewer", cwd=tmp, title="[IT REVIEW] t", model=backend.models_catalog[1])
    run = {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "arbiter": {"binding": "originating-control-window", "delivery": "outbox-and-notification"},
        "cwd": str(tmp),
        "task": task,
        "ledger_path": str(directory / "ledger.md"),
        "executor": dict(executor.to_json(), role="executor"),
        "reviewer": dict(reviewer.to_json(), role="reviewer"),
        "phase": "launching",
        "round": 1,
        "review_round": 0,
        "dispatch_counter": 0,
        "pending_dispatch": None,
        "last_delivery": None,
    }
    store.save_run(config, run)
    if dispatch_now:
        from iron_triangle import policy
        from iron_triangle.runner import execute_actions

        execute_actions(
            config=config,
            config_path=pathlib.Path(config["state_dir"]).parent / "runtime.json",
            bridge_path=ROOT / "scripts" / "iron_triangle_bridge.py",
            run=run,
            backend=backend,
            actions=[policy.Dispatch("executor", "executor-contract")],
            expected_phase="await-executor",
        )
        store.save_run(config, run)
    return run
