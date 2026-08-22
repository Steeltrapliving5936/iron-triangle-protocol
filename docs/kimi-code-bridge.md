# Codex → Kimi Code Bridge

This adapter lets the current control window create or reuse two Kimi Code sessions, select any model alias exposed by the local session API, dispatch the executor, and hand the completed turn to an independent reviewer through a supervised relay.

v0.2 keeps the field-proven wire behavior and every v0.1 command; the implementation now lives in `src/iron_triangle/` behind a controller-agnostic policy state machine and adapter boundary (`backend.py`). The entry shim `scripts/iron_triangle_bridge.py` stays the documented interface.

## Capability tier (honest grading)

This backend is **automatic** for its own scope: bind/create, destination-acknowledged dispatch, terminal-event reads from a durable event stream, and state-based crash resume all work without human relay. Reinjecting payloads into the *originating controller* window has no reliable cross-platform API — **open question**; the shipped path is the arbiter outbox plus an optional desktop notification (`NEEDS_ARBITER` / `ROUND_CLOSURE_PASS` entries under `<state_dir>/arbiter-outbox.jsonl`).

## One-line intent

```text
铁三角：<task>
```

The window receiving that phrase is the arbiter. Model brands do not determine the arbiter. Explicit app, window, model, and effort names in the same request override private defaults. If the phrase contains no task, the controller asks only for the missing task.

## Private configuration

Copy [`runtime-config.example.json`](../examples/runtime-config.example.json) outside the repository and replace every placeholder. Endpoints, credentials, local paths, event-stream locations, model defaults, and role/session bindings belong only in that private file. The file is versioned (`schema_version: 2`, contract in [`schemas/runtime-config.schema.json`](../schemas/runtime-config.schema.json)).

```bash
python3 scripts/iron_triangle_bridge.py \
  --config <private-runtime-config> preflight
```

`preflight` is read-only: API reachability, catalog sizes, terminal-event stream health, and resolution of the configured default executor and reviewer.

## Launch

```bash
python3 scripts/iron_triangle_bridge.py \
  --config <private-runtime-config> launch \
  --cwd <task-workspace> \
  --task '<authorized-task>'
```

Override either role per task with `--executor-model` / `--reviewer-model` (model id or unique display name; resolved against the live catalog, ambiguity fails closed) and `--executor-thinking` / `--reviewer-thinking`. Reuse named existing windows with `--executor-session` / `--reviewer-session`; ambiguous names fail closed printing the matches, and executor/reviewer can never share one window. `--dry-run` prints the plan without side effects.

New role windows are named deterministically from the task's first line (`[IT EXEC] …` / `[IT REVIEW] …`, localized prefixes under `zh-CN`) unless overridden with `--title`, or per-role `--executor-title` / `--reviewer-title`.

### Narration language

Language is automatic for users: the arbiter determines one `response_language` per run — an explicit user language requirement wins, otherwise the task's dominant script (the bridge auto-detects zh-CN / en / ja / ko / ru and defaults to en) — and passes it once. Both role windows inherit it jointly and never re-judge separately; `--language` on `launch` (or `"language"` in the private config) remains as an explicit override or test interface.

Catalog-backed languages (`en`, `zh-CN`) localize window titles, role system prompts, the executor and reviewer contracts, ledger narration values, desktop notification summaries, and arbiter closure summaries. Any other recognized response language keeps English machine fields and role labels while both contracts gain an explicit directive to write natural-language replies in that language. A mid-run switch is registered by the arbiter (`arbiter --decision continue --language <code>`), recorded in the ledger, and applies to both roles together.

Machine protocol fields — run ids, ledger entry headers and field labels, reviewer decision commands, and the top-level `NEEDS_ARBITER` / `ROUND_CLOSURE_PASS` markers — are identical in every language, and the `en` path is byte-identical to v0.2. Localizing the native UI of the target app itself is an **open question** outside runtime control.

## Durable relay

```bash
python3 scripts/iron_triangle_bridge.py --config <private-runtime-config> install
```

Installs the watcher under **launchd** (macOS, applied for real as in v0.1). Other targets are generation/dry-run only until exercised against the real platform (**experimental**):

```bash
python3 scripts/iron_triangle_bridge.py --config <private-runtime-config> install --dry-run --target systemd
python3 scripts/iron_triangle_bridge.py --config <private-runtime-config> install --dry-run --target windows-task
```

The watcher persists run state, delivery identifiers, terminal-event byte cursors, ledger entries, and reviewer decisions outside model context. It dispatches the reviewer only after a new `turn.ended` event (session-summary sequence as fallback). Fail-closed behaviors, each covered by tests:

| Condition | Behavior |
|---|---|
| duplicate / replayed turn-ended | no second dispatch |
| event-stream truncation | run suspended, arbiter outbox entry |
| transport timeout on dispatch | `transport-unknown`; never blind-retried |
| HTTP rejection by destination | line suspended, outbox entry |
| process restart with unresolved dispatch | escalates instead of resending |
| reviewer ends without valid decision | suspends line into `await-arbiter` |
| dual idle beyond `idle_wake_seconds` (optional, default off) | one reviewer wake |

Inspect and hand-hold runs with:

```bash
python3 scripts/iron_triangle_bridge.py --config <private-runtime-config> status --pending
```

After inspecting a closure receipt, the current controller records final acceptance:

```bash
python3 scripts/iron_triangle_bridge.py --config <private-runtime-config> arbiter \
  --run-id <run-id> --decision accept
```

For `NEEDS_ARBITER`, the same command supports `--decision continue --message-file <authorized-next-slice>` or `--decision stop`.

## Crash recovery

When a dispatch state is unknown (crash between send and record, or transport timeout), verify the truth in the target app, then tell the bridge explicitly:

```bash
# the prompt WAS delivered:
... resume --run-id <run-id> --ack-prompt-id <prompt-id>
# the prompt was NOT delivered; authorize a replacement:
... resume --run-id <run-id> --retry-new
```

Both append a ledger receipt of the human verification; nothing auto-resends.

## Product lifecycle commands

| Command | Purpose |
|---|---|
| `doctor` | offline health checks (Python, config schema, state dir writability, event stream, supervisor target); `--live` adds network probes |
| `repair` | idempotent: ensure state dirs, prune stale temp files, re-render service-definition reference into `<state_dir>/service/`, flag ledger anomalies without touching them |
| `upgrade` | migrate the runtime config to the current schema with a timestamped backup |
| `version` | tool version, config schema version, Python, platform |
| `uninstall [--dry-run]` | reverse of `install` (real apply on launchd only) |

## Security and authority

- The repository contains no endpoint, credential, private session binding, or organization path; CI enforces the scan.
- The bridge sends only the task authorized by the user and does not widen deployment, destructive-action, or external-communication permissions.
- Existing windows are reused only when the user identifies them or a private binding does so unambiguously.
- A transport timeout is an explicit unknown state, never a retryable failure.
