# Platform mapping: generic CLI runtimes

- `turn_ended(executor)`: process exit plus a terminal receipt written atomically.
- `dispatch(role, text)`: resume a bound process/session through stdin or a supported resume command, with a stable dispatch identifier.
- `watch(ledger)`: a supervised file watcher with a durable cursor; stop fail-closed on truncation or rewrite.
- `escalate(arbiter)`: notification, queue entry, or a manual handoff file labeled pending until delivered.

Do not use an open pipe alone as proof that a process is alive. Persist heartbeats and terminal state so a restarted watcher resumes from recorded cursors instead of re-deriving them.

## Rotation

Pause dispatch, append the handoff, replace all three bindings together, reset watcher baselines to recorded cursors, read back mappings, then send one resume payload per role.
