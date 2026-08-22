# Pre-decision contract (template)

- Status: template
- Protocol version: 1.0-draft
- All angle-bracket values must be replaced before use.

## Round identity

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

## Budget limits

```yaml
total_budget: <amount-and-unit>
warning_level: <measurable threshold>
hard_stop: <measurable threshold>
```

Reaching the warning level triggers the pre-decided action. Reaching the hard stop suspends only work that would exceed the budget and emits `NEEDS_ARBITER:`.

## Authorized scope

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

## Pre-decided branches

### Branch A: authorized slice passes independent review

- IF: the executor receipt is complete and the reviewer reproduces every required check.
- THEN: the reviewer dispatches the next authorized slice without waking the arbiter.
- VERIFY: append the review record and delivery receipt.
- LIMIT: one dispatch per reviewed executor turn.

### Branch B: evidence is missing or differs

- IF: a claim lacks a receipt, a reproduction fails, or read-back differs.
- THEN: suspend that line and emit `NEEDS_ARBITER:` with the smallest decision request.
- VERIFY: preserve both observations in the ledger.
- ELSE: unrelated authorized lines continue.

### Branch C: a red test remains before deployment

- IF: any required test is red and no separate arbiter decision covers it.
- THEN: deployment is forbidden; emit `NEEDS_ARBITER:`.
- VERIFY: attach the failing output and affected scope.

### Branch D: a protective limit is insufficient

- IF: the limit is insufficient for the first time.
- THEN: stay inside `<first adjustment ceiling>` and record the evidence.
- IF: the same limit is insufficient a second time.
- THEN: stop increasing it, switch to root-cause diagnosis, and emit `NEEDS_ARBITER:` if diagnosis exceeds scope.

### Branch E: executor transport is unavailable

- IF: executor dispatch is unavailable or rejects work.
- THEN: reviewer enters watch-only mode, preserves completed receipts, and probes on `<probe schedule>`.
- LIMIT: no blind duplicate delivery while status is unknown.
- ESCALATE: after `<outage threshold>` or when the critical path is blocked.

### Branch F: both executor and reviewer are idle

- IF: both are idle for `<idle timeout>` and work remains.
- THEN: the supervised watcher wakes the reviewer with the latest ledger cursor.
- VERIFY: record wake delivery and cursor.

### Branch G: context/window rotation

- IF: a round boundary is reached or context is stale, slow, or costly.
- THEN: pause dispatch, append the handoff, rotate all three windows, update role bindings together, reset watcher baselines, and read back the mapping.
- LIMIT: no mixed old/new role bindings.

### Branch H: milestone appears complete

- IF: focused checks pass.
- THEN: run `<end-to-end probe>` before closure.
- IF: only internal probes pass.
- THEN: status remains not accepted.

## Required marker format

```text
NEEDS_ARBITER: <ledger-sequence> | <reason> | <decision requested>
ROUND_CLOSURE_PASS: <ledger-sequence> | <scope> | <receipt set>
```

Unknown policy choices must be written as **open question**, not filled by assumption.
