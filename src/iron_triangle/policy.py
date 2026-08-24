"""Pure Iron Triangle run-state policy.

``decide``, ``apply_delivery``, and ``heartbeat`` are pure functions from the
current run snapshot plus fresh observations to an ordered list of actions.
The runner executes those actions against a backend and the durable store;
this module performs no I/O so every fail-closed invariant is unit-testable.

Fail-closed invariants encoded here:

- an unresolved ``pending_dispatch`` (crash between send and save) never
  triggers a blind resend; it escalates to the arbiter outbox;
- event-stream truncation suspends the line instead of re-reading;
- a missing, malformed, or invalid reviewer decision escalates instead of
  guessing;
- delivery states are three-valued: only ``accepted`` counts as delivered,
  ``rejected`` suspends the line, ``unknown`` blocks automatic retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import i18n

PHASES = (
    "launching",
    "await-executor",
    "await-reviewer",
    "await-arbiter",
    "await-final-acceptance",
    "blocked-input",
    "transport-unknown",
    "suspended",
    "complete",
    "stopped",
)

# Phases where human/arbiter attention is required; surfaced by `status --pending`.
PENDING_PHASES = frozenset(
    {"await-arbiter", "await-final-acceptance", "blocked-input", "transport-unknown", "suspended"}
)

ACTIVE_PHASES = frozenset({"await-executor", "await-reviewer"})

DELIVERY_ACCEPTED = "accepted"
DELIVERY_REJECTED = "rejected"
DELIVERY_UNKNOWN = "unknown"


@dataclass(frozen=True)
class RoleObservation:
    busy: bool | None = None
    turn_ended: bool = False
    truncated: bool = False
    pending_interaction: str | None = None


@dataclass(frozen=True)
class PolicyInput:
    phase: str
    executor: RoleObservation = field(default_factory=RoleObservation)
    reviewer: RoleObservation = field(default_factory=RoleObservation)
    review_round: int = 0
    decision_status: str = "absent"  # absent | ready | malformed | mismatch
    decision: dict[str, Any] | None = None
    pending_dispatch: dict[str, Any] | None = None
    language: str = i18n.DEFAULT_LANGUAGE  # response_language; static strings fall back via catalog_for


@dataclass(frozen=True)
class Transition:
    phase: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Dispatch:
    role: str  # "executor" | "reviewer"
    text_key: str  # "executor-contract" | "reviewer-contract" | "raw:<literal>"
    literal: str = ""


@dataclass(frozen=True)
class Outbox:
    kind: str  # NEEDS_ARBITER | ROUND_CLOSURE_PASS
    message: str


@dataclass(frozen=True)
class LedgerAppend:
    text: str


def _text(inp: "PolicyInput", key: str, **kwargs: Any) -> str:
    """Catalog text for the run's response language (English machine-field fallback for others)."""
    return i18n.text(i18n.catalog_for(inp.language), key, **kwargs)


def _escalate(inp: PolicyInput, message: str) -> list[Any]:
    tail = _text(inp, "escalate_tail")
    marker = f"NEEDS_ARBITER: open | {message} | {tail}"
    return [LedgerAppend(marker), Outbox("NEEDS_ARBITER", message), Transition("await-arbiter", {"arbiter_reason": message})]


def decide(inp: PolicyInput) -> list[Any]:
    """Next actions for one watcher pass over an active run."""
    # Terminal state wins over stale migration/crash metadata. A watcher must
    # never reopen a run that already has an accepted completion/stop receipt.
    if inp.phase in {"complete", "stopped"}:
        return []
    if inp.pending_dispatch is not None and inp.phase != "transport-unknown":
        prompt_id = str(inp.pending_dispatch.get("prompt_id", "<unknown>"))
        message = _text(inp, "msg_unresolved_dispatch", prompt_id=prompt_id)
        return [
            Outbox("NEEDS_ARBITER", message),
            Transition("transport-unknown", {"arbiter_reason": message}),
        ]

    if inp.phase == "await-executor":
        return _decide_await_executor(inp)
    if inp.phase == "await-reviewer":
        return _decide_await_reviewer(inp)
    return []


def _blocked(inp: PolicyInput, role: str, pending: str) -> list[Any]:
    message = _text(inp, "msg_blocked_input", role=role, pending=pending)
    return [
        Outbox("NEEDS_ARBITER", message),
        Transition(
            "blocked-input",
            {
                "blocked_role": role,
                "blocked_previous_phase": f"await-{role}",
                "arbiter_reason": message,
            },
        ),
    ]


def _truncated(inp: PolicyInput, role: str) -> list[Any]:
    message = _text(inp, "msg_truncated", role=role)
    return [
        Outbox("NEEDS_ARBITER", message),
        Transition("suspended", {"suspension_reason": "event-stream-truncation", "arbiter_reason": message}),
    ]


def _decide_await_executor(inp: PolicyInput) -> list[Any]:
    ex = inp.executor
    if ex.pending_interaction:
        return _blocked(inp, "executor", ex.pending_interaction)
    if ex.truncated:
        return _truncated(inp, "executor")
    if not ex.busy and ex.turn_ended:
        return [
            Dispatch("reviewer", "reviewer-contract"),
            Transition("await-reviewer", {"review_round": inp.review_round + 1}),
        ]
    return []


def _decide_await_reviewer(inp: PolicyInput) -> list[Any]:
    rv = inp.reviewer
    if rv.pending_interaction:
        return _blocked(inp, "reviewer", rv.pending_interaction)
    if rv.truncated:
        return _truncated(inp, "reviewer")
    if rv.busy or not rv.turn_ended:
        return []

    if inp.decision_status != "ready":
        return _escalate(inp, _text(inp, "msg_no_valid_decision"))
    decision = inp.decision or {}
    action = decision.get("decision")
    message = str(decision.get("message", "")).strip()
    if action == "continue" and message:
        return [
            Dispatch("executor", "raw", literal=message),
            Transition("await-executor", {"round_next": True}),
        ]
    if action == "needs-arbiter":
        return [
            Outbox("NEEDS_ARBITER", message),
            Transition("await-arbiter", {"arbiter_reason": message}),
        ]
    if action == "closure-pass":
        return [
            Outbox("ROUND_CLOSURE_PASS", message),
            Transition("await-final-acceptance", {"arbiter_reason": message}),
        ]
    return _escalate(inp, _text(inp, "msg_no_valid_decision"))


def apply_delivery(inp: PolicyInput, role: str, status: str, expected_phase: str) -> list[Any]:
    """Actions after a dispatch attempt returned ``status``.

    Send success must never impersonate receive: only the destination
    acknowledgement produces ``accepted``.
    """
    if status == DELIVERY_ACCEPTED:
        return [Transition(expected_phase)]
    if status == DELIVERY_REJECTED:
        message = _text(inp, "msg_dispatch_rejected", role=role)
        return [
            Outbox("NEEDS_ARBITER", message),
            Transition("suspended", {"suspension_reason": "dispatch-rejected", "arbiter_reason": message}),
        ]
    message = _text(inp, "msg_dispatch_unknown", role=role)
    return [
        Outbox("NEEDS_ARBITER", message),
        Transition("transport-unknown", {"arbiter_reason": message}),
    ]


def heartbeat(
    inp: PolicyInput,
    idle_seconds: float | None,
    limit_seconds: float | None,
    wake_sent: bool,
) -> list[Any]:
    """Dual-idle wake: when both roles sit idle past the limit, nudge the reviewer once."""
    if limit_seconds is None or idle_seconds is None or wake_sent:
        return []
    if inp.phase not in ACTIVE_PHASES:
        return []
    if idle_seconds < limit_seconds:
        return []
    message = _text(inp, "msg_heartbeat_wake", idle_seconds=idle_seconds)
    return [
        Dispatch("reviewer", "raw", literal=message),
        Outbox("NEEDS_ARBITER", message),
    ]
