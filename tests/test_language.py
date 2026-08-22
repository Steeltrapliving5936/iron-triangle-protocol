"""Deterministic tests for the run narration language policy (zh-CN / en).

Contract under test:

- ``en`` output stays byte-identical to v0.2 (no ``language`` anywhere means
  today's behavior, byte for byte);
- ``zh-CN`` localizes role window titles, role system prompts, the executor
  and reviewer contracts, ledger narration values, and notification
  summaries, while machine protocol fields, the reviewer decision commands,
  and the ``NEEDS_ARBITER`` / ``ROUND_CLOSURE_PASS`` markers stay identical;
- the arbiter's task and constraints are carried verbatim into both contracts
  in both languages;
- the language is resolved once at launch, stored on the run record, and read
  back by every later narration site.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import _helpers  # noqa: F401  (sys.path bootstrap)

from iron_triangle import cli, config as config_mod, i18n, policy, prompts, store
from iron_triangle.errors import BridgeError
from iron_triangle.runner import execute_actions

ROOT = _helpers.ROOT
BRIDGE = ROOT / "scripts" / "iron_triangle_bridge.py"

# v0.2 baseline strings, replicated verbatim so any drift in the en compat
# path fails here first.
V02_EXECUTOR_PROMPT = """IRON TRIANGLE EXECUTOR CONTRACT

Run: {run_id}
Arbiter: the originating control window; do not impersonate it.
Workspace: {cwd}
Append-only ledger: {ledger_path}

Task from the arbiter:
{task}

Operate only inside the user's authorized scope. Investigate, implement, test, and produce reproducible receipts. Use the smallest reversible slice, append results to the ledger, and stop after the currently authorized work is complete. Do not self-approve. The independent reviewer will be dispatched automatically after your turn ends.
"""


def _v02_reviewer_prompt(run: dict, bridge_path: pathlib.Path, config_path: pathlib.Path) -> str:
    import shlex
    import sys

    from iron_triangle.store import run_dir_from_record

    decision_path = run_dir_from_record(run) / f"review-decision-{run['review_round']}.json"
    command_base = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(bridge_path))} "
        f"--config {shlex.quote(str(config_path))} decide --run-id {shlex.quote(run['run_id'])} "
        f"--review-round {run['review_round']}"
    )
    return f"""IRON TRIANGLE INDEPENDENT REVIEW CONTRACT

Run: {run['run_id']}
Review round: {run['review_round']}
Workspace: {run['cwd']}
Append-only ledger: {run['ledger_path']}

Task and arbiter constraints:
{run['task']}

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

The decision file will be written to {decision_path}. Do not dispatch another model directly; the supervised bridge owns delivery and deduplication. Missing or malformed decisions fail closed to the arbiter.
"""


class _ClientShim:
    def __init__(self, backend: "_BackendShim") -> None:
        self._backend = backend

    def sessions(self) -> list[dict]:
        return []


class _BackendShim(_helpers.FakeBackend):
    """FakeBackend plus the `client` attribute cmd_launch expects."""

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.client = _ClientShim(self)


def make_run(
    config: dict,
    backend,
    tmp: pathlib.Path,
    *,
    language: str | None = None,
    task: str = "Bounded test task.",
    dispatch_now: bool = False,
) -> dict:
    run = _helpers.make_run(config, backend, tmp, task=task, dispatch_now=dispatch_now)
    if language is not None:
        run["language"] = language
        store.save_run(config, run)
    return run


class EnglishCompatTests(unittest.TestCase):
    """No language information anywhere must reproduce v0.2 output exactly."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.temp.name)
        self.config = _helpers.base_config(self.tmp)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_executor_prompt_matches_v02_byte_for_byte(self) -> None:
        run = {
            "run_id": "it-golden-1",
            "cwd": "/ws",
            "ledger_path": "/state/runs/it-golden-1/ledger.md",
            "task": "Do the bounded thing.",
        }
        self.assertEqual(prompts.executor_prompt(run), V02_EXECUTOR_PROMPT.format(**run))

    def test_reviewer_prompt_matches_v02_byte_for_byte(self) -> None:
        run = {
            "run_id": "it-golden-2",
            "review_round": 3,
            "cwd": "/ws",
            "ledger_path": str(self.tmp / "state/runs/it-golden-2/ledger.md"),
            "task": "Do the bounded thing.",
        }
        expected = _v02_reviewer_prompt(run, BRIDGE, self.tmp / "runtime.json")
        self.assertEqual(prompts.reviewer_prompt(run, BRIDGE, self.tmp / "runtime.json"), expected)

    def test_role_system_prompts_match_v02(self) -> None:
        self.assertEqual(
            prompts.role_system_prompt("executor"),
            "You are the executor in an Iron Triangle run. Implement and verify; never self-approve.",
        )
        self.assertEqual(
            prompts.role_system_prompt("reviewer"),
            "You are the independent reviewer in an Iron Triangle run. Reproduce evidence; never approve by report.",
        )

    def test_en_output_is_ascii_only(self) -> None:
        run = make_run(self.config, _helpers.FakeBackend(self.config), self.tmp)
        run["review_round"] = 1
        for text in (
            prompts.executor_prompt(run),
            prompts.reviewer_prompt(run, BRIDGE, self.tmp / "runtime.json"),
            prompts.role_system_prompt("executor"),
            i18n.role_title("en", "executor", "t"),
            i18n.notification("en", run["run_id"], "NEEDS_ARBITER")[1],
        ):
            self.assertTrue(text.isascii(), text)

    def test_default_titles_are_the_v02_prefixes(self) -> None:
        self.assertEqual(i18n.role_title("en", "executor", "Fix it"), "[IT EXEC] Fix it")
        self.assertEqual(i18n.role_title("en", "reviewer", "Fix it"), "[IT REVIEW] Fix it")

    def test_pre_language_run_record_defaults_to_en(self) -> None:
        self.assertEqual(i18n.run_language({}), "en")
        self.assertEqual(i18n.run_language({"language": "zh-CN"}), "zh-CN")


class LanguageResolutionTests(unittest.TestCase):
    def test_precedence_override_then_config_then_default(self) -> None:
        self.assertEqual(i18n.resolve_language({"language": "zh-CN"}, "en"), "en")
        self.assertEqual(i18n.resolve_language({"language": "zh-CN"}), "zh-CN")
        self.assertEqual(i18n.resolve_language({}), "en")
        self.assertEqual(i18n.resolve_language(None, "zh-CN"), "zh-CN")

    def test_unknown_language_fails_closed(self) -> None:
        with self.assertRaises(BridgeError):
            i18n.resolve_language({"language": "klingon"})
        with self.assertRaises(BridgeError):
            i18n.resolve_language({}, "zh")  # zh alone is not a response-language code

    def test_config_validation_accepts_known_and_rejects_unknown_language(self) -> None:
        base = {
            "schema_version": 2,
            "adapters": {"kimi-code": {"base_url": "http://session-api.invalid/api/v1", "token_file": "t"}},
            "state_dir": "/tmp/state",
        }
        config_mod.validate_config({**base, "language": "zh-CN"})
        config_mod.validate_config({**base, "language": "ja"})  # non-catalog response language
        config_mod.validate_config(base)
        with self.assertRaises(BridgeError):
            config_mod.validate_config({**base, "language": "klingon"})


class ResponseLanguageDetectionTests(unittest.TestCase):
    """Automatic language: explicit > configured > dominant task script > en."""

    def test_detection_by_script_is_deterministic(self) -> None:
        cases = {
            "修复登录超时并补测试。": "zh-CN",
            "Implement the bounded slice and add tests.": "en",
            "ログイン処理を修正し、テストを追加してください。": "ja",
            "로그인 시간 초과를 수정하세요.": "ko",
            "Исправить таймаут входа.": "ru",
            "": "en",
        }
        for text, expected in cases.items():
            self.assertEqual(i18n.detect_language(text), expected, text)

    def test_resolution_precedence_override_then_config_then_detection(self) -> None:
        # Explicit override wins over everything.
        self.assertEqual(i18n.resolve_run_language({"language": "ja"}, "de", "中文任务"), "de")
        # Configured default wins over task detection.
        self.assertEqual(i18n.resolve_run_language({"language": "ja"}, None, "中文任务"), "ja")
        # No switch anywhere: the task's dominant script decides.
        self.assertEqual(i18n.resolve_run_language({}, None, "修复登录超时"), "zh-CN")
        self.assertEqual(i18n.resolve_run_language({}, None, "Fix the login timeout"), "en")
        self.assertEqual(i18n.resolve_run_language({}, None, "ログインを修正"), "ja")
        # Nothing to go on: English default (v0.2 behavior).
        self.assertEqual(i18n.resolve_run_language({}, None, None), "en")

    def test_third_language_falls_back_to_english_machine_fields_with_directive(self) -> None:
        run = {"run_id": "it-ja", "cwd": "/ws", "ledger_path": "/l.md", "task": "t", "language": "ja"}
        contract = prompts.executor_prompt(run)
        self.assertTrue(contract.startswith("IRON TRIANGLE EXECUTOR CONTRACT"))  # en machine fields
        self.assertIn("Response language: write all of your natural-language replies in Japanese (ja).", contract)
        run["review_round"] = 1
        review = prompts.reviewer_prompt(run, BRIDGE, pathlib.Path("/cfg.json"))
        self.assertIn("IRON TRIANGLE INDEPENDENT REVIEW CONTRACT", review)
        self.assertIn("(ja)", review)
        self.assertEqual(prompts.role_system_prompt("executor", "ja"), prompts.role_system_prompt("executor", "en"))
        self.assertEqual(i18n.role_title("ja", "executor", "t"), "[IT EXEC] t")
        outbox = policy.decide(
            policy.PolicyInput(
                phase="await-reviewer",
                reviewer=policy.RoleObservation(busy=False, turn_ended=True),
                language="ja",
            )
        )
        ledger_append = next(a for a in outbox if isinstance(a, policy.LedgerAppend))
        self.assertTrue(ledger_append.text.startswith("NEEDS_ARBITER: open | "))


class ChineseContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.temp.name)
        self.config = _helpers.base_config(self.tmp)
        self.task = "修复登录超时并补测试；不得改动部署脚本。"
        self.run = make_run(self.config, _helpers.FakeBackend(self.config), self.tmp, language="zh-CN", task=self.task)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_executor_contract_is_chinese_and_carries_machine_fields(self) -> None:
        text = prompts.executor_prompt(self.run)
        self.assertIn("铁三角执行者合同", text)
        self.assertIn("主控下达的任务：", text)
        self.assertIn(self.task, text)  # arbiter task carried verbatim
        self.assertIn(self.run["run_id"], text)
        self.assertIn(self.run["ledger_path"], text)
        self.assertNotIn("IRON TRIANGLE EXECUTOR CONTRACT", text)
        self.assertNotIn("Task from the arbiter:", text)

    def test_reviewer_contract_is_chinese_with_intact_protocol_commands(self) -> None:
        bumped = dict(self.run, review_round=1)
        text = prompts.reviewer_prompt(bumped, BRIDGE, self.tmp / "runtime.json")
        self.assertIn("铁三角独立审查合同", text)
        self.assertIn("任务与主控约束：", text)
        self.assertIn(self.task, text)  # constraints carried verbatim
        self.assertIn("decide", text)
        self.assertIn("--decision needs-arbiter", text)
        self.assertIn("NEEDS_ARBITER", text)
        self.assertIn("ROUND_CLOSURE_PASS", text)
        self.assertIn(f"review-decision-1.json", text)
        self.assertNotIn("IRON TRIANGLE INDEPENDENT REVIEW CONTRACT", text)

    def test_role_system_prompts_are_chinese(self) -> None:
        self.assertEqual(prompts.role_system_prompt("executor", "zh-CN"), "你是铁三角运行中的执行者。负责实现与验证；不得自我验收。")
        self.assertEqual(prompts.role_system_prompt("reviewer", "zh-CN"), "你是铁三角运行中的独立审查者。必须亲自复现证据；不得仅凭汇报通过。")

    def test_default_titles_are_chinese(self) -> None:
        self.assertEqual(i18n.role_title("zh-CN", "executor", "修复登录"), "[铁三角·执行] 修复登录")
        self.assertEqual(i18n.role_title("zh-CN", "reviewer", "修复登录"), "[铁三角·审查] 修复登录")

    def test_notification_summary_is_chinese_with_machine_marker(self) -> None:
        title, message = i18n.notification("zh-CN", "it-x", "NEEDS_ARBITER")
        self.assertEqual(title, "铁三角")
        self.assertIn("NEEDS_ARBITER", message)
        self.assertIn("需要主控裁决", message)
        title, message = i18n.notification("zh-CN", "it-x", "ROUND_CLOSURE_PASS")
        self.assertIn("ROUND_CLOSURE_PASS", message)
        self.assertIn("本轮收口通过", message)

    def test_unknown_notification_kind_falls_back_to_marker_only(self) -> None:
        title, message = i18n.notification("zh-CN", "it-x", "FUTURE_KIND")
        self.assertIn("FUTURE_KIND", message)


class ChinesePolicyMessageTests(unittest.TestCase):
    def test_unresolved_dispatch_message_is_chinese_with_marker_intact(self) -> None:
        actions = policy.decide(
            policy.PolicyInput(phase="await-executor", pending_dispatch={"prompt_id": "p-1"}, language="zh-CN")
        )
        outbox = next(a for a in actions if isinstance(a, policy.Outbox))
        self.assertIn("未确认的派发 p-1", outbox.message)
        self.assertIn("--ack-prompt-id", outbox.message)

    def test_escalation_marker_stays_protocol_fixed(self) -> None:
        actions = policy.decide(
            policy.PolicyInput(
                phase="await-reviewer",
                reviewer=policy.RoleObservation(busy=False, turn_ended=True),
                language="zh-CN",
            )
        )
        ledger_append = next(a for a in actions if isinstance(a, policy.LedgerAppend))
        self.assertTrue(ledger_append.text.startswith("NEEDS_ARBITER: open | "))
        self.assertIn("检查审查者收据", ledger_append.text)

    def test_blocked_and_truncated_messages_are_chinese(self) -> None:
        blocked = policy.decide(
            policy.PolicyInput(
                phase="await-executor",
                executor=policy.RoleObservation(pending_interaction="permission"),
                language="zh-CN",
            )
        )
        self.assertTrue(any(isinstance(a, policy.Outbox) and "executor 会话" in a.message for a in blocked))
        truncated = policy.decide(
            policy.PolicyInput(
                phase="await-reviewer",
                reviewer=policy.RoleObservation(truncated=True),
                language="zh-CN",
            )
        )
        self.assertTrue(any(isinstance(a, policy.Outbox) and "事件流被截断" in a.message for a in truncated))

    def test_delivery_and_heartbeat_messages_are_chinese(self) -> None:
        inp = policy.PolicyInput(phase="await-executor", language="zh-CN")
        rejected = policy.apply_delivery(inp, "executor", policy.DELIVERY_REJECTED, "await-executor")
        self.assertTrue(any("被目标端拒绝" in a.message for a in rejected if isinstance(a, policy.Outbox)))
        unknown = policy.apply_delivery(inp, "reviewer", policy.DELIVERY_UNKNOWN, "await-reviewer")
        self.assertTrue(any("不盲目重试" in a.message for a in unknown if isinstance(a, policy.Outbox)))
        wake = policy.heartbeat(inp, 45.0, 30.0, False)
        self.assertTrue(any("双闲超时" in a.message for a in wake if isinstance(a, policy.Outbox)))

    def test_english_policy_messages_are_unchanged(self) -> None:
        actions = policy.decide(
            policy.PolicyInput(phase="await-reviewer", reviewer=policy.RoleObservation(busy=False, turn_ended=True))
        )
        ledger_append = next(a for a in actions if isinstance(a, policy.LedgerAppend))
        self.assertEqual(
            ledger_append.text,
            "NEEDS_ARBITER: open | Reviewer turn ended without a valid machine decision; "
            "affected line suspended. | inspect reviewer receipt and choose next action",
        )


class ChineseLaunchTests(unittest.TestCase):
    """End-to-end launch through cmd_launch with a fake backend."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.temp.name)
        self.config = _helpers.base_config(self.tmp)
        self.backend = _BackendShim(self.config)
        self._original = cli.SessionApiBackend
        cli.SessionApiBackend = lambda cfg: self.backend
        (self.tmp / "token").write_text("t", encoding="utf-8")

    def tearDown(self) -> None:
        cli.SessionApiBackend = self._original
        self.temp.cleanup()

    def _args(self, **overrides) -> argparse.Namespace:
        values = {
            "task": "实现有界任务切片。",
            "task_file": None,
            "cwd": str(self.tmp),
            "title": None,
            "executor_title": None,
            "reviewer_title": None,
            "executor_model": None,
            "reviewer_model": None,
            "executor_thinking": None,
            "reviewer_thinking": None,
            "executor_session": None,
            "reviewer_session": None,
            "permission_mode": None,
            "language": None,
            "dry_run": True,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_dry_run_plan_reports_language_and_chinese_titles(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.cmd_launch(self._args(language="zh-CN"), self.config, self.tmp / "runtime.json")
        plan = json.loads(buffer.getvalue())["plan"]
        self.assertEqual(plan["language"], "zh-CN")
        self.assertTrue(plan["executor_title"].startswith("[铁三角·执行] "))
        self.assertTrue(plan["reviewer_title"].startswith("[铁三角·审查] "))
        self.assertEqual(self.backend.sessions, {})  # dry run created nothing

    def test_explicit_titles_win_over_language_defaults(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.cmd_launch(
                self._args(language="zh-CN", executor_title="执行窗", reviewer_title="审查窗"),
                self.config,
                self.tmp / "runtime.json",
            )
        plan = json.loads(buffer.getvalue())["plan"]
        self.assertEqual(plan["executor_title"], "执行窗")
        self.assertEqual(plan["reviewer_title"], "审查窗")

    def test_launch_binds_language_and_dispatches_chinese_executor_contract(self) -> None:
        args = self._args(language="zh-CN", dry_run=False)
        cli.cmd_launch(args, self.config, self.tmp / "runtime.json")
        self.assertEqual(len(self.backend.dispatches), 1)
        text = self.backend.dispatches[0]["text"]
        self.assertIn("铁三角执行者合同", text)
        self.assertIn("实现有界任务切片。", text)

        runs = list(store.iter_runs(self.config))
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run["language"], "zh-CN")
        self.assertTrue(run["executor"]["title"].startswith("[铁三角·执行] "))
        self.assertTrue(run["reviewer"]["title"].startswith("[铁三角·审查] "))

        ledger = (store.run_dir(self.config, run["run_id"]) / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("# Iron Triangle Ledger —", ledger)
        self.assertIn("当前发起窗口即主控；执行与审查分别绑定。", ledger)
        self.assertIn("## R-1 arbiter launch", ledger)

    def test_english_launch_keeps_v02_titles_and_contract(self) -> None:
        args = self._args(task="Implement a bounded slice with tests.", dry_run=False)
        cli.cmd_launch(args, self.config, self.tmp / "runtime.json")
        text = self.backend.dispatches[0]["text"]
        self.assertTrue(text.startswith("IRON TRIANGLE EXECUTOR CONTRACT"))
        self.assertNotIn("Response language:", text)  # byte-compatible en path
        run = list(store.iter_runs(self.config))[0]
        self.assertEqual(run.get("language"), "en")
        self.assertTrue(run["executor"]["title"].startswith("[IT EXEC] "))

    def test_chinese_task_auto_selects_zh_without_any_manual_switch(self) -> None:
        # Gap-1 acceptance: no flag, no config key — the task's dominant
        # language alone decides, and both role titles inherit it.
        args = self._args(dry_run=True)  # default task is Chinese; no language set
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.cmd_launch(args, self.config, self.tmp / "runtime.json")
        plan = json.loads(buffer.getvalue())["plan"]
        self.assertEqual(plan["language"], "zh-CN")
        self.assertTrue(plan["executor_title"].startswith("[铁三角·执行] "))
        self.assertTrue(plan["reviewer_title"].startswith("[铁三角·审查] "))

    def test_config_level_language_applies_without_flag(self) -> None:
        self.config["language"] = "zh-CN"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.cmd_launch(self._args(), self.config, self.tmp / "runtime.json")
        plan = json.loads(buffer.getvalue())["plan"]
        self.assertEqual(plan["language"], "zh-CN")


class ChineseLedgerNarrationTests(unittest.TestCase):
    """resume / arbiter narration follows the language stored on the run."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.temp.name)
        self.config = _helpers.base_config(self.tmp)
        self.backend = _helpers.FakeBackend(self.config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_resume_ack_narrates_in_chinese(self) -> None:
        run = make_run(self.config, self.backend, self.tmp, language="zh-CN")
        run["phase"] = "transport-unknown"
        run["pending_dispatch"] = {
            "role": "executor",
            "prompt_id": "p-9",
            "baseline_seq": 0,
            "event_offset": 17,
        }
        store.save_run(self.config, run)
        args = argparse.Namespace(run_id=run["run_id"], ack_prompt_id="p-9", retry_new=False)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_resume(args, self.config)
        resumed = store.load_run(self.config, run["run_id"])
        self.assertEqual(resumed["executor_event_offset"], 17)
        ledger = (store.run_dir(self.config, run["run_id"]) / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("经人工查验确认已送达", ledger)
        self.assertIn("## R-1 arbiter recover", ledger)

    def test_resume_retry_narrates_in_chinese(self) -> None:
        run = make_run(self.config, self.backend, self.tmp, language="zh-CN")
        run["phase"] = "transport-unknown"
        run["pending_dispatch"] = {"role": "executor", "prompt_id": "p-9", "baseline_seq": 0}
        store.save_run(self.config, run)
        args = argparse.Namespace(run_id=run["run_id"], ack_prompt_id=None, retry_new=True)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_resume(args, self.config)
        ledger = (store.run_dir(self.config, run["run_id"]) / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("经人工确认未送达；已授权替换派发", ledger)

    def test_resume_narrates_in_english_for_pre_language_runs(self) -> None:
        run = make_run(self.config, self.backend, self.tmp)
        run["phase"] = "transport-unknown"
        run["pending_dispatch"] = {"role": "executor", "prompt_id": "p-9", "baseline_seq": 0}
        store.save_run(self.config, run)
        args = argparse.Namespace(run_id=run["run_id"], ack_prompt_id="p-9", retry_new=False)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_resume(args, self.config)
        ledger = (store.run_dir(self.config, run["run_id"]) / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("confirmed delivered by human inspection", ledger)

    def test_arbiter_stop_default_message_is_chinese(self) -> None:
        run = make_run(self.config, self.backend, self.tmp, language="zh-CN")
        run["phase"] = "await-executor"
        store.save_run(self.config, run)
        args = argparse.Namespace(run_id=run["run_id"], decision="stop", message=None, message_file=None)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_arbiter(args, self.config, self.tmp / "runtime.json")
        ledger = (store.run_dir(self.config, run["run_id"]) / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("主控停止了本次运行。", ledger)
        self.assertIn("## R-1 arbiter stop", ledger)
        self.assertIn("- Result: suspended", ledger)

    def test_arbiter_accept_default_closure_summary_is_chinese(self) -> None:
        run = make_run(self.config, self.backend, self.tmp, language="zh-CN")
        run["phase"] = "await-final-acceptance"
        store.save_run(self.config, run)
        args = argparse.Namespace(run_id=run["run_id"], decision="accept", message=None, message_file=None)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_arbiter(args, self.config, self.tmp / "runtime.json")
        ledger = (store.run_dir(self.config, run["run_id"]) / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("主控接受经独立复现的收口证据。", ledger)
        self.assertIn("## R-1 arbiter final-acceptance", ledger)
        self.assertIn("- Result: pass", ledger)

    def test_arbiter_accept_english_default_unchanged(self) -> None:
        run = make_run(self.config, self.backend, self.tmp)
        run["phase"] = "await-final-acceptance"
        store.save_run(self.config, run)
        args = argparse.Namespace(run_id=run["run_id"], decision="accept", message=None, message_file=None)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_arbiter(args, self.config, self.tmp / "runtime.json")
        ledger = (store.run_dir(self.config, run["run_id"]) / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("Arbiter accepts the independently reproduced closure evidence.", ledger)

    def test_arbiter_can_continue_instead_of_accepting_closure(self) -> None:
        run = make_run(self.config, self.backend, self.tmp, language="zh-CN")
        run["phase"] = "await-final-acceptance"
        store.save_run(self.config, run)
        args = argparse.Namespace(
            run_id=run["run_id"],
            decision="continue",
            message="补齐主控发现的最新验收缺口。",
            message_file=None,
        )
        with mock.patch.object(cli, "SessionApiBackend", return_value=self.backend):
            with contextlib.redirect_stdout(io.StringIO()):
                cli.cmd_arbiter(args, self.config, self.tmp / "runtime.json")
        resumed = store.load_run(self.config, run["run_id"])
        self.assertEqual(resumed["phase"], "await-executor")
        self.assertEqual(self.backend.dispatches[-1]["role"], "executor")
        self.assertIn("补齐主控发现的最新验收缺口。", self.backend.dispatches[-1]["text"])


class MidRunLanguageSwitchTests(unittest.TestCase):
    """A registered mid-run switch applies to both roles together."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.temp.name)
        self.config = _helpers.base_config(self.tmp)
        self.backend = _BackendShim(self.config)
        self._original = cli.SessionApiBackend
        cli.SessionApiBackend = lambda cfg: self.backend

    def tearDown(self) -> None:
        cli.SessionApiBackend = self._original
        self.temp.cleanup()

    def test_continue_registers_switch_and_both_roles_inherit_it(self) -> None:
        run = make_run(self.config, self.backend, self.tmp, language="zh-CN")
        run["phase"] = "await-arbiter"
        store.save_run(self.config, run)
        args = argparse.Namespace(
            run_id=run["run_id"],
            decision="continue",
            message="下一切片：修复登录超时。",
            message_file=None,
            language="ja",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_arbiter(args, self.config, self.tmp / "runtime.json")

        resumed = store.load_run(self.config, run["run_id"])
        self.assertEqual(resumed["language"], "ja")

        ledger = (store.run_dir(self.config, run["run_id"]) / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("回复语言已切换：zh-CN -> ja", ledger)
        self.assertIn("执行者与审查者共同继承", ledger)

        # The raw slice message itself is unchanged...
        self.assertEqual([d for d in self.backend.dispatches if d["role"] == "executor"][-1]["text"], "下一切片：修复登录超时。")
        # ...but every later role contract carries the new response_language.
        contract = prompts.executor_prompt(resumed)
        self.assertIn("Response language: write all of your natural-language replies in Japanese (ja).", contract)
        resumed["review_round"] = 1
        review = prompts.reviewer_prompt(resumed, BRIDGE, self.tmp / "runtime.json")
        self.assertIn("(ja)", review)


class WatcherLanguagePropagationTests(unittest.TestCase):
    def test_watcher_dispatches_chinese_reviewer_contract(self) -> None:
        temp = tempfile.TemporaryDirectory()
        try:
            tmp = pathlib.Path(temp.name)
            config = _helpers.base_config(tmp)
            backend = _helpers.FakeBackend(config)
            run = make_run(config, backend, tmp, language="zh-CN", dispatch_now=True)
            backend.end_turn(run["executor"]["session_id"])
            execute_actions(
                config=config,
                config_path=tmp / "runtime.json",
                bridge_path=BRIDGE,
                run=run,
                backend=backend,
                actions=[policy.Dispatch("reviewer", "reviewer-contract")],
                expected_phase="await-reviewer",
            )
            reviewer_text = backend.dispatches[-1]["text"]
            self.assertIn("铁三角独立审查合同", reviewer_text)
            self.assertIn("审查轮次：1", reviewer_text)
        finally:
            temp.cleanup()


class ModelReceiptTests(unittest.TestCase):
    """Launch persists honest model/effort/independence receipts (R-5 audit).

    The receipt must never claim an applied value was verified on the
    destination while no adapter read-back exists: ``readback`` stays
    ``unreadback`` and any fallback out of a fuzzy resolution is disclosed.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.temp.name)
        self.config = _helpers.base_config(self.tmp)
        self.backend = _BackendShim(self.config)
        self._original = cli.SessionApiBackend
        cli.SessionApiBackend = lambda cfg: self.backend
        (self.tmp / "token").write_text("t", encoding="utf-8")

    def tearDown(self) -> None:
        cli.SessionApiBackend = self._original
        self.temp.cleanup()

    def _args(self, **overrides) -> argparse.Namespace:
        values = {
            "task": "Bounded receipt task.",
            "task_file": None,
            "cwd": str(self.tmp),
            "title": None,
            "executor_title": None,
            "reviewer_title": None,
            "executor_model": None,
            "reviewer_model": None,
            "executor_thinking": None,
            "reviewer_thinking": None,
            "executor_session": None,
            "reviewer_session": None,
            "permission_mode": None,
            "language": None,
            "dry_run": True,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def _launch(self, **overrides) -> dict:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.cmd_launch(self._args(**overrides), self.config, self.tmp / "runtime.json")
        return json.loads(buffer.getvalue())

    def _status_entry(self, run_id: str) -> dict:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.cmd_status(argparse.Namespace(run_id=run_id, pending=False), self.config)
        return json.loads(buffer.getvalue())[0]

    def test_default_launch_records_adapter_defaults_and_unreadback(self) -> None:
        payload = self._launch(dry_run=False)
        receipt = payload["executor"]["model_receipt"]
        self.assertIsNone(receipt["requested_model"])
        self.assertEqual(receipt["applied_model"], "executor-a")
        self.assertEqual(receipt["model_source"], "adapter-default")
        self.assertFalse(receipt["fallback_occurred"])
        self.assertIsNone(receipt["requested_effort"])
        self.assertIsNone(receipt["applied_effort"])
        self.assertEqual(receipt["effort_source"], "none")
        self.assertEqual(receipt["readback"], "unreadback")  # never claims verified
        self.assertEqual(payload["independence"], {"level": "separate-sessions"})

        # The same receipt is durable and surfaced by status.
        run = list(store.iter_runs(self.config))[0]
        self.assertEqual(run["executor"]["model_receipt"], receipt)
        self.assertEqual(run["independence"], {"level": "separate-sessions"})
        entry = self._status_entry(run["run_id"])
        self.assertEqual(entry["executor"]["model_receipt"], receipt)
        self.assertEqual(entry["reviewer"]["model_receipt"]["applied_model"], "reviewer-b")
        self.assertEqual(entry["independence"], {"level": "separate-sessions"})

    def test_explicit_names_and_flags_are_recorded_without_fallback(self) -> None:
        payload = self._launch(executor_model="Executor A", executor_thinking="high", dry_run=False)
        receipt = payload["executor"]["model_receipt"]
        self.assertEqual(receipt["requested_model"], "Executor A")
        self.assertEqual(receipt["applied_model"], "executor-a")
        self.assertEqual(receipt["model_source"], "explicit")
        self.assertFalse(receipt["fallback_occurred"])  # display name is an exact naming
        self.assertEqual(receipt["requested_effort"], "high")
        self.assertEqual(receipt["applied_effort"], "high")
        self.assertEqual(receipt["effort_source"], "flag")

    def test_fuzzy_resolution_is_disclosed_as_fallback(self) -> None:
        payload = self._launch(executor_model="executor", dry_run=False)
        receipt = payload["executor"]["model_receipt"]
        self.assertEqual(receipt["applied_model"], "executor-a")
        self.assertTrue(receipt["fallback_occurred"])

    def test_effort_source_precedence_flag_adapter_then_model_default(self) -> None:
        self.config["adapters"]["kimi-code"]["default_reviewer_thinking"] = "mid"
        payload = self._launch(dry_run=False)
        reviewer = payload["reviewer"]["model_receipt"]
        self.assertEqual(reviewer["effort_source"], "adapter-config")
        self.assertEqual(reviewer["applied_effort"], "mid")

        self.backend.models_catalog[0]["default_effort"] = "low"
        payload = self._launch(dry_run=False)  # second run, adapter default only set for reviewer
        executor = payload["executor"]["model_receipt"]
        self.assertEqual(executor["effort_source"], "model-default")
        self.assertEqual(executor["applied_effort"], "low")


class TransportUnknownRecoveryTests(unittest.TestCase):
    """Event-cursor recovery: transport-unknown → manual ack → turn.ended consumed.

    Field incident: the first dispatch returned ``unknown``; after a human ack
    the executor's ``turn.ended`` landed in the durable event stream, but the
    recovery record had no ``event_offset`` and Kimi's summary ``last_seq``
    stayed 0 — so neither detector could fire and the reviewer was never
    dispatched. The patch persists the pre-dispatch offset inside
    ``pending_dispatch`` and restores it on ack; legacy records without the
    field must not gain a guessed cursor.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.temp.name)
        self.config = _helpers.base_config(self.tmp)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _resume_ack(self, run: dict) -> None:
        args = argparse.Namespace(run_id=run["run_id"], ack_prompt_id="it_p", retry_new=False)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_resume(args, self.config)

    def test_unknown_dispatch_persists_offset_and_ack_restores_reviewer_dispatches_once(self) -> None:
        backend = _helpers.FakeBackend(self.config, fail_mode="unknown")
        run = make_run(self.config, backend, self.tmp)
        execute_actions(
            config=self.config,
            config_path=self.tmp / "runtime.json",
            bridge_path=BRIDGE,
            run=run,
            backend=backend,
            actions=[policy.Dispatch("executor", "executor-contract")],
            expected_phase="await-executor",
        )
        # Fail-closed state keeps the pending dispatch with its pre-dispatch cursor.
        self.assertEqual(run["phase"], "transport-unknown")
        self.assertIsNotNone(run["pending_dispatch"])
        self.assertEqual(run["pending_dispatch"]["event_offset"], 0)  # empty stream size
        store.save_run(self.config, run)

        backend.fail_mode = None  # later dispatches succeed
        prompt_id = run["pending_dispatch"]["prompt_id"]
        args = argparse.Namespace(run_id=run["run_id"], ack_prompt_id=prompt_id, retry_new=False)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_resume(args, self.config)

        resumed = store.load_run(self.config, run["run_id"])
        self.assertEqual(resumed["phase"], "await-executor")
        self.assertIsNone(resumed["pending_dispatch"])
        self.assertEqual(resumed["executor_event_offset"], 0)  # restored, not guessed

        # The executor turn ends in the durable event stream while Kimi's
        # summary sequence stays at the baseline (the exact field condition).
        session_id = resumed["executor"]["session_id"]
        backend.end_turn(session_id)
        backend.sessions[session_id]["last_seq"] = resumed["executor_baseline_seq"]

        from iron_triangle.runner import step_run

        changed = step_run(
            config=self.config,
            config_path=self.tmp / "runtime.json",
            bridge_path=BRIDGE,
            run=resumed,
            backend=backend,
        )
        self.assertTrue(changed)
        self.assertEqual(resumed["phase"], "await-reviewer")
        reviewer_dispatches = [d for d in backend.dispatches if d["role"] == "reviewer"]
        self.assertEqual(len(reviewer_dispatches), 1)

        # A second watcher pass must not duplicate the reviewer dispatch.
        step_run(
            config=self.config,
            config_path=self.tmp / "runtime.json",
            bridge_path=BRIDGE,
            run=resumed,
            backend=backend,
        )
        reviewer_dispatches = [d for d in backend.dispatches if d["role"] == "reviewer"]
        self.assertEqual(len(reviewer_dispatches), 1)

    def test_legacy_pending_without_event_offset_is_not_guessed(self) -> None:
        backend = _helpers.FakeBackend(self.config)
        run = make_run(self.config, backend, self.tmp)
        run["phase"] = "transport-unknown"
        run["pending_dispatch"] = {"role": "executor", "prompt_id": "it_p", "baseline_seq": 0}
        store.save_run(self.config, run)
        self._resume_ack(run)
        resumed = store.load_run(self.config, run["run_id"])
        self.assertNotIn("executor_event_offset", resumed)

    def test_legacy_pending_without_contract_round_is_not_guessed(self) -> None:
        """A pre-contract-round pending record must not gain a guessed bump."""
        run = make_run(self.config, _helpers.FakeBackend(self.config), self.tmp)
        run["phase"] = "transport-unknown"
        run["pending_dispatch"] = {"role": "reviewer", "prompt_id": "it_p", "baseline_seq": 0}
        store.save_run(self.config, run)
        self._resume_ack(run)
        resumed = store.load_run(self.config, run["run_id"])
        self.assertEqual(resumed["phase"], "await-reviewer")
        self.assertEqual(resumed["review_round"], 0)

    def test_ack_after_unknown_reviewer_dispatch_reconciles_review_round(self) -> None:
        """Root-cause regression: after a transport-unknown reviewer dispatch,
        the manual ack must reconcile the durable review_round with the
        contract that was actually sent, so the reviewer's legal decision can
        decide the same contract instead of failing round validation.

        Field failure chain: the reviewer contract is built for round N+1, but
        the queued durable bump is intentionally dropped when delivery lands in
        transport-unknown; ``resume --ack-prompt-id`` restored delivery
        bookkeeping only, so ``decide --review-round N+1`` was rejected forever.
        """
        from iron_triangle.runner import step_run

        backend = _helpers.FakeBackend(self.config)
        run = make_run(self.config, backend, self.tmp, dispatch_now=True)
        self.assertEqual(run["phase"], "await-executor")

        # The executor turn ends; the reviewer dispatch hits an unknown state.
        backend.fail_mode = "unknown"
        backend.end_turn(run["executor"]["session_id"])
        step_run(
            config=self.config,
            config_path=self.tmp / "runtime.json",
            bridge_path=BRIDGE,
            run=run,
            backend=backend,
        )
        self.assertEqual(run["phase"], "transport-unknown")
        self.assertEqual(run["review_round"], 0)  # fail-closed: the bump was skipped
        pending = run["pending_dispatch"]
        self.assertEqual(pending["role"], "reviewer")
        reviewer_text = [d for d in backend.dispatches if d["role"] == "reviewer"][-1]["text"]
        self.assertIn("--review-round 1", reviewer_text)  # the sent contract references round 1

        store.save_run(self.config, run)
        backend.fail_mode = None  # human verified the destination window
        args = argparse.Namespace(run_id=run["run_id"], ack_prompt_id=pending["prompt_id"], retry_new=False)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_resume(args, self.config)

        resumed = store.load_run(self.config, run["run_id"])
        self.assertEqual(resumed["phase"], "await-reviewer")
        self.assertEqual(resumed["review_round"], 1)  # reconciled with the sent contract

        # The reviewer's per-contract decision must be accepted...
        decide_args = argparse.Namespace(
            run_id=run["run_id"],
            review_round=1,
            decision="closure-pass",
            ledger_sequence="R-2",
            message="independently reproduced the focused checks",
            message_file=None,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_decide(decide_args, self.config)

        # ...and the same contract consumes it instead of escalating.
        backend.end_turn(resumed["reviewer"]["session_id"])
        changed = step_run(
            config=self.config,
            config_path=self.tmp / "runtime.json",
            bridge_path=BRIDGE,
            run=resumed,
            backend=backend,
        )
        self.assertTrue(changed)
        self.assertEqual(resumed["phase"], "await-final-acceptance")
        outbox = [json.loads(line) for line in (store.state_dir(self.config) / "arbiter-outbox.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(item["kind"] == "ROUND_CLOSURE_PASS" for item in outbox))


if __name__ == "__main__":
    unittest.main()
