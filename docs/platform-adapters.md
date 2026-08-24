# Platform Adapter Guide

This guide maps platform-specific session mechanics onto four stable protocol primitives. It intentionally does not copy private endpoints, local paths, account identifiers, credentials, or model names.

## 1. Interface

The control surface should accept a minimal invocation such as `铁三角：<task>`. The receiving window binds itself as `arbiter`; the adapter resolves executor and reviewer targets from explicit user wording first, then private defaults. Do not make the user restate the role contract that the skill already carries.

```ts
type Role = "arbiter" | "executor" | "reviewer";

type Cursor = string;

type TurnEnd = {
  role: "executor";
  runId: string;
  cursor: Cursor;
  endedAt: string;
  outcome: "completed" | "needs-input" | "failed";
};

type Delivery = {
  accepted: boolean;
  deliveryId?: string;
  observedAt: string;
  detail?: string;
};

type MarkerEvent = {
  cursor: Cursor;
  marker: "NEEDS_ARBITER" | "ROUND_CLOSURE_PASS";
  ledgerSequence: string;
  payload: string;
};

interface IronTriangleAdapter {
  turnEnded(after: Cursor): Promise<TurnEnd | null>;
  dispatch(role: Role, text: string): Promise<Delivery>;
  watchLedger(after: Cursor): AsyncIterable<MarkerEvent>;
  escalate(text: string): Promise<Delivery>;
  stop(runId: string): Promise<Delivery>;
}
```

An adapter **must not** report delivery merely because a command returned successfully. `accepted` means the destination acknowledged the handoff. User-visible receipt, execution completion, and acceptance are separate states.

## 2. Required state

Keep orchestration state outside model context:

```yaml
adapter_version: <version>
role_bindings:
  arbiter: <opaque-binding>
  executor: <opaque-binding>
  reviewer: <opaque-binding>
ledger_cursor: <durable-cursor>
last_executor_turn: <opaque-run-id>
last_delivery:
  reviewer: <delivery-receipt>
  arbiter: <delivery-receipt>
heartbeat_at: <timestamp>
```

Opaque bindings stay in the private runtime configuration. Public repositories store only placeholders or schemas.

## 3. Primitive semantics

### `turnEnded(after)`

Return exactly once for each newly completed executor turn. Persist the cursor before dispatching the reviewer. Completion may come from a native task result, a transcript event stream, a session API, a process exit, or an atomic sentinel file.

Do not infer completion from inactivity alone. Inactivity belongs to the heartbeat path.

### `dispatch(role, text)`

Deliver one idempotent prompt containing:

- ledger sequence and authorized slice;
- artifact/receipt references;
- the exact next action;
- a stable dispatch identifier.

Retry only when delivery is known to have failed. An unknown delivery state is an escalation condition, not permission to duplicate the prompt.

### `watchLedger(after)`

Read append-only changes in order and emit only markers at column one:

```text
NEEDS_ARBITER:
ROUND_CLOSURE_PASS:
```

Persist the last consumed byte offset, record sequence, or event cursor. On truncation or rewrite, stop fail-closed: an append-only invariant has been broken.

### `escalate(text)`

Wake the arbiter through a platform notification or produce a copy-ready manual handoff. Manual paste is a valid and dependable degraded path. Never label a prepared handoff as delivered.

### `stop(runId)`

Cancel only work whose destination prompt/task identifiers are owned by the run. Read back destination-confirmed cancellation or exact-task terminal state before reporting `stopped`. Shutting down the local relay alone is not execution cancellation and remains a suspended/unknown stop state.

## 4. Generic adapter skeleton

```python
class Adapter:
    def on_executor_event(self, event):
        if not event.is_terminal or self.seen(event.cursor):
            return
        self.persist_cursor(event.cursor)
        delivery = self.dispatch("reviewer", self.review_prompt(event))
        self.record_delivery(delivery)

    def on_ledger_append(self, line, cursor):
        if line.startswith("NEEDS_ARBITER:"):
            self.persist_ledger_cursor(cursor)
            self.record_delivery(self.escalate(line))
        elif line.startswith("ROUND_CLOSURE_PASS:"):
            self.persist_ledger_cursor(cursor)
            self.record_delivery(self.escalate(line))

    def heartbeat(self, state):
        if state.executor_idle and state.reviewer_idle and state.idle_limit_reached:
            self.record_delivery(self.dispatch("reviewer", state.wake_prompt))
```

The skeleton is illustrative. Persistence, authentication, concurrency control, exact-prompt cancellation, and retry semantics are platform responsibilities. A UI automation layer is presentation only and cannot satisfy dispatch, stop, approval, or delivery-receipt semantics.

## 5. Codex-style runtime

Use native task/agent status as the preferred `turnEnded` signal when the work stays inside one active task. Use native follow-up messaging for `dispatch` and an explicit reviewer result for the ledger marker.

For cross-session or unattended work:

- keep the ledger and cursor in durable files or a service;
- place heartbeat/watch logic under a system supervisor;
- treat an app notification or a prepared manual message as `escalate`;
- read back role bindings after rotation before new work starts.

A background process launched from a transient command tool is not a durable watcher.

## 6. Claude Code-style runtime

Prefer native agent completion or hook/transcript completion events for `turnEnded`. Dispatch through the platform’s supported agent/task messaging or a resumable session command. Keep the reviewer’s independent reproduction instructions separate from the executor’s report.

Long-lived `watchLedger` and heartbeat logic belong to a supervised external process. Hooks can emit durable events but should not be assumed to remain alive after the parent session exits.

## 7. Session-API runtime (Kimi-like)

Wrap vendor-specific endpoints behind two private methods:

```ts
interface SessionBackend {
  readEvents(binding: string, after: Cursor): Promise<unknown[]>;
  sendPrompt(binding: string, payload: unknown): Promise<Delivery>;
  readBusy(binding: string): Promise<boolean>;
}
```

Mapping:

- `turnEnded` parses a terminal event from `readEvents`;
- `dispatch` first checks whether the destination can accept a prompt, then calls `sendPrompt`;
- `watchLedger` is independent of the session service;
- `escalate` sends to the arbiter binding or prepares a manual payload.

Endpoints, payload shapes, account identifiers, and credentials are deployment configuration—not protocol text. A provider outage places the reviewer in watch-only mode, preserves receipts, and probes availability on the contract schedule.

## 8. Interactive-window runtime (Cursor-like)

An interactive window may not expose a stable session API. Implement an honest semi-automatic adapter:

- `turnEnded`: use an exported completion event if available; otherwise require an atomic sentinel written by the executor;
- `dispatch`: use a supported native session/task API, or return a manual-paste payload for the user;
- `watchLedger`: use an external file watcher with a durable cursor;
- `escalate`: raise an OS notification and place the arbiter payload on a controlled handoff surface.

UI focus, clicking, or text insertion is not an adapter transport. The adapter records a prepared manual payload as `accepted: false` until the destination acknowledges the prompt.

## 9. Generic CLI runtime

- `turnEnded`: process exit plus a terminal receipt written atomically;
- `dispatch`: resume a bound process/session through stdin or a supported resume command;
- `watchLedger`: supervised file watcher;
- `escalate`: notification, queue, or manual handoff file.

Do not use an open pipe alone as proof that a process is alive. Persist heartbeats and terminal state.

## 10. Rotation protocol

Role-binding rotation is an atomic operational change:

1. pause new dispatch;
2. record the ledger cursor and last accepted delivery for each role;
3. create or bind fresh windows;
4. replace all role bindings together;
5. reset watcher baselines to the recorded cursor;
6. restart the supervised watcher;
7. read back bindings, watcher health, and cursor;
8. send one resume payload per role.

If only part of the mapping changes, remain paused and escalate. Dispatching against mixed old/new bindings risks duplicated or lost work.

## 11. Adapter conformance checks

Before unattended use, verify (the session-API bridge automates this list in `tests/test_conformance.py`):

- one executor terminal event produces exactly one reviewer dispatch;
- replaying the same event produces no second dispatch;
- a marker with indentation is ignored, while a column-one marker is emitted;
- ledger truncation stops the watcher;
- dual-idle timeout wakes the reviewer;
- a rejected delivery is recorded as failed, not accepted;
- an unknown delivery state does not trigger blind retry;
- rotated bindings and cursor survive watcher restart;
- manual escalation works when platform dispatch is unavailable.

The best default timeout and a universal receipt schema remain **open questions**.
