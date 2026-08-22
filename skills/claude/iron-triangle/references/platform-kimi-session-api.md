# Platform mapping: session-API runtimes (Kimi Code style)

Wrap vendor-specific endpoints behind a backend boundary; endpoints, payload shapes, account identifiers, and credentials are deployment configuration, never protocol text or repository content.

- `turn_ended(executor)`: parse terminal events from the session event stream past a durable byte cursor; fall back to the session summary sequence when the stream is not configured. Persist the cursor before dispatch; stop fail-closed on truncation.
- `dispatch(role, text)`: check the destination can accept work, send an idempotent prompt with a stable prompt id, and record the destination acknowledgement. HTTP rejection is `rejected`; transport timeout is `unknown` — an escalation condition, never a blind retry.
- `watch(ledger)`: a supervised external watcher with a durable cursor under launchd/systemd; stop on ledger truncation or rewrite.
- `escalate(arbiter)`: write to the arbiter outbox plus an optional desktop notification. Reliable automatic injection into the exact originating controller window has no cross-platform API — **open question**; manual paste from the outbox is the dependable path.

## Runnable bridge

The repository ships a field-proven bridge for this runtime:

```bash
python3 scripts/iron_triangle_bridge.py --config <private-runtime-config> preflight
python3 scripts/iron_triangle_bridge.py --config <private-runtime-config> launch --cwd <workspace> --task '<task>'
python3 scripts/iron_triangle_bridge.py --config <private-runtime-config> install   # supervised relay (launchd)
python3 scripts/iron_triangle_bridge.py --config <private-runtime-config> status --pending
```

`preflight` is read-only. Model and window names resolve against the live catalog; ambiguity fails closed. See `docs/kimi-code-bridge.md` for the full command surface, including `doctor`, `repair`, `uninstall`, and crash recovery via `resume --ack-prompt-id` / `--retry-new`.

## Rotation

Pause dispatch, append the handoff, replace all three role bindings together, reset watcher baselines to recorded cursors, restart and read back the watcher, then send one resume prompt per role.
