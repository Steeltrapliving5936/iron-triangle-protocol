# Platform mapping: Codex

Implement the four primitives with the narrowest native mechanism available.

- `turn_ended(executor)`: native agent/task terminal result, or a durable atomic sentinel written by the executor. Persist its cursor before dispatch.
- `dispatch(role, text)`: native follow-up/task message with a stable dispatch identifier. Record destination acknowledgement; a tool return alone is not delivery.
- `watch(ledger)`: during one active task, consume appended markers directly. For cross-session unattended work use an authorized OS/service supervisor with a durable cursor; a background process launched from a transient command tool is not a durable watcher.
- `escalate(arbiter)`: native task message or notification, or a copy-ready manual handoff labeled pending until delivered.

## Launch behavior

- Treat the trigger phrase as explicit invocation; the receiving window is the arbiter.
- Parse app, window/session, model, and effort assignments from the same user message; explicit assignments win, unspecified roles use private defaults.
- Create fresh executor/reviewer sessions by default; reuse an existing window only when the user names it or a private binding resolves it uniquely. Ambiguous names fail closed and print the matches.
- Resolve model names against the live catalog; never invent an alias or silently pick among fuzzy matches.

## Rotation

Pause dispatch, append the handoff, replace all three role bindings together, reset the watcher baseline to the recorded cursor, read back the mappings, then send one resume prompt per role.
