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
    CAPABILITY_AUTOMATIC,
    Binding,
    CapabilityReport,
    Delivery,
)
from .errors import BridgeError
from . import i18n
from .prompts import role_system_prompt
from .util import expand_path


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

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
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
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise BridgeError(f"session API rejected request: {payload!r}")
        return payload.get("data")

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

    # -- capability probe ---------------------------------------------------

    def probe(self) -> CapabilityReport:
        notes: list[str] = []
        api_reachable = True
        models: list[dict[str, Any]] = []
        sessions: list[dict[str, Any]] = []
        try:
            models = self.client.models()
            sessions = self.client.sessions()
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
        failure or timeout maps to ``unknown``; only a 2xx ack is ``accepted``."""
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
        status = result.get("status", "accepted")
        if status != "accepted":
            return Delivery(status="unknown", prompt_id=str(result.get("prompt_id", prompt_id)), detail=f"status={status}")
        return Delivery(status="accepted", prompt_id=str(result.get("prompt_id", prompt_id)))
