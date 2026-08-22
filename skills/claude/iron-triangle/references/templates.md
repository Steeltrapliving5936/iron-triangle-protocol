# Templates

## Ledger entry

```markdown
## R-<sequence> <role> <event> <UTC timestamp>

- Scope: <authorized slice>
- Decision or claim: <one falsifiable statement>
- Evidence: <receipt identifiers or links>
- Result: <pass | fail | suspended>
- Rollback: <verified rollback reference or not-applicable>
- Next: <one owner and action>
```

Sequence numbers increase monotonically. Corrections append a superseding entry; history is never edited.

## Receipt

```yaml
receipt_id: <stable-id>
claim: <falsifiable result>
actor_role: executor
scope: <authorized slice>
observed_at: <timestamp>
checks:
  - method: <test | hash | readback | end-to-end probe>
    target: <generic target>
    result: <pass | fail>
    evidence_ref: <artifact reference>
rollback_ref: <reference or not-applicable>
known_reds: []
```

A receipt describes observed state. It must never turn a failed or absent check into a successful claim.

## Review record

```markdown
- Receipt reviewed: <stable-id>
- Reproduction performed: <exact independent check>
- Observed result: <pass | fail>
- Differences from executor claim: <none or concise facts>
- Authorization/red-line check: <pass | fail>
- End-to-end check: <pass | fail | not-yet-required>
```

## Pre-decision branch

```markdown
### Branch <id>: <observable condition>

- IF: <measurable trigger>
- THEN: <authorized action>
- VERIFY: <receipt and independent check>
- LIMIT: <scope, budget, and attempt ceiling>
- ELSE: <continue | suspend this line | escalate>
```

Cover at minimum: missing evidence, red tests before deployment, rollback failure, budget warning/hard stop, executor transport outage, dual-idle timeout, second guardrail increase, window rotation, and end-to-end closure. Unknown policy choices are **open question**.

## Decision summary block

Mandatory at the end of every executor or reviewer turn. At most 10 lines. This is the arbiter's default intake; it does not replace receipts or independent reproduction.

```markdown
Decision summary
- Conclusion: <one falsifiable line>
- Key figures: <counts, hashes, durations, or none>
- Risks: <list or none>
- Decisions needed: <none | concrete ruling requests>
```

If the block is missing or too thin to rule, fail closed and request a complete summary. Do not treat the summary as evidence, and do not have the arbiter compensate by reading implementation.

## Arbiter closure briefing

Mandatory whenever the reviewer records `closure-pass` or `needs-arbiter`. The arbiter states all six elements side by side — divergence is presented, never flattened:

```markdown
Closure briefing — <run-id> round <n> (<closure-pass | needs-arbiter>)
- Executor claim: <one falsifiable line>
- Reviewer findings: <independent reproduction results>
- Role divergence: <none | concrete differences from the executor claim>
- Arbiter ruling: <continue | stop | accept> — <rationale within the ruling scope>
- Residual risks / open questions: <list or none>
- Next step: <recommended action and owner>
- Continuation authority: <pre-decision <id> covers this scope | waiting for explicit user authorization>
```

The arbiter synthesizes evidence; it is not a third technical reviewer and must not claim to have personally re-run checks. Auto-continuation is allowed only inside the same authorized scope already covered by a pre-decision; after closure, new substantive scope requires a pre-decision or explicit user authorization.
