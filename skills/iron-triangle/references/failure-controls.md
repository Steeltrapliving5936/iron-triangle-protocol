# Failure controls

Seven failure classes observed in the founding field run, each with its required control.

| Failure | Required control |
|---|---|
| Relay appears alive but no review starts | supervised watcher, keep-alive, durable cursor |
| Both workers idle and no one advances | dual-idle timeout and reviewer wake-up |
| Executor API unavailable | reviewer enters watch-only mode, probes on a schedule, preserves completed work in ledger |
| Reviewer only summarizes the executor | independent receipt reproduction (rerun/hash/read-back/real channel) |
| Deployment proceeds with red tests | release only when all tests are green or every red has a separate arbiter decision |
| Context becomes stale, slow, or costly | coordinated boundary rotation and ledger-based recovery |
| Internal probe passes while the user path fails | end-to-end channel probe is the release gate |

Delivery semantics that prevent most relapse:

- A command returning successfully is not delivery. Only a destination acknowledgement counts as accepted.
- A transport timeout produces an explicit unknown state — an escalation condition, never permission to resend blindly.
- A prepared manual handoff is labeled pending until a human confirms it was delivered.
