# Sanitized Night Autonomy Contract

- Status: template
- Protocol version: `1.0-draft`
- All angle-bracket values must be replaced before use.

## 1. Round identity

```yaml
round_id: <round-id>
goal: <single measurable goal>
authorized_start: <timestamp>
authorized_end: <timestamp>
ledger: <append-only-ledger-reference>
arbiter_binding: <private-runtime-binding>
executor_binding: <private-runtime-binding>
reviewer_binding: <private-runtime-binding>
```

## 2. Roles and budget

- Arbiter: decide only at escalation, milestone, or closure; target `<2%` of total tokens.
- Executor: investigate, implement, test, and deploy within this contract; target `>90%`.
- Reviewer: independently reproduce critical checks and dispatch already-authorized slices.
- Paper protocol: ledger, receipts, red lines, pre-decisions, and watcher state.

Budget limits:

```yaml
total_budget: <amount-and-unit>
arbiter_budget: <amount-and-unit>
executor_budget: <amount-and-unit>
reviewer_budget: <amount-and-unit>
warning_level: <measurable threshold>
hard_stop: <measurable threshold>
```

Reaching the warning level triggers the pre-decided action below. Reaching the hard stop suspends only work that would exceed the budget and emits `NEEDS_ARBITER:`.

## 3. Authorized scope

Allowed:

- <reversible action 1>
- <reversible action 2>
- <focused validation>

Forbidden:

- destructive irreversible action without receipt and rollback path;
- expansion beyond `<scope boundary>`;
- weakening a fail-closed control, evidence field, or safety watermark;
- deployment with red tests unless every red has a separate arbiter decision;
- treating an internal probe as end-to-end acceptance.

## 4. Acceptance line

The round can close only when all are true:

- [ ] `<focused test set>` is green;
- [ ] the reviewer independently reran `<critical checks>`;
- [ ] production changes have a deployment closure, read-back, and rollback reference;
- [ ] `<real user channel probe>` passed when applicable;
- [ ] every remaining red has its own arbiter decision;
- [ ] the reviewer emitted `ROUND_CLOSURE_PASS:`.

## 5. Pre-decided branches

### A. Authorized slice passes independent review

- IF: the executor receipt is complete and the reviewer reproduces every required check.
- THEN: the reviewer dispatches the next authorized slice without waking the arbiter.
- VERIFY: append the review record and delivery receipt.
- LIMIT: one dispatch per reviewed executor turn.

### B. Evidence is missing or differs

- IF: a claim lacks a receipt, a reproduction fails, or read-back differs.
- THEN: suspend that line and emit `NEEDS_ARBITER:` with the smallest decision request.
- VERIFY: preserve both observations in the ledger.
- ELSE: unrelated authorized lines continue.

### C. A red test remains before deployment

- IF: any required test is red and no separate arbiter decision covers it.
- THEN: deployment is forbidden; emit `NEEDS_ARBITER:`.
- VERIFY: attach the failing output and affected scope.

### D. A protective limit is insufficient

- IF: the limit is insufficient for the first time.
- THEN: stay inside `<first adjustment ceiling>` and record the evidence.
- IF: the same limit is insufficient a second time.
- THEN: stop increasing it, switch to root-cause diagnosis, and emit `NEEDS_ARBITER:` if diagnosis exceeds scope.

### E. Executor transport is unavailable

- IF: executor dispatch is unavailable or rejects work.
- THEN: reviewer enters watch-only mode, preserves completed receipts, and probes on `<probe schedule>`.
- LIMIT: no blind duplicate delivery while status is unknown.
- ESCALATE: after `<outage threshold>` or when the critical path is blocked.

### F. Both executor and reviewer are idle

- IF: both are idle for `<idle timeout>` and work remains.
- THEN: the supervised watcher wakes the reviewer with the latest ledger cursor.
- VERIFY: record wake delivery and cursor.

### G. Context/window rotation

- IF: a round boundary is reached or context is stale, slow, or costly.
- THEN: pause dispatch, append the handoff, rotate all three windows, update role bindings together, reset watcher baselines, and read back the mapping.
- LIMIT: no mixed old/new role bindings.

### H. Milestone appears complete

- IF: focused checks pass.
- THEN: run `<end-to-end probe>` before closure.
- IF: only internal probes pass.
- THEN: status remains not accepted.

## 6. Required marker format

Markers start at column one and contain one decision request or closure event:

```text
NEEDS_ARBITER: <ledger-sequence> | <reason> | <decision requested>
ROUND_CLOSURE_PASS: <ledger-sequence> | <scope> | <receipt set>
```

## 7. Morning handoff

Append one handoff entry containing:

- latest arbiter decision;
- completed slices and receipt references;
- independently verified state;
- suspended lines and exact blockers;
- budget used;
- current role bindings by opaque reference;
- ledger and watcher cursors;
- one next owner and action.

Unknown policy choices must be written as **open question**, not filled by assumption.
