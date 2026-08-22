# Iron Triangle Protocol Specification v1

- Status: generalized public draft
- Evidence base: one four-day production field run
- Normative language: **MUST**, **MUST NOT**, **SHOULD**, and **MAY** indicate requirement strength.

## 1. Purpose / 目的

The protocol coordinates three distinct model roles during long-running AI work while keeping evidence, authority, and recovery state outside any one model window. It is platform-independent and model-pluggable.

本协议把长任务中的裁决、执行、独立验证拆成三种角色，并把证据、权限和恢复状态放在模型窗口之外。平台与模型均可替换。

## 2. Activation gate / 启用门槛

An explicit user phrase—`铁三角`, `启动铁三角`, or `iron triangle`—**MUST** activate the protocol. The controller window receiving the phrase becomes the arbiter, independent of its model vendor. Explicit app, model, window, and effort assignments in the same request **MUST** override defaults.

When the user has not explicitly invoked the protocol, count these conditions before recommending or assigning roles:

1. duration is at least one day, or the task crosses sessions/windows;
2. production changes, irreversible operations, or unverified-success risk are present;
3. unattended continuation is required;
4. reasoning cost must be separated from execution throughput.

Implicit activation **MUST** require at least two conditions. With zero or one condition and no explicit phrase, a single model **SHOULD** execute directly. Complexity by itself is not an implicit activation condition.

## 3. Roles and authority / 角色与权责

### 3.1 Arbiter / 主控

The arbiter decides, plans, writes measurable acceptance lines, sets red lines, and resolves exceptions. It **MUST NOT** investigate, read implementation details, run tests, or deploy. If evidence is insufficient, it sends investigation to the executor and independent verification to the reviewer.

Target token share: less than 2%.

### 3.2 Executor / 执行者

The executor investigates, implements, tests, and deploys within explicit authorization. Every claimed result **MUST** include an independently reproducible receipt. “Done” without evidence is not done.

Target token share: more than 90%.

### 3.3 Reviewer / 审查者

The reviewer independently reproduces critical checks: rerun focused tests, recompute hashes, read deployed values, or exercise the real acceptance channel. It **MUST NOT** approve solely by summarizing the executor’s report. A different model vendor is preferred when available.

### 3.4 Paper protocol / 纸面协议

The durable fourth member is the append-only ledger plus receipts, red lines, pre-decisions, and recovery state. Role assignments may change; this state **MUST** survive window loss and model replacement.

The protocol does not enlarge user-granted permissions. User instructions and platform safety rules remain authoritative.

## 4. Start-of-work checklist / 三角色开工检查单

### Arbiter

- [ ] Record the single goal and what is out of scope.
- [ ] Write measurable acceptance and end-to-end release criteria.
- [ ] Define destructive or irreversible red lines and rollback requirements.
- [ ] Set the cost split and the events that justify arbiter involvement.
- [ ] Pre-decide predictable branches as “if X, then Y.”
- [ ] Name the ledger and the two allowed top-level markers.

### Executor

- [ ] Read the latest arbiter decision, authorized scope, and stop conditions.
- [ ] Confirm the smallest reversible slice and its rollback path.
- [ ] Name the claim that the slice will prove and the receipt it will produce.
- [ ] Confirm that tests and read-back sensors are available before mutation.
- [ ] Append work results in sequence; never rewrite earlier ledger entries.

### Reviewer

- [ ] Read the acceptance line and receipts, not the executor’s conclusion alone.
- [ ] Confirm independent access to rerun or read back each critical check.
- [ ] Identify the true end-to-end channel for milestone acceptance.
- [ ] Refuse approval when evidence is missing, authorization is exceeded, or a red line is touched.
- [ ] Emit exactly one top-level marker after each review turn.

## 5. Ten required mechanisms / 十条核心机制

All ten mechanisms are required. Removing one is a degraded mode and **MUST** be disclosed.

1. **Single append-only ledger.** Decisions, reviews, incidents, and closure records are appended in one continuous sequence. A new window resumes from the ledger, not from remembered chat context.
2. **Receipts.** Each executor claim includes reproducible evidence such as a content hash, test output, deployment closure, rollback anchor, or read-back value.
3. **Independent reproduction.** The reviewer personally reruns the critical verification instead of accepting a report about it.
4. **Machine-readable escalation markers.** Reviewer escalations and closure passes start at column one with fixed markers.
5. **Fail closed by line.** Missing evidence, exceeded authority, or a red-line contact suspends that line and escalates it. Other authorized lines continue.
6. **Pre-decision contract.** Predictable branches are written in advance so the reviewer can continue safely while the arbiter is offline.
7. **No guardrail chasing.** If the same protective parameter is insufficient a second time, work switches to root-cause diagnosis. Silent increases are forbidden.
8. **End-to-end acceptance.** A milestone requires the real user channel or closest real-world probe. Internal service probes alone cannot release it.
9. **Boundary rotation.** At a round boundary, stale windows are replaced together. New windows resume from the handoff and ledger, and orchestration identifiers are updated atomically.
10. **Cost partition.** The arbiter appears only for exceptions, milestones, and final acceptance. Authorized work already verified by the reviewer is not re-reviewed.

## 6. Durable artifacts / 持久化工件

### 6.1 Ledger entry

```markdown
## R-<sequence> <role> <event-type> <UTC timestamp>

- Scope: <authorized slice>
- Decision or claim: <one falsifiable statement>
- Evidence: <receipt identifiers or links>
- Result: <pass | fail | suspended>
- Rollback: <verified rollback reference or not-applicable>
- Next: <one owner and action>
```

Entries **MUST** have monotonically increasing sequence numbers. Corrections append a superseding entry; they never edit history.

### 6.2 Receipt

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

A receipt describes observed state. It **MUST NOT** turn a failed or absent check into a successful claim.

### 6.3 Review record

```markdown
- Receipt reviewed: <stable-id>
- Reproduction performed: <exact independent check>
- Observed result: <pass | fail>
- Differences from executor claim: <none or concise facts>
- Authorization/red-line check: <pass | fail>
- End-to-end check: <pass | fail | not-yet-required>
```

## 7. Top-level marker contract / 顶格上报标记

Public adapters **MUST** recognize these generalized markers only at column one:

```text
NEEDS_ARBITER: <ledger sequence> | <reason> | <decision requested>
ROUND_CLOSURE_PASS: <ledger sequence> | <scope> | <receipt set>
```

Rules:

- one marker represents one completed reviewer turn;
- prose before the marker is allowed, but the marker line itself has no indentation, quote prefix, or list bullet;
- `NEEDS_ARBITER:` suspends only the affected line unless the contract says the whole round is unsafe;
- `ROUND_CLOSURE_PASS:` means the reviewer independently reproduced the required checks; it is not automatically final release;
- adapters may provide local aliases, but public artifacts should emit the generalized markers.

## 8. Pre-decision contract / 预裁决合同

A pre-decision is written before the arbiter goes offline:

```markdown
### Branch <id>: <observable condition>

- IF: <measurable trigger>
- THEN: <authorized action>
- VERIFY: <receipt and independent check>
- LIMIT: <scope, budget, and attempt ceiling>
- ELSE: <continue, suspend this line, or escalate>
```

The contract **MUST** cover authorization, failure isolation, rollback, budget, guardrail escalation, and closure. See the [sanitized night contract](../examples/night-autonomy-contract.md).

## 9. Four orchestration primitives / 四个编排原语

Every platform adapter implements:

```text
turn_ended(executor)  -> completion event with durable cursor
dispatch(role, text)  -> delivery receipt or explicit failure
watch(ledger)         -> ordered stream of appended marker events
escalate(arbiter)     -> wake receipt or manual-handoff payload
```

The semantics are normative; transport is not. Session APIs, native agent messaging, transcript events, file sentinels, terminal resume, and manual paste are valid implementations when they provide honest delivery state. Durable watchers **SHOULD** run under an operating-system or service supervisor, not inside a transient tool sandbox.

## 10. Round lifecycle / 轮次生命周期

```text
arbiter decision
  -> executor slice
  -> executor receipt
  -> reviewer reproduction
  -> dispatch next authorized slice
     or NEEDS_ARBITER
     or ROUND_CLOSURE_PASS
  -> arbiter exception/closure decision when required
```

At a window-rotation boundary:

1. stop dispatching new slices;
2. append the current decision, receipts, blockers, and next owner;
3. rotate the three role windows;
4. update orchestration identifiers and reset watcher cursors to the recorded baseline;
5. read back all mappings before resuming.

## 11. Observed failure controls / 实测失效与控制

| Failure | Required control |
|---|---|
| Relay appears alive but no review starts | supervised watcher, keep-alive, durable cursor |
| Both workers idle and no one advances | dual-idle timeout and reviewer wake-up |
| Executor API unavailable | reviewer enters watch-only mode, probes on a schedule, preserves completed work in ledger |
| Reviewer only summarizes executor | independent receipt reproduction |
| Deployment proceeds with red tests | release only when all tests are green or every red has a separate arbiter decision |
| Context becomes stale, slow, or costly | coordinated boundary rotation and ledger-based recovery |
| Internal probe passes while user path fails | end-to-end channel probe is the release gate |

## 12. Completion / 完成定义

A round is eligible for closure only when:

- every claimed result has a receipt;
- the reviewer reproduced the critical checks;
- every test is green or each remaining red has an explicit arbiter decision;
- rollback evidence exists for production mutations;
- the real end-to-end probe passed when the milestone affects a user channel;
- the reviewer emitted `ROUND_CLOSURE_PASS:`;
- the arbiter issued final acceptance when the contract requires it.

## 13. Open questions

The first evidence base does not settle:

- how much review independence is lost when three roles use models from one vendor;
- the best default idle timeout across platforms;
- a standard portable schema for delivery receipts;
- the quantitative quality loss under arbiter downgrade;
- whether the second field run should change any normative mechanism.

Adapters and implementations **MUST** label answers to these as **open question** until field evidence exists.
