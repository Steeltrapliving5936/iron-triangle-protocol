"""Controller-agnostic adapter boundary.

Every controller backend implements :class:`BridgeBackend`. The runner and
policy never touch vendor wire formats. Honest capability grading lives in
:class:`CapabilityReport`:

- ``automatic``   — bind/create, acknowledged dispatch, terminal-event read,
                    and state-based resume all work without a human relay;
- ``semi-automatic`` — some steps need an executor-written sentinel or a
                    copy-paste handoff; delivery is not destination-acked;
- ``manual``      — the step (today: reinjecting into the exact originating
                    arbiter window) has no reliable cross-platform API; the
                    bridge only prepares an outbox payload and notification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

CAPABILITY_AUTOMATIC = "automatic"
CAPABILITY_SEMI_AUTOMATIC = "semi-automatic"
CAPABILITY_MANUAL = "manual"


@dataclass(frozen=True)
class Delivery:
    """Three-valued delivery result; ``accepted`` requires destination ack."""

    status: str  # accepted | rejected | unknown
    prompt_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class AbortReceipt:
    """Result of stopping one prompt owned by a run.

    ``aborted`` means the destination confirmed interruption;
    ``already-terminal`` means the exact prompt was no longer active;
    ``unknown`` means the bridge cannot honestly claim that execution stopped.
    """

    status: str  # aborted | already-terminal | unknown
    prompt_id: str
    detail: str | None = None


@dataclass(frozen=True)
class CapabilityReport:
    adapter_id: str
    tier: str  # automatic | semi-automatic | manual
    api_reachable: bool
    models_available: int = 0
    sessions_visible: int = 0
    event_stream_configured: bool = False
    event_stream_available: bool = False
    prompt_statuses: tuple[str, ...] = ()
    prompt_contract_compatible: bool = False
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter_id,
            "capability_tier": self.tier,
            "api_reachable": self.api_reachable,
            "models_available": self.models_available,
            "sessions_visible": self.sessions_visible,
            "event_stream": {
                "configured": self.event_stream_configured,
                "available": self.event_stream_available,
            },
            "prompt_contract": {
                "compatible": self.prompt_contract_compatible,
                "statuses": list(self.prompt_statuses),
            },
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Binding:
    role: str
    adapter: str
    session_id: str
    title: str
    created: bool
    model: str
    thinking: str | None
    permission_mode: str

    def to_json(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "session_id": self.session_id,
            "title": self.title,
            "created": self.created,
            "model": self.model,
            "thinking": self.thinking,
            "permission_mode": self.permission_mode,
        }


@runtime_checkable
class BridgeBackend(Protocol):
    """The controller adapter surface used by the durable runner."""

    adapter_id: str

    def probe(self) -> CapabilityReport:
        """Capability probe: reachability, catalog sizes, event-stream health."""
        ...

    def resolve_model(self, requested: str | None, default: str | None) -> dict[str, Any]:
        """Resolve against the live catalog; ambiguous names fail closed."""
        ...

    def bind_or_create(
        self,
        *,
        role: str,
        sessions: list[dict[str, Any]],
        cwd: Any,
        title: str,
        model: dict[str, Any],
        thinking: str | None,
        permission_mode: str,
        existing: str | None,
    ) -> Binding:
        """Bind an existing window by unambiguous name or create a fresh one."""
        ...

    def baseline(self, session_id: str) -> int:
        """Current summary-sequence baseline for turn-ended fallback."""
        ...

    def observe(self, session_id: str) -> dict[str, Any]:
        """Live session snapshot: busy flag, last_seq, pending_interaction."""
        ...

    def turn_ended(self, session_id: str, offset: int | None) -> bool:
        """Terminal-event read past a durable byte cursor; raises on truncation."""
        ...

    def dispatch(
        self,
        *,
        binding: Binding,
        text: str,
        prompt_id: str,
    ) -> Delivery:
        """Idempotent prompt send; returns three-valued Delivery."""
        ...

    def abort_prompt(self, *, binding: Binding, prompt_id: str) -> AbortReceipt:
        """Stop the exact prompt owned by a run; never infer ownership from busy state."""
        ...
