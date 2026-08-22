"""Language policy: single source of truth for run narration language.

The runtime separates machine protocol artifacts from natural-language
narration. Protocol artifacts are identical in every language and are never
localized: run ids, ledger entry headers (``## R-<n> <role> <event> <ts>``)
and their six field labels, the top-level ``NEEDS_ARBITER`` /
``ROUND_CLOSURE_PASS`` markers, reviewer decision commands, and every JSON
key. Narration follows the run's language: role session titles, role system
prompts, executor/reviewer contracts, escalation messages, ledger narration
values, desktop notification summaries, and arbiter closure summaries.

Supported languages live in :data:`SUPPORTED_LANGUAGES`; adding one means
adding a catalog below with the same keys — no call site changes anywhere
else. The default is ``en``, whose strings are byte-identical to v0.2 output,
so runs launched without a language keep their existing behavior.

The language is resolved once at launch (``--language`` flag, else the
runtime config's ``language`` key, else the default) and stored on the run
record; every later narration site reads it back with :func:`run_language`.
"""

from __future__ import annotations

from typing import Any

from .errors import BridgeError

SUPPORTED_LANGUAGES = ("en", "zh-CN")  # catalog-backed narration languages
# Recognized response languages: a superset of catalogs. Any of these may be
# a run's response_language; codes without a static catalog keep the English
# machine fields and role labels while both roles reply in that language.
RESPONSE_LANGUAGES = SUPPORTED_LANGUAGES + ("ja", "ko", "de", "fr", "es", "pt", "it", "ru")
LANGUAGE_NAMES = {
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
    "ru": "Russian",
}
DEFAULT_LANGUAGE = "en"

# Protocol-fixed ledger labels and header shapes intentionally stay English
# in every catalog: docs/protocol-spec.md §6.1 defines them normatively.

CATALOGS: dict[str, dict[str, str]] = {
    "en": {
        "title_executor": "[IT EXEC] {title}",
        "title_reviewer": "[IT REVIEW] {title}",
        "system_prompt_executor": (
            "You are the executor in an Iron Triangle run. Implement and verify; never self-approve."
        ),
        "system_prompt_reviewer": (
            "You are the independent reviewer in an Iron Triangle run. Reproduce evidence; never approve by report."
        ),
        "executor_contract": """IRON TRIANGLE EXECUTOR CONTRACT

Run: {run_id}
Arbiter: the originating control window; do not impersonate it.
Workspace: {cwd}
Append-only ledger: {ledger_path}

Task from the arbiter:
{task}

Operate only inside the user's authorized scope. Investigate, implement, test, and produce reproducible receipts. Use the smallest reversible slice, append results to the ledger, and stop after the currently authorized work is complete. Do not self-approve. The independent reviewer will be dispatched automatically after your turn ends.{response_language_directive}
""",
        "reviewer_contract": """IRON TRIANGLE INDEPENDENT REVIEW CONTRACT

Run: {run_id}
Review round: {review_round}
Workspace: {cwd}
Append-only ledger: {ledger_path}

Task and arbiter constraints:
{task}

The executor turn ended. Independently inspect the workspace and raw receipts. Personally rerun the critical test/hash/read-back/end-to-end probe; a summary of the executor report is not evidence. Append your review record to the ledger.

Then record exactly one machine decision with the bridge helper:

1. Pre-authorized work should continue:
   {command_base} --decision continue --message-file <path-to-next-slice-text>
2. Arbiter judgment is required:
   {command_base} --decision needs-arbiter --ledger-sequence <R-n> --message-file <path-to-question-text>
   Also append a column-one NEEDS_ARBITER: marker to the ledger.
3. The round satisfies closure evidence:
   {command_base} --decision closure-pass --ledger-sequence <R-n> --message-file <path-to-closure-summary>
   Also append a column-one ROUND_CLOSURE_PASS: marker to the ledger.

The decision file will be written to {decision_path}. Do not dispatch another model directly; the supervised bridge owns delivery and deduplication. Missing or malformed decisions fail closed to the arbiter.{response_language_directive}
""",
        "notify_title": "Iron Triangle",
        "notify_message": "{run_id}: {kind}",
        "notify_message_summary": "{run_id}: {kind} ({summary})",
        "notify_summary_NEEDS_ARBITER": "arbiter judgment required",
        "notify_summary_ROUND_CLOSURE_PASS": "round closure passed, awaiting acceptance",
        "msg_unresolved_dispatch": (
            "Run restarted with unresolved dispatch {prompt_id}; delivery state unknown. "
            "Verify in the target app, then `resume` with --ack-prompt-id or --retry-new."
        ),
        "msg_blocked_input": "{role} session requires {pending}; resolve it in the target app, then resume the run.",
        "msg_truncated": "{role} session event stream was truncated; append-only invariant broken, line suspended.",
        "msg_dispatch_rejected": "{role} dispatch was rejected by the destination; affected line suspended.",
        "msg_dispatch_unknown": "{role} dispatch state is unknown (transport timeout or crash window); no blind retry.",
        "msg_no_valid_decision": "Reviewer turn ended without a valid machine decision; affected line suspended.",
        "msg_heartbeat_wake": "Dual-idle timeout reached ({idle_seconds:.0f}s); waking reviewer with latest ledger cursor.",
        "escalate_tail": "inspect reviewer receipt and choose next action",
        "arbiter_accept_default": "Arbiter accepts the independently reproduced closure evidence.",
        "arbiter_stop_default": "Arbiter stopped the run.",
        "ledger_launch": """## R-1 arbiter launch {timestamp}

- Scope: {task}
- Decision or claim: current originating window is the arbiter; execution and review are separately bound.
- Evidence: role bindings in run.json
- Result: active
- Rollback: stop dispatch and preserve receipts
- Next: executor performs the authorized task""",
        "ledger_recover_ack": """## R-{sequence} arbiter recover {timestamp}

- Scope: transport-unknown recovery
- Decision or claim: dispatch {prompt_id} confirmed delivered by human inspection.
- Evidence: manual ack recorded in run.json
- Result: active
- Rollback: stop the run
- Next: watcher resumes {role} monitoring""",
        "ledger_recover_retry": """## R-{sequence} arbiter recover {timestamp}

- Scope: transport-unknown recovery
- Decision or claim: dispatch {prompt_id} confirmed NOT delivered; authorized a replacement.
- Evidence: superseded dispatch preserved in run.json
- Result: active
- Rollback: stop the run
- Next: watcher may dispatch {role} again""",
        "ledger_final_acceptance": """## R-{sequence} arbiter final-acceptance {timestamp}

- Scope: final closure decision
- Decision or claim: {message}
- Evidence: reviewer closure receipt and ROUND_CLOSURE_PASS
- Result: pass
- Rollback: not-applicable
- Next: none""",
        "ledger_continuation": """## R-{sequence} arbiter continuation {timestamp}

- Scope: previously suspended line
- Decision or claim: {message}
- Evidence: arbiter dispatch receipt {prompt_id}
- Result: active
- Rollback: stop the affected line
- Next: executor""",
        "ledger_stop": """## R-{sequence} arbiter stop {timestamp}

- Scope: active run
- Decision or claim: {message}
- Evidence: current run state
- Result: suspended
- Rollback: preserve all receipts
- Next: none""",
        "ledger_language_switch": "- Response language switched: {old} -> {new} (registered by the arbiter; both roles inherit)",
    },
    "zh-CN": {
        "title_executor": "[铁三角·执行] {title}",
        "title_reviewer": "[铁三角·审查] {title}",
        "system_prompt_executor": "你是铁三角运行中的执行者。负责实现与验证；不得自我验收。",
        "system_prompt_reviewer": "你是铁三角运行中的独立审查者。必须亲自复现证据；不得仅凭汇报通过。",
        "executor_contract": """铁三角执行者合同

运行：{run_id}
主控：发起本次运行的控制窗口；不得冒充主控。
工作区：{cwd}
只追加台账：{ledger_path}

主控下达的任务：
{task}

仅在用户授权范围内操作。调查、实现、测试并产出可复现收据；使用最小可回滚切片，把结果追加到台账；当前授权工作完成后即停止。不得自我验收。执行者回合结束后，将自动派出独立审查者。{response_language_directive}
""",
        "reviewer_contract": """铁三角独立审查合同

运行：{run_id}
审查轮次：{review_round}
工作区：{cwd}
只追加台账：{ledger_path}

任务与主控约束：
{task}

执行者回合已结束。请独立检查工作区与原始收据；亲自复现关键测试、哈希、读回与端到端探针；执行者报告的摘要不构成证据。把你的审查记录追加到台账。

然后用桥助手记录恰好一条机器裁决：

1. 预授权工作应继续：
   {command_base} --decision continue --message-file <下一切片文本路径>
2. 需要主控裁决：
   {command_base} --decision needs-arbiter --ledger-sequence <R-n> --message-file <问题文本路径>
   同时在台账顶格追加 NEEDS_ARBITER: 标记。
3. 本轮满足收口证据：
   {command_base} --decision closure-pass --ledger-sequence <R-n> --message-file <收口摘要路径>
   同时在台账顶格追加 ROUND_CLOSURE_PASS: 标记。

裁决文件将写入 {decision_path}。不要直接派发其他模型；受监督的桥负责投递与去重。缺失或格式非法的裁决按失败闭合处理，交由主控。{response_language_directive}
""",
        "notify_title": "铁三角",
        "notify_message": "{run_id}：{kind}",
        "notify_message_summary": "{run_id}：{kind}（{summary}）",
        "notify_summary_NEEDS_ARBITER": "需要主控裁决",
        "notify_summary_ROUND_CLOSURE_PASS": "本轮收口通过，等待主控验收",
        "msg_unresolved_dispatch": (
            "运行重启后存在未确认的派发 {prompt_id}；投递状态未知。"
            "请在目标应用中核实，然后用 `resume` 配合 --ack-prompt-id 或 --retry-new 处理。"
        ),
        "msg_blocked_input": "{role} 会话需要处理 {pending}；请在目标应用中解决后恢复运行。",
        "msg_truncated": "{role} 会话事件流被截断；只追加不变量被破坏，该线路已挂起。",
        "msg_dispatch_rejected": "{role} 派发被目标端拒绝；受影响线路已挂起。",
        "msg_dispatch_unknown": "{role} 派发状态未知（传输超时或崩溃窗口）；不盲目重试。",
        "msg_no_valid_decision": "审查者回合结束但没有有效的机器裁决；受影响线路已挂起。",
        "msg_heartbeat_wake": "双闲超时（{idle_seconds:.0f} 秒）；携带最新台账游标唤醒审查者。",
        "escalate_tail": "检查审查者收据并选择下一步动作",
        "arbiter_accept_default": "主控接受经独立复现的收口证据。",
        "arbiter_stop_default": "主控停止了本次运行。",
        "ledger_launch": """## R-1 arbiter launch {timestamp}

- Scope: {task}
- Decision or claim: 当前发起窗口即主控；执行与审查分别绑定。
- Evidence: run.json 中的角色绑定
- Result: active
- Rollback: 停止派发并保留收据
- Next: 执行者执行授权任务""",
        "ledger_recover_ack": """## R-{sequence} arbiter recover {timestamp}

- Scope: 传输状态未知后的恢复
- Decision or claim: 派发 {prompt_id} 经人工查验确认已送达。
- Evidence: 人工确认已记录于 run.json
- Result: active
- Rollback: 停止本次运行
- Next: 监督者恢复对 {role} 的监控""",
        "ledger_recover_retry": """## R-{sequence} arbiter recover {timestamp}

- Scope: 传输状态未知后的恢复
- Decision or claim: 派发 {prompt_id} 经人工确认未送达；已授权替换派发。
- Evidence: 被替换的派发已保留于 run.json
- Result: active
- Rollback: 停止本次运行
- Next: 监督者可重新向 {role} 派发""",
        "ledger_final_acceptance": """## R-{sequence} arbiter final-acceptance {timestamp}

- Scope: 最终收口裁决
- Decision or claim: {message}
- Evidence: 审查者收口收据与 ROUND_CLOSURE_PASS
- Result: pass
- Rollback: 不适用
- Next: 无""",
        "ledger_continuation": """## R-{sequence} arbiter continuation {timestamp}

- Scope: 此前被挂起的线路
- Decision or claim: {message}
- Evidence: 主控派发回执 {prompt_id}
- Result: active
- Rollback: 停止受影响线路
- Next: 执行者""",
        "ledger_stop": """## R-{sequence} arbiter stop {timestamp}

- Scope: 活跃运行
- Decision or claim: {message}
- Evidence: 当前运行状态
- Result: suspended
- Rollback: 保留全部收据
- Next: 无""",
        "ledger_language_switch": "- 回复语言已切换：{old} -> {new}（由主控登记；执行者与审查者共同继承）",
    },
}


def normalize_language(value: Any) -> str:
    """Return a valid response-language code; fail closed on unknown values.

    Response languages are a superset of catalog languages: any recognized
    code may be the run's ``response_language`` even when only the ``en``
    machine fields back it statically.
    """
    if value is None:
        return DEFAULT_LANGUAGE
    candidate = str(value).strip()
    if candidate in RESPONSE_LANGUAGES:
        return candidate
    raise BridgeError(f"unsupported language {value!r}; supported: {', '.join(RESPONSE_LANGUAGES)}")


def resolve_language(config: dict[str, Any] | None, override: str | None = None) -> str:
    """Launch-time precedence: explicit override, then config key, then default."""
    if override is not None:
        return normalize_language(override)
    return normalize_language((config or {}).get("language"))


def detect_language(text_sample: str) -> str:
    """Best-effort dominant-script detection for automatic response language.

    Deterministic script-range heuristics only — an explicit user language
    requirement always wins over this guess. Kana is checked before Han
    (Japanese text contains kanji); anything Latin-script or empty maps to
    the English default.
    """
    sample = text_sample or ""
    if any("\u3040" <= ch <= "\u30ff" for ch in sample):  # hiragana + katakana
        return "ja"
    if any("\uac00" <= ch <= "\ud7af" for ch in sample):  # hangul syllables
        return "ko"
    if any("\u4e00" <= ch <= "\u9fff" for ch in sample):  # CJK unified ideographs
        return "zh-CN"
    if any("\u0400" <= ch <= "\u04ff" for ch in sample):  # cyrillic
        return "ru"
    return DEFAULT_LANGUAGE


def resolve_run_language(config: dict[str, Any] | None, override: str | None = None, task_text: str | None = None) -> str:
    """Unified response-language resolution for a whole run.

    Explicit override > configured default > dominant task language > en.
    The result is stored once on the run record; executor and reviewer
    inherit it jointly and never re-judge separately.
    """
    if override is not None:
        return normalize_language(override)
    configured = (config or {}).get("language")
    if configured is not None:
        return normalize_language(configured)
    if task_text:
        return detect_language(task_text)
    return normalize_language(None)


def run_language(run: dict[str, Any] | None) -> str:
    """Response language of a stored run; records created before this field exist stay ``en``."""
    try:
        return normalize_language((run or {}).get("language"))
    except BridgeError:
        return DEFAULT_LANGUAGE


def catalog_for(language: str) -> str:
    """Catalog that renders static strings for a response language.

    Languages without a static catalog keep the English machine fields and
    role labels; the model-facing reply language is carried separately by
    :func:`response_directive`.
    """
    code = normalize_language(language)
    return "zh-CN" if code.startswith("zh") else "en"


def response_directive(language: str) -> str:
    """Extra contract line pinning the model's natural-language reply language.

    Empty for catalog-backed languages (their contracts already are in the
    right language, keeping en byte-compatible and zh-CN unchanged); an
    explicit instruction otherwise.
    """
    code = normalize_language(language)
    if catalog_for(code) == code:
        return ""
    name = LANGUAGE_NAMES.get(code, code)
    return (
        f"\n\nResponse language: write all of your natural-language replies in {name} ({code}). "
        "Machine protocol fields and markers stay unchanged."
    )


def text(language: str, key: str, **kwargs: Any) -> str:
    """Render one catalog entry; ``language`` must be a catalog-backed code."""
    catalog_language = catalog_for(language)
    catalog = CATALOGS[catalog_language]
    if key not in catalog:
        raise BridgeError(f"message key {key!r} is missing from the {catalog_language} catalog")
    return catalog[key].format(**kwargs)


def role_title(language: str, role: str, title: str) -> str:
    """Default new-session title for a role under the run's language."""
    key = {"executor": "title_executor", "reviewer": "title_reviewer"}[role]
    return text(catalog_for(language), key, title=title)


def notification(language: str, run_id: str, kind: str) -> tuple[str, str]:
    """Desktop notification ``(title, message)`` for an outbox kind."""
    catalog_language = catalog_for(language)
    title = text(catalog_language, "notify_title")
    summary = CATALOGS[catalog_language].get(f"notify_summary_{kind}")
    if summary is None:
        return title, text(catalog_language, "notify_message", run_id=run_id, kind=kind)
    return title, text(catalog_language, "notify_message_summary", run_id=run_id, kind=kind, summary=summary)
