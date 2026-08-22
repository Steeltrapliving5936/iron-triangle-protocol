---
name: iron-triangle
description: >-
  Activate immediately whenever the user says 铁三角, 启动铁三角, or iron
  triangle; the receiving window becomes the arbiter regardless of model
  brand. Otherwise recommend the protocol only when at least two apply:
  day-long or cross-session work, production or irreversible or
  high-fabrication-risk changes, unattended continuation, or separated
  reasoning/execution budgets. Orchestrates a distinct executor, an
  independent reviewer, a durable append-only ledger, and a supervised relay.
license: MIT
compatibility: Any agent runtime; durable unattended watching requires an OS service supervisor.
metadata:
  protocol: iron-triangle
  version: 0.3.0-rc.1
---

# Iron Triangle Protocol

Three model roles plus a durable paper protocol deliver long-running work more reliably than any single model. Models are replaceable slots; the ledger, receipts, red lines, pre-decisions, and watcher state are the durable fourth member.

Explicit invocation authorizes creating the role sessions and durable run artifacts this workflow needs. It never grants permission to deploy, perform destructive actions, or communicate externally beyond the task's stated scope. Installing an OS supervisor stays a separate, explicit setup action.

## Activation gate

- Any occurrence of `铁三角`, `启动铁三角`, or `iron triangle` is an explicit invocation. Do not apply the implicit gate to refuse it.
- The window receiving the phrase is the **arbiter**, independent of model vendor. Never infer the arbiter from a brand.
- Explicit app, window/session, model, and effort assignments in the same message override private defaults.
- Task text present: launch immediately. Only the phrase present: ask only for the missing task. Never make the user restate this contract.
- Unresolvable adapter or target: fail closed with one concise blocker; label unsupported transport **open question**.

Implicit gate (no phrase used): count (1) at least one day or cross-session/window, (2) production/irreversible/high-fabrication-risk work, (3) unattended continuation, (4) separated reasoning/execution budgets. Activate at two or more; otherwise run as a normal single-agent task. If three roles or a durable ledger cannot be instantiated, disclose degraded mode — never label executor self-review as independent.

## Roles

| Role | Responsibility | Budget |
|---|---|---:|
| Arbiter | Decide, plan, set measurable acceptance and red lines; never investigate or execute | `<2%` |
| Executor | Investigate, implement, test, deploy within authorization; receipt for every claim | `>90%` |
| Reviewer | Independently rerun critical checks; never approve by summarizing the report | remainder |
| Paper protocol | Append-only ledger, receipts, red lines, pre-decisions, bindings, watcher cursor | durable |

## Marker contract

Markers start at column one — no list bullet, quote, or indentation:

```text
NEEDS_ARBITER: <ledger sequence> | <reason> | <decision requested>
ROUND_CLOSURE_PASS: <ledger sequence> | <scope> | <receipt set>
```

`NEEDS_ARBITER:` suspends only the affected line unless the contract says the whole round is unsafe. `ROUND_CLOSURE_PASS:` means the reviewer independently reproduced the checks; it does not replace required arbiter acceptance.

## Reference map

Load on demand:

- [references/workflow.md](references/workflow.md) — three-role start checklists, the ten required mechanisms, and closure conditions;
- [references/templates.md](references/templates.md) — ledger entry, receipt, review record, pre-decision, decision-summary, and closure-briefing templates;
- [references/failure-controls.md](references/failure-controls.md) — the seven observed failure classes and their controls;
- [references/platform-codex.md](references/platform-codex.md), [references/platform-claude-code.md](references/platform-claude-code.md), [references/platform-kimi-session-api.md](references/platform-kimi-session-api.md), [references/platform-cursor.md](references/platform-cursor.md), [references/platform-generic-cli.md](references/platform-generic-cli.md) — per-runtime orchestration mappings for the four primitives (`turn_ended`, `dispatch`, `watch`, `escalate`);
- [assets/ledger-entry-template.md](assets/ledger-entry-template.md), [assets/receipt-template.yaml](assets/receipt-template.yaml), [assets/predecision-contract-template.md](assets/predecision-contract-template.md) — copy-paste starting files.

## Operating rules

1. One append-only ledger per run; corrections append superseding entries, never edits.
2. Every claimed result carries a reproducible receipt; "done" without evidence is not done.
3. The reviewer personally reruns critical checks; a report about them is not evidence.
4. Fail closed per line: missing evidence, exceeded authority, or a red line suspends that line and escalates.
5. Unknown delivery state is an escalation condition, never a license to resend.
6. Unknown policy choices are written as **open question**, not filled by assumption.
7. Language is automatic — the user never operates a language switch. Before launching, determine one `response_language` for the whole run: an explicit user language requirement wins; otherwise use the dominant language of the user's task (the bridge also auto-detects it when nothing explicit exists). Pass it once (`launch --language <code>` or config `"language"`); the executor and reviewer inherit it jointly and never re-judge separately. Catalog-backed languages (`en`, `zh-CN`) localize window titles, contracts, and narration values; any other recognized code keeps English machine fields and role labels while both roles' natural-language replies follow `response_language`. For a mid-run switch, the arbiter registers it (`arbiter --decision continue --language <code>`) so both roles change together — never one silently splitting from the other. Native UI text of third-party apps stays outside this policy (**open question**).

## Arbiter cost partition

These rules operationalize mechanism 10. They do not add an eleventh mechanism and they do not change the marker contract.

- The arbiter produces ruling text only: acceptance lines, red lines, pre-decisions, exception rulings, and the six-element closure briefing. Session creation, worker dispatch, polling, material assembly, and evidence persistence belong to the executor or the supervised orchestration layer.
- The arbiter window MAY invoke the documented bridge commands that start a run or record a ruling (`launch`, `status --pending`, `arbiter --decision`). It MUST NOT call vendor session APIs, debug consoles, or perform executor investigation.
- At the end of every executor or reviewer turn, attach a compact **decision-summary block** of at most 10 lines covering conclusion, key figures, risks, and items needing a ruling (see [references/templates.md](references/templates.md)). Full worker narratives stay in evidence files. The arbiter's default intake is that block plus receipt identifiers. If the block is missing or too thin to rule, fail closed and request a complete summary — do not compensate by reading implementation.
- Role trials or replacements: the arbiter freezes the prompt template in the ledger; the executor delivers it verbatim. The arbiter does not run the trial.
- Incidents, including production or P0 events, do not exempt the cost partition. The arbiter still rules from the summary and receipts; it does not become the incident operator.
- Two consecutive execution-layer actions by the arbiter are a process incident: stop, reassign, and append the incident to the ledger.

## Arbiter closure briefing

After every reviewer `closure-pass` or `needs-arbiter`, the arbiter's ruling to the user MUST state, side by side:

1. the executor's claim;
2. the reviewer's independent findings and exactly where they differ from the executor;
3. the arbiter's ruling and its rationale;
4. remaining risks and open questions;
5. the recommended next step;
6. the authorization basis for automatic continuation (a pre-decision covering the same scope) or an explicit wait for user confirmation.

The six-element briefing is synthesized from the workers' decision-summary blocks and receipt results. The arbiter synthesizes evidence and ruling scope; it is **not a third technical reviewer** and must never claim to have personally re-run checks — divergence between roles is presented, not flattened. Within the same authorized scope, fixes already covered by pre-decisions may auto-continue. After closure, any new substantive scope requires a pre-decision or explicit user authorization; a briefing without element 6 is incomplete.
