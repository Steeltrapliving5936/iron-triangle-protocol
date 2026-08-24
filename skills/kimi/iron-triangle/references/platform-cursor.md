# Platform mapping: interactive windows (Cursor style)

Status: **experimental**. Interactive windows may expose no stable session API, so this mapping is honest about what stays manual.

- `turn_ended(executor)`: use an exported completion event if available; otherwise require an atomic sentinel file written by the executor at turn end.
- `dispatch(role, text)`: use a supported native session/task API when available. Otherwise produce a copy-ready manual-paste payload for the user. The agent must not focus the bound window, click it, or insert text through UI automation; a prepared payload remains `accepted: false` until the destination acknowledges.
- `watch(ledger)`: an external file watcher with a durable cursor, under an OS supervisor for unattended runs.
- `escalate(arbiter)`: raise an OS notification and place the arbiter payload on a controlled handoff surface.

Whether Cursor exposes a resumable session API suitable for acknowledged dispatch remains an **open question** until verified against official documentation.

## Rotation

Pause dispatch, append the handoff, replace all three bindings together, reset watcher baselines to recorded cursors, read back mappings, then prepare one resume payload per role (manual paste expected).
