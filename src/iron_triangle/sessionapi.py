"""Session-API backend (Kimi Code compatible).

Wire format, endpoint paths, and payload shapes are moved verbatim from the
original single-file bridge so the field-proven behavior is unchanged. All
private bindings stay in the runtime config; nothing here hardcodes them.
"""

from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .backend import (
    AbortReceipt,
    CAPABILITY_AUTOMATIC,
    Binding,
    CapabilityReport,
    Delivery,
)
from .errors import BridgeError
from . import i18n
from .prompts import role_system_prompt
from .util import expand_path

# Prompt acknowledgement states this bridge understands well enough to send
# work into. Anything else published by the live OpenAPI document fails the
# contract gate closed before dispatch.
KNOWN_PROMPT_STATUSES = frozenset({"accepted", "running", "queued", "blocked"})


class SessionApiClient:
    """HTTP client for a local session API. Wire-compatible with v0.1."""

    def __init__(self, adapter: dict[str, Any]):
        self.base_url = str(adapter["base_url"]).rstrip("/")
        token_path = expand_path(str(adapter["token_file"]))
        try:
            self.token = token_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise BridgeError(f"configured token file not found: {token_path}") from exc
        if not self.token:
            raise BridgeError("configured token file is empty")

    def request_envelope(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            raise BridgeError(f"session API HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BridgeError(f"session API unavailable or invalid response: {exc}") from exc
        if not isinstance(payload, dict):
            raise BridgeError(f"session API returned a non-object response: {payload!r}")
        return payload

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = self.request_envelope(method, path, body)
        if payload.get("code") != 0:
            raise BridgeError(f"session API rejected request: {payload!r}")
        return payload.get("data")

    def openapi(self) -> dict[str, Any]:
        """Read the runtime's published contract without assuming its API prefix.

        Kimi Code serves the OpenAPI document at the HTTP origin while the
        configured bridge base normally ends in ``/api/v1``.  This read-only
        sensor prevents a runtime upgrade from silently changing delivery
        semantics underneath the bridge again.
        """

        parts = urllib.parse.urlsplit(self.base_url)
        url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/openapi.json", "", ""))
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            raise BridgeError(f"OpenAPI HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BridgeError(f"OpenAPI unavailable or invalid response: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("paths"), dict):
            raise BridgeError("OpenAPI response has no paths object")
        return payload

    def prompt_status_contract(self) -> tuple[str, ...]:
        """Return POST-prompt acknowledgement statuses from the live schema."""

        operation = (
            self.openapi()
            .get("paths", {})
            .get("/api/v1/sessions/{session_id}/prompts", {})
            .get("post")
        )
        if not isinstance(operation, dict):
            raise BridgeError("OpenAPI does not publish the session prompt POST operation")

        statuses: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                properties = value.get("properties")
                if isinstance(properties, dict):
                    status_schema = properties.get("status")
                    if isinstance(status_schema, dict):
                        enum = status_schema.get("enum")
                        if isinstance(enum, list):
                            statuses.update(item for item in enum if isinstance(item, str))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(operation.get("responses", {}))
        if not statuses:
            raise BridgeError("OpenAPI prompt POST response publishes no status enum")
        return tuple(sorted(statuses))

    def models(self) -> list[dict[str, Any]]:
        return list(self.request("GET", "models").get("items", []))

    def sessions(self) -> list[dict[str, Any]]:
        return list(self.request("GET", "sessions").get("items", []))

    def session(self, session_id: str) -> dict[str, Any]:
        return dict(self.request("GET", f"sessions/{urllib.parse.quote(session_id, safe='')}"))

    def create_session(
        self,
        *,
        title: str,
        cwd: pathlib.Path,
        model: str,
        thinking: str | None,
        permission_mode: str,
        system_prompt: str,
    ) -> dict[str, Any]:
        agent_config: dict[str, Any] = {
            "model": model,
            "permission_mode": permission_mode,
            "plan_mode": False,
            "swarm_mode": False,
            "system_prompt": system_prompt,
        }
        if thinking:
            agent_config["thinking"] = thinking
        return dict(
            self.request(
                "POST",
                "sessions",
                {"title": title, "metadata": {"cwd": str(cwd)}, "agent_config": agent_config},
            )
        )

    def prompt(
        self,
        *,
        session_id: str,
        text: str,
        model: str,
        thinking: str | None,
        permission_mode: str,
        prompt_id: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "model": model,
            "permission_mode": permission_mode,
            "plan_mode": False,
            "swarm_mode": False,
            "prompt_id": prompt_id,
        }
        if thinking:
            body["thinking"] = thinking
        return dict(
            self.request(
                "POST",
                f"sessions/{urllib.parse.quote(session_id, safe='')}/prompts",
                body,
            )
        )

    def abort_prompt(self, *, session_id: str, prompt_id: str) -> dict[str, Any]:
        session = urllib.parse.quote(session_id, safe="")
        prompt = urllib.parse.quote(prompt_id, safe="")
        payload = self.request_envelope("POST", f"sessions/{session}/prompts/{prompt}:abort", {})
        if payload.get("code") == 0:
            return dict(payload.get("data") or {})
        # Kimi Code publishes 40903 when the prompt exists but is no longer
        # active, and 40402 after the active/queued record has been retired.
        # Both are idempotent stop success only because the caller supplies an
        # exact session + run-owned prompt id; no generic 404 is accepted.
        if payload.get("code") == 40903 and isinstance(payload.get("data"), dict):
            return dict(payload["data"])
        if payload.get("code") == 40402:
            return {"aborted": False, "reason": "prompt-not-found"}
        raise BridgeError(f"session API rejected abort request: {payload!r}")

    def approvals(self, *, session_id: str) -> list[dict[str, Any]]:
        session = urllib.parse.quote(session_id, safe="")
        result = self.request("GET", f"sessions/{session}/approvals?status=pending")
        return list(dict(result).get("items", []))

    def resolve_approval(
        self,
        *,
        session_id: str,
        approval_id: str,
        decision: str,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        session = urllib.parse.quote(session_id, safe="")
        approval = urllib.parse.quote(approval_id, safe="")
        body: dict[str, Any] = {"decision": decision}
        if feedback:
            body["feedback"] = feedback
        return dict(self.request("POST", f"sessions/{session}/approvals/{approval}", body))


def model_label(item: dict[str, Any]) -> str:
    return str(item.get("model", ""))


def resolve_model(models: list[dict[str, Any]], requested: str | None, default_model: str | None) -> dict[str, Any]:
    query = (requested or default_model or "").strip()
    if not query:
        raise BridgeError("no model specified and no private default configured")
    lowered = query.casefold()

    exact = [
        item
        for item in models
        if lowered in {str(item.get("model", "")).casefold(), str(item.get("display_name", "")).casefold()}
    ]
    if len(exact) == 1:
        return exact[0]

    suffix = [item for item in models if str(item.get("model", "")).casefold().split("/")[-1] == lowered]
    if len(suffix) == 1:
        return suffix[0]

    fuzzy = [
        item
        for item in models
        if lowered in str(item.get("model", "")).casefold() or lowered in str(item.get("display_name", "")).casefold()
    ]
    if len(fuzzy) == 1:
        return fuzzy[0]
    choices = ", ".join(model_label(item) for item in (fuzzy or models))
    if fuzzy:
        raise BridgeError(f"model name is ambiguous: {query}; matches: {choices}")
    raise BridgeError(f"model not available: {query}; available: {choices}")


def resolve_session(sessions: list[dict[str, Any]], requested: str) -> dict[str, Any]:
    query = requested.strip()
    exact = [item for item in sessions if item.get("id") == query or item.get("title") == query]
    if len(exact) == 1:
        return exact[0]
    lowered = query.casefold()
    fuzzy = [item for item in sessions if lowered in str(item.get("title", "")).casefold()]
    if len(fuzzy) == 1:
        return fuzzy[0]
    if fuzzy:
        titles = ", ".join(str(item.get("title", "")) for item in fuzzy)
        raise BridgeError(f"session/window name is ambiguous: {query}; matches: {titles}")
    raise BridgeError(f"session/window not found: {query}")


def default_thinking(model: dict[str, Any], configured: str | None) -> str | None:
    effort = configured or model.get("default_effort")
    supported = model.get("support_efforts") or []
    if effort and supported and effort not in supported:
        raise BridgeError(f"thinking effort {effort!r} is not supported by {model_label(model)}")
    return str(effort) if effort else None


class SessionApiBackend:
    """BridgeBackend over a Kimi-Code-style local session API.

    Capability tier: ``automatic`` — bind/create, destination-acked dispatch,
    terminal-event reads from the durable event stream, and state-based crash
    resume all work without human relay. Reinjecting into the *originating*
    controller window remains out of scope for this backend and stays an open
    question handled by the arbiter outbox.
    """

    adapter_id = "kimi-code"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.adapter = config["adapters"][self.adapter_id]
        self.client = SessionApiClient(self.adapter)
        self._contract_verified = False
        self._contract_refusal: str | None = None

    # -- dispatch contract gate ------------------------------------------------

    def contract_gate(self) -> str | None:
        """Refusal reason for sending work, or ``None`` when verified safe.

        Read-only OpenAPI sensing runs before any dispatch: a runtime that
        publishes unknown prompt acknowledgement states — or whose contract
        cannot be read at all — must not receive prompts whose delivery
        semantics we would have to guess. A verified-compatible contract is
        cached; an incompatible one stays refused for this backend's lifetime;
        a transport-level read failure refuses the current send and retries
        verification on the next dispatch.
        """
        if self._contract_verified:
            return self._contract_refusal
        try:
            statuses = self.client.prompt_status_contract()
        except BridgeError as exc:
            return f"OpenAPI prompt contract could not be verified: {exc}"
        self._contract_verified = True
        unknown = sorted(set(statuses) - KNOWN_PROMPT_STATUSES)
        if unknown or not statuses:
            self._contract_refusal = (
                "OpenAPI publishes unsupported prompt acknowledgement statuses: "
                + (", ".join(unknown) if unknown else "<no status enum>")
            )
        return self._contract_refusal

    # -- capability probe ---------------------------------------------------

    def probe(self) -> CapabilityReport:
        notes: list[str] = []
        api_reachable = True
        models: list[dict[str, Any]] = []
        sessions: list[dict[str, Any]] = []
        prompt_statuses: tuple[str, ...] = ()
        prompt_contract_compatible = False
        try:
            models = self.client.models()
            sessions = self.client.sessions()
            prompt_statuses = self.client.prompt_status_contract()
            known = {"accepted", "running", "queued", "blocked"}
            prompt_contract_compatible = bool(prompt_statuses) and set(prompt_statuses) <= known
            if not prompt_contract_compatible:
                notes.append(
                    "prompt acknowledgement contract contains unsupported statuses: "
                    + ", ".join(prompt_statuses)
                )
        except BridgeError as exc:
            api_reachable = False
            notes.append(str(exc))
        event_dir = self.adapter.get("event_dir")
        configured = bool(event_dir)
        available = bool(event_dir and expand_path(str(event_dir)).is_dir())
        if configured and not available:
            notes.append("event_dir is configured but the directory does not exist")
        if not configured:
            notes.append("event_dir not configured; turn-ended falls back to summary sequence only")
        return CapabilityReport(
            adapter_id=self.adapter_id,
            tier=CAPABILITY_AUTOMATIC,
            api_reachable=api_reachable,
            models_available=len(models),
            sessions_visible=len(sessions),
            event_stream_configured=configured,
            event_stream_available=available,
            prompt_statuses=prompt_statuses,
            prompt_contract_compatible=prompt_contract_compatible,
            notes=notes,
        )

    # -- catalog / binding ----------------------------------------------------

    def resolve_model(self, requested: str | None, default: str | None) -> dict[str, Any]:
        return resolve_model(self.client.models(), requested, default)

    def bind_or_create(
        self,
        *,
        role: str,
        sessions: list[dict[str, Any]],
        cwd: pathlib.Path,
        title: str,
        model: dict[str, Any],
        thinking: str | None,
        permission_mode: str,
        existing: str | None,
        language: str = i18n.DEFAULT_LANGUAGE,
    ) -> Binding:
        if existing:
            session = resolve_session(sessions, existing)
            session_cwd = session.get("metadata", {}).get("cwd")
            if session_cwd and expand_path(str(session_cwd)) != cwd:
                raise BridgeError(f"existing {role} session is bound to a different workspace: {session_cwd}")
            session_id = str(session["id"])
            created = False
        else:
            session = self.client.create_session(
                title=title,
                cwd=cwd,
                model=model_label(model),
                thinking=thinking,
                permission_mode=permission_mode,
                system_prompt=role_system_prompt(role, language),
            )
            session_id = str(session["id"])
            created = True
        return Binding(
            role=role,
            adapter=self.adapter_id,
            session_id=session_id,
            title=str(session.get("title", title)),
            created=created,
            model=model_label(model),
            thinking=thinking,
            permission_mode=permission_mode,
        )

    # -- observation ----------------------------------------------------------

    def baseline(self, session_id: str) -> int:
        return int(self.client.session(session_id).get("last_seq", 0))

    def observe(self, session_id: str) -> dict[str, Any]:
        return self.client.session(session_id)

    def turn_ended(self, session_id: str, offset: int | None) -> bool:
        from . import store

        return store.turn_ended_after(self.config, self.adapter_id, session_id, offset)

    # -- delivery ---------------------------------------------------------------

    def dispatch(self, *, binding: Binding, text: str, prompt_id: str) -> Delivery:
        """Send one prompt. HTTP-level rejection maps to ``rejected``; transport
        failure or timeout maps to ``unknown``. Kimi Code's successful prompt
        contract returns ``running``, ``queued``, or ``blocked`` together with
        a destination prompt id; all three are destination acknowledgements."""
        gate = self.contract_gate()
        if gate is not None:
            return Delivery(status="rejected", prompt_id=prompt_id, detail=f"contract-gate: {gate}")
        try:
            result = self.client.prompt(
                session_id=binding.session_id,
                text=text,
                model=binding.model,
                thinking=binding.thinking,
                permission_mode=binding.permission_mode,
                prompt_id=prompt_id,
            )
        except BridgeError as exc:
            detail = str(exc)
            if detail.startswith("session API HTTP"):
                return Delivery(status="rejected", prompt_id=prompt_id, detail=detail)
            return Delivery(status="unknown", prompt_id=prompt_id, detail=detail)
        remote_status = str(result.get("status", ""))
        destination_prompt_id = str(result.get("prompt_id", prompt_id))
        if remote_status in {"running", "queued", "blocked", "accepted"}:
            return Delivery(
                status="accepted",
                prompt_id=destination_prompt_id,
                detail=f"remote_status={remote_status}",
            )
        return Delivery(
            status="unknown",
            prompt_id=destination_prompt_id,
            detail=f"unrecognized remote_status={remote_status or '<missing>'}",
        )

    def abort_prompt(self, *, binding: Binding, prompt_id: str) -> AbortReceipt:
        try:
            result = self.client.abort_prompt(session_id=binding.session_id, prompt_id=prompt_id)
        except BridgeError as exc:
            return AbortReceipt(status="unknown", prompt_id=prompt_id, detail=str(exc))
        if result.get("aborted") is True:
            return AbortReceipt(status="aborted", prompt_id=prompt_id, detail="destination-confirmed")
        return AbortReceipt(status="already-terminal", prompt_id=prompt_id, detail="destination-reported-not-active")
