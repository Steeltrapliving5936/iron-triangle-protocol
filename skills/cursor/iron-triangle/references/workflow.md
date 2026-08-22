# Workflow: checklists, mechanisms, closure

## Three-role start checklist

### Arbiter

- Record one goal, the out-of-scope boundary, a measurable acceptance line, and the end-to-end release gate.
- Define destructive/irreversible red lines and required rollback evidence.
- Set budget limits and the events that justify arbiter involvement.
- Pre-decide predictable branches as "if X, then Y".
- Name the ledger and the marker contract.

### Executor

- Read the latest decision, authorized slice, stop conditions, and red lines.
- Choose the smallest reversible slice and its nearest result sensor.
- State the falsifiable claim and receipt before mutation.
- Confirm tests and read-back sensors exist before changing anything.
- Append results; never rewrite prior ledger entries.

### Reviewer

- Read the acceptance line and raw receipts, not the executor's conclusion alone.
- Confirm independent access to rerun tests, recompute hashes, read deployed state, or exercise the real channel.
- Fail closed on missing evidence, exceeded authority, or a red-line contact.
- Emit exactly one column-one marker after each review turn.

## Ten required mechanisms

All ten are required; removing one is a degraded mode and must be disclosed.

1. Single append-only ledger with continuous sequence numbers.
2. Receipts for every claim.
3. Independent reproduction by the reviewer.
4. Fixed column-one escalation markers.
5. Fail closed on the affected line; unrelated authorized work continues.
6. Pre-decision contract written before the arbiter goes offline.
7. No silent second increase of the same guardrail — switch to root-cause diagnosis.
8. Real end-to-end acceptance for milestones.
9. Coordinated window rotation at round boundaries, with role-binding read-back.
10. Arbiter involvement only for exceptions, milestones, and final acceptance.

## Window rotation

1. Stop dispatching new slices.
2. Append the current decision, receipts, blockers, and next owner.
3. Rotate the three role windows together.
4. Update orchestration identifiers atomically; reset watcher cursors to the recorded baseline.
5. Read back all mappings before resuming; mixed old/new bindings stay paused and escalate.

## Incident and honesty norms

- A process violation is recorded as an incident even when the result is harmless. The ledger records what actually happened; "the output looked fine" never upgrades a skipped step into a compliant one.
- An executor who honestly self-reports an error is named and credited in the ledger. Honest failure reports are required closure inputs — penalizing them only teaches windows to hide failures.

## Closure conditions

A round is eligible for closure only when:

- every claimed result has a receipt;
- the reviewer reproduced the critical checks;
- every test is green or each remaining red has an explicit arbiter decision;
- rollback evidence exists for production mutations;
- the real end-to-end probe passed when the milestone affects a user channel;
- the reviewer emitted `ROUND_CLOSURE_PASS:`;
- the arbiter issued final acceptance when the contract requires it.
