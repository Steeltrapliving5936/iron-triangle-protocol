# Platform mapping: Claude Code

Implement the four primitives with the narrowest native mechanism available.

- `turn_ended(executor)`: native agent/task completion, hook/transcript terminal event, or a durable atomic sentinel. Persist its cursor before dispatch.
- `dispatch(role, text)`: supported agent/task messaging or a resumable session command with a stable dispatch identifier. Record destination acknowledgement; command success alone is not delivery.
- `watch(ledger)`: hooks may emit durable append events, but cross-session unattended watching belongs to an authorized OS/service supervisor with a durable cursor. Do not assume a hook or child process survives the parent session.
- `escalate(arbiter)`: supported agent/session message, notification, or a copy-ready manual handoff labeled pending until delivered.

Keep the reviewer's independent reproduction instructions separate from the executor's report; the reviewer reruns checks personally.

The arbiter being Claude Code does not determine the worker app. For a Kimi Code or other cross-app target, use the configured local runtime plus that target's mapping. Missing automatic transport is a disclosed degraded mode, never permission to control another app's UI.

## Rotation

Pause dispatch, append the handoff, replace all three role bindings together, reset the watcher baseline to the recorded cursor, read back the mappings, then send one resume prompt per role.
