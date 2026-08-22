# Case Study: The Founding Field Run

*A sanitized account of the four-day production run that produced Iron Triangle Protocol v1. Cost figures and the end-to-end incident below are backed by a machine-readable receipt: [`docs/receipts/founding-field-run.json`](receipts/founding-field-run.json).*

- Status: evidence-backed case study. Every number traces to the receipt file above, which carries metric definitions, raw counters, derivation formulas, one-way provenance anchors (prefix-snapshot hashes for append-only private sources and a canonical event-set digest for aggregated hook events), and the desensitization rules applied. Remaining unknowns are listed as open questions in §7.
- 状态：本案例研究由收据背书。所有数字可追溯至上述机器可读收据（含指标定义、原始计数、推导公式、只追加私有源的前缀快照哈希与聚合 hook 事件的规范事件集摘要，以及已执行的脱敏规则）；仍未知项见第 7 节。
- Protocol version at time of writing: `1.0-draft` ([spec](protocol-spec.md)) · Tool version: `0.3.0-rc.1`.

## 中文摘要

2026 年 8 月中旬，一段约 92 小时（主控结案综述口径，通常概括为四天）的真实记忆系统生产优化长任务由三个模型角色完成：交互式编辑器代理任主控、高吞吐运行时任执行者、独立审查会话任审查者，全部通过一份只追加台账与收据制验收协作。各角色的收据活动跨度已被精确界定——审查者窗内 88.31 小时、执行者全流 101.54 小时——而任务本身的精确起止仍为开放问题。运行暴露七类失效（见下文表格），其中最贵的一课是端到端通道断裂：服务层检索 8/8 全绿、同问句真实用户通道却返回空。主控在台账中承认此前只验了服务层、未验真实通道，按 P0 处理；根因是查询时全量嵌入（4,421 个检索面外推约 45.6 秒），修复为仅嵌查询＋预存连接＋索引维护入工作周期；审查者随后以两条真实通道探针复验（1.42 秒 8/8 档案浮现；1.13 秒进展槽命中）确认闭环。成本方面，合同预设主控 `<2%` 总 token 的目标**没有达成**：收据复算为 **2.554832%**（差约 0.55 个百分点），执行者 70.07%、审查者 27.37%。这一纠正本身就是协议诚实门的成功拦截——未经复算的"<2% 达成"宣传在发布前被台账拦下，公开的是实测值而非目标值。

## 1. The run

| Fact | Value | Public evidence |
|---|---|---|
| Duration | about 92 hours as carried by the arbiter's closing summary — commonly rounded to four days. The receipts bound each role's recorded activity precisely (reviewer in-window span 88.31 h (bounded by the 1,262nd parsed event); executor full-stream span 101.54 h), while the task's exact wall-clock start and end remain an open question ([receipt](receipts/founding-field-run.json), `run_window`, `activity_spans`) |
| Workload | production optimization run on a memory system serving a real end user through a messaging channel | [README · Field origin](../README.md#field-origin--实战来源); incident record in §4 |
| Organization of work | one arbiter, one executor, one independent reviewer; one append-only ledger; receipt-based acceptance | [README · Field origin](../README.md#field-origin--实战来源); [spec §3](protocol-spec.md#3-roles-and-authority--角色与权责) |
| Nature of evidence | operational case, not a synthetic benchmark | [README · Field origin](../README.md#field-origin--实战来源) |

Names, session identifiers, model brands, channel details, and infrastructure are generalized throughout; the sanitizer enforced on every tracked file ([`src/iron_triangle/sanitizer.py`](../src/iron_triangle/sanitizer.py)) independently guarantees none appear anywhere in this repository.

## 2. How the work was held together

The durable member of the team was paper, not memory:

- **One append-only ledger** with continuous sequence numbers; corrections supersede, never rewrite ([spec §5 mechanism 1, §6.1](protocol-spec.md#5-ten-required-mechanisms--十条核心机制)).
- **Receipts for every claim** — content hashes, test output, read-backs — because "'done' without evidence is not done" ([spec §5 mechanism 2, §3.2](protocol-spec.md#32-executor--执行者)).
- **Independent reproduction by the reviewer**, never approval-by-summary ([spec §5 mechanism 3, §3.3](protocol-spec.md#33-reviewer--审查者)).
- **Pre-decided branches** written before the arbiter went offline ([spec §8](protocol-spec.md#8-pre-decision-contract--预裁决合同)); the sanitized contract shipped in this repo ([`examples/night-autonomy-contract.md`](../examples/night-autonomy-contract.md)) preserves that structure.
- **Two fixed escalation markers** at column one, used repeatedly during the run ([spec §7](protocol-spec.md#7-top-level-marker-contract--顶格上报标记)); excerpt C in §4 is a sanitized instance.

## 3. What broke: seven failure classes

All seven classes below were observed in the run ([README · Field origin](../README.md#field-origin--实战来源)); the table is normative today ([spec §11](protocol-spec.md#11-observed-failure-controls--实测失效与控制), [skill reference](../skills/iron-triangle/references/failure-controls.md)):

| # | Failure observed in the run | Required control (now normative) |
|---|---|---|
| 1 | Relay appears alive but no review starts | supervised watcher, keep-alive, durable cursor |
| 2 | Both workers idle and no one advances | dual-idle timeout and reviewer wake-up |
| 3 | Executor API unavailable | reviewer enters watch-only mode, probes on a schedule, preserves completed work in ledger |
| 4 | Reviewer only summarizes executor | independent receipt reproduction |
| 5 | Deployment proceeds with red tests | release only when all tests are green or every red has a separate arbiter decision |
| 6 | Context becomes stale, slow, or costly | coordinated boundary rotation and ledger-based recovery |
| 7 | Internal probe passes while user path fails | end-to-end channel probe is the release gate |

Class 7 has a fully documented instance (§4). The other six remain class-level descriptions pending sanitized instance receipts (§7).

## 4. The end-to-end channel breakage — a complete loop

This is the failure class the protocol's most expensive rule came from, captured here from admission to closure. All quotes are semantic English re-renderings of ledger entries, not verbatim text; identifiers are generalized ([receipt](receipts/founding-field-run.json), `end_to_end_incident`).

**Breakage.** Acceptance questions failed on the real user channel although the data existed and service-layer retrieval was correct:

> **Excerpt A — arbiter ledger entry (admission).** "The verified facts: eight roster records and their memory heads are in the store right now; the service layer answers the very same question correctly. What was false was my release decision — I checked the water plant's output, never whether the tap in your home was connected. The messaging channel is still running the old pipeline… P0 issued; end-to-end diagnosis under way."

**Root cause and fix.** The reviewer traced the breakage to query-time full embedding and confirmed the repair against the ledger:

> **Excerpt B — reviewer ledger entry (turn-173 review).** "Latency root cause confirmed: answering required embedding all 4,421 indexed surfaces first, extrapolating to ~45.6 s per query. Fix: embed the query only, join via prestored digests, move index maintenance into worker cycles, warm the index once at startup. Both acceptance questions then re-run over the real channel by the reviewer personally: roster question 1.42 s with all 8 catalog heads surfaced; progress question 1.13 s with the current-state entity and latest-progress slot hit."

**Fail-closed discipline around the fix itself.** Even the repair's side effects were escalated rather than silently patched:

> **Excerpt C — escalation entry.** "Eight retrieval-surface tests are red after the change, including an untrusted-head security assertion. Attribution: the new empty-index query semantics conflict with test fixtures that have no warmed index. Production behaves correctly — both real-channel probes pass with a warmed index. Ruling requested before anything proceeds; the reds stay open until decided."

**Closure.** The arbiter's ruling recorded the P0 loop as closed only after the reviewer's own real-channel reproduction — internal probes alone would not release it ([spec §5 mechanism 8, §12](protocol-spec.md#12-completion--完成定义)). This single loop exercised mechanisms 1–5 and 8 of the ten.

## 5. Cost structure — measured, target missed, published anyway

The run operated under explicit role budgets; the protocol keeps them as targets ([spec §3.1–3.2](protocol-spec.md#31-arbiter--主控)). The receipts settle what actually happened:

| Role | Target share | Measured share | Native tokens (raw counters in [receipt](receipts/founding-field-run.json)) |
|---|---|---|---:|
| Arbiter | `<2%` | **2.554832%** | 34,059,923 |
| Executor | `>90%` | 70.072850% | 934,181,204 |
| Reviewer | remainder | 27.372318% | 364,916,007 |
| Total | — | 100% | 1,333,157,134 |

**The honesty correction:** the contracted arbiter budget of `<2%` was **not met** — the measured share is 2.554832%, about 0.55 percentage points over target. Earlier claims that the target had been achieved were caught by the paper trail before publication and replaced by the recomputed figure. We publish this miss deliberately: it is a working example of the protocol's honesty gate intercepting an unverified success claim — precisely the failure mode the protocol exists to prevent. No counter rebasing narrows the gap; cache-read/cache-write counters are diagnostic subcounters of input and are never added on top of native totals ([receipt](receipts/founding-field-run.json), `metric_definitions`).

## 6. What the tooling inherited

Everything above is protocol text; this repository additionally ships the tooling the run relied on, in verified form where the [release gates](release-gates.md) say so: the session-API bridge with honest delivery states (`accepted` / `rejected` / `unknown`) and crash resume, the fail-closed policy state machine, supervised relays, the sanitization scanner with its security canary, and generated skills for four platforms ([support matrix](../README.md#support-matrix--支持矩阵)). The full CI matrix now runs green remotely (receipt runs linked from the support matrix); local checks are still never presented as remote runs.

## 7. Evidence status and open questions

Closed by the public receipt ([`docs/receipts/founding-field-run.json`](receipts/founding-field-run.json)): measured per-role token structure with raw counters and formulas; the end-to-end channel-breakage loop from admission to independent reverification; sanitized ledger-entry renderings (§4).

Still open:

- the task's exact wall-clock start and end — role-level activity spans are receipt-bounded (`activity_spans`), but no single source proves the absolute start/end behind the ~92-hour approximation;
- concrete instance receipts for failure classes 1–6 (class-level descriptions only, §3);
- per-step latency distribution across the whole run.

这些开放问题保持显式标注；任何私有材料补洞或数字虚构都被协议禁止。
