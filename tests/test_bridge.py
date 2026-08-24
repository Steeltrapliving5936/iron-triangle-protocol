from __future__ import annotations

import http.server
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse


ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts" / "iron_triangle_bridge.py"


class FakeState:
    models = [
        {
            "provider": "provider-a",
            "model": "provider-a/executor-v1",
            "display_name": "Executor V1",
            "support_efforts": ["low", "high"],
            "default_effort": "high",
        },
        {
            "provider": "provider-b",
            "model": "provider-b/reviewer-v1",
            "display_name": "Reviewer V1",
            "support_efforts": ["low", "high"],
            "default_effort": "high",
        },
    ]
    sessions: dict[str, dict] = {}
    prompts: list[dict] = []
    prompt_status = "running"
    prompt_contract_statuses = ["running", "queued", "blocked"]
    approvals: dict[str, list[dict]] = {}
    aborts: list[dict] = []
    abort_active = True
    abort_inactive_code = 40903


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def reply(self, data: object, status: int = 200) -> None:
        body = json.dumps({"code": 0, "msg": "success", "data": data, "request_id": "test"}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def reply_code(self, code: int, data: object, status: int = 200) -> None:
        body = json.dumps({"code": code, "msg": "test", "data": data, "request_id": "test"}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def reply_raw(self, data: object, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/openapi.json":
            self.reply_raw(
                {
                    "openapi": "3.0.0",
                    "paths": {
                        "/api/v1/sessions/{session_id}/prompts": {
                            "post": {
                                "responses": {
                                    "200": {
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "properties": {
                                                        "data": {
                                                            "properties": {
                                                                "status": {
                                                                    "type": "string",
                                                                    "enum": FakeState.prompt_contract_statuses,
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            )
            return
        if path == "/api/v1/models":
            self.reply({"items": FakeState.models})
            return
        if path == "/api/v1/sessions":
            self.reply({"items": list(FakeState.sessions.values()), "has_more": False})
            return
        if path.endswith("/approvals"):
            session_id = path.split("/")[4]
            self.reply({"items": FakeState.approvals.get(session_id, [])})
            return
        if path.startswith("/api/v1/sessions/"):
            session_id = path.split("/")[4]
            self.reply(FakeState.sessions[session_id])
            return
        self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/v1/sessions":
            session_id = f"s-{len(FakeState.sessions) + 1}"
            session = {
                "id": session_id,
                "title": body["title"],
                "busy": False,
                "last_seq": 0,
                "pending_interaction": "none",
                "metadata": body["metadata"],
                "agent_config": body["agent_config"],
            }
            FakeState.sessions[session_id] = session
            self.reply(session)
            return
        if path.endswith(":abort") and "/prompts/" in path:
            session_id = path.split("/")[4]
            prompt_id = urllib.parse.unquote(path.rsplit("/", 1)[1][:-len(":abort")])
            FakeState.aborts.append({"session_id": session_id, "prompt_id": prompt_id})
            FakeState.sessions[session_id]["busy"] = False
            if FakeState.abort_active:
                self.reply({"aborted": True, "at_seq": 1})
            else:
                data = {"aborted": False} if FakeState.abort_inactive_code == 40903 else None
                self.reply_code(FakeState.abort_inactive_code, data)
            return
        if "/approvals/" in path:
            session_id = path.split("/")[4]
            approval_id = urllib.parse.unquote(path.rsplit("/", 1)[1])
            items = FakeState.approvals.get(session_id, [])
            FakeState.approvals[session_id] = [item for item in items if item.get("approval_id") != approval_id]
            self.reply({"resolved": True, "resolved_at": "now"})
            return
        if path.endswith("/prompts"):
            session_id = path.split("/")[4]
            FakeState.prompts.append({"session_id": session_id, "body": body})
            FakeState.sessions[session_id]["busy"] = True
            self.reply(
                {
                    "prompt_id": body["prompt_id"],
                    "user_message_id": "m-1",
                    "status": FakeState.prompt_status,
                    "content": body["content"],
                    "created_at": "now",
                }
            )
            return
        self.send_error(404)


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        FakeState.sessions = {}
        FakeState.prompts = []
        FakeState.prompt_status = "running"
        FakeState.prompt_contract_statuses = ["running", "queued", "blocked"]
        FakeState.approvals = {}
        FakeState.aborts = []
        FakeState.abort_active = True
        FakeState.abort_inactive_code = 40903
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=3)

    def setUp(self) -> None:
        FakeState.sessions = {}
        FakeState.prompts = []
        FakeState.prompt_status = "running"
        FakeState.prompt_contract_statuses = ["running", "queued", "blocked"]
        FakeState.abort_active = True
        FakeState.abort_inactive_code = 40903
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        token = self.root / "token"
        token.write_text("test-token", encoding="utf-8")
        self.events = self.root / "events"
        self.events.mkdir()
        self.config = self.root / "runtime.json"
        self.config.write_text(
            json.dumps(
                {
                    "adapters": {
                        "kimi-code": {
                            "base_url": f"http://127.0.0.1:{self.server.server_port}/api/v1",
                            "token_file": str(token),
                            "event_dir": str(self.events),
                            "default_executor_model": "provider-a/executor-v1",
                            "default_reviewer_model": "Reviewer V1",
                            "permission_mode": "auto",
                        }
                    },
                    "state_dir": str(self.root / "state"),
                    "notifications": False,
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_bridge(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BRIDGE), "--config", str(self.config), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_preflight_resolves_private_defaults(self) -> None:
        result = self.run_bridge("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["defaults"]["executor"], "provider-a/executor-v1")
        self.assertEqual(payload["defaults"]["reviewer"], "provider-b/reviewer-v1")
        self.assertEqual(payload["prompt_contract"]["statuses"], ["blocked", "queued", "running"])
        self.assertTrue(payload["prompt_contract"]["compatible"])

    def test_preflight_fails_closed_on_unknown_prompt_status_contract(self) -> None:
        FakeState.prompt_contract_statuses = ["running", "teleported"]
        result = self.run_bridge("preflight")
        self.assertEqual(result.returncode, 2, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["prompt_contract"]["compatible"])

    def test_launch_fails_closed_before_any_dispatch_on_unknown_contract(self) -> None:
        FakeState.prompt_contract_statuses = ["running", "teleported"]
        result = self.run_bridge(
            "launch",
            "--cwd",
            str(self.root),
            "--task",
            "Must not reach the destination.",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("refusing to launch", result.stderr)
        self.assertIn("teleported", result.stderr)
        self.assertEqual(FakeState.sessions, {})
        self.assertEqual(FakeState.prompts, [])

    def test_watcher_contract_gate_suspends_before_reviewer_dispatch(self) -> None:
        launched = self.run_bridge(
            "launch",
            "--cwd",
            str(self.root),
            "--task",
            "Executor turn completes, then the contract changes.",
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        run_id = json.loads(launched.stdout)["run_id"]
        run_path = self.root / "state" / "runs" / run_id / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        executor_id = run["executor"]["session_id"]
        (self.events / f"{executor_id}.jsonl").write_text(
            json.dumps({"envelope": {"type": "turn.ended", "payload": {"turnId": 0}}}) + "\n",
            encoding="utf-8",
        )
        FakeState.sessions[executor_id]["busy"] = False
        FakeState.prompt_contract_statuses = ["running", "teleported"]
        watched = self.run_bridge("watch-once")
        self.assertEqual(watched.returncode, 0, watched.stderr)
        run = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(run["phase"], "suspended")
        self.assertEqual(run["suspension_reason"], "dispatch-rejected")
        events = [
            json.loads(line)
            for line in (self.root / "state" / "runs" / run_id / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertTrue(
            any(
                item.get("kind") == "dispatch_rejected" and "contract-gate" in str(item.get("detail"))
                for item in events
            )
        )
        self.assertEqual(len(FakeState.prompts), 1, "reviewer prompt must not be sent")

    def test_rejected_dispatch_stays_suspended_without_redispatch_on_next_watch(self) -> None:
        launched = self.run_bridge(
            "launch",
            "--cwd",
            str(self.root),
            "--task",
            "Reject one dispatch, then hold the line.",
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        run_id = json.loads(launched.stdout)["run_id"]
        run_path = self.root / "state" / "runs" / run_id / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        executor_id = run["executor"]["session_id"]
        (self.events / f"{executor_id}.jsonl").write_text(
            json.dumps({"envelope": {"type": "turn.ended", "payload": {"turnId": 0}}}) + "\n",
            encoding="utf-8",
        )
        FakeState.sessions[executor_id]["busy"] = False
        FakeState.prompt_contract_statuses = ["running", "teleported"]
        first = self.run_bridge("watch-once")
        self.assertEqual(first.returncode, 0, first.stderr)
        run = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(run["phase"], "suspended")
        self.assertEqual(run["suspension_reason"], "dispatch-rejected")
        self.assertIsNone(run["pending_dispatch"], "a definitely-rejected dispatch has no in-flight record")

        # With the contract healthy again, a later watcher pass must keep the
        # suspended verdict: no redispatch, no transport-unknown escalation.
        FakeState.prompt_contract_statuses = ["running", "queued", "blocked"]
        second = self.run_bridge("watch-once")
        self.assertEqual(second.returncode, 0, second.stderr)
        run = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(run["phase"], "suspended")
        self.assertEqual(run["suspension_reason"], "dispatch-rejected")
        self.assertIsNone(run["pending_dispatch"])
        self.assertEqual(len(FakeState.prompts), 1, "no role may be redispatched after rejection")

    def test_launch_creates_two_roles_and_dispatches_only_executor(self) -> None:
        result = self.run_bridge(
            "launch",
            "--cwd",
            str(self.root),
            "--task",
            "Implement the bounded test task.",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["launched"])
        self.assertEqual(len(FakeState.sessions), 2)
        self.assertEqual(len(FakeState.prompts), 1)
        self.assertEqual(FakeState.prompts[0]["body"]["model"], "provider-a/executor-v1")
        run_path = self.root / "state" / "runs" / payload["run_id"] / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(run["phase"], "await-executor")
        self.assertEqual(run["arbiter"]["binding"], "originating-control-window")
        self.assertEqual(run["last_delivery"]["detail"], "remote_status=running")

    def test_all_documented_prompt_ack_states_are_accepted(self) -> None:
        for status in ("running", "queued", "blocked"):
            with self.subTest(status=status):
                FakeState.sessions = {}
                FakeState.prompts = []
                FakeState.prompt_status = status
                result = self.run_bridge(
                    "launch",
                    "--cwd",
                    str(self.root),
                    "--task",
                    f"Exercise {status} acknowledgement.",
                    "--allow-concurrent",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                run_path = self.root / "state" / "runs" / payload["run_id"] / "run.json"
                run = json.loads(run_path.read_text(encoding="utf-8"))
                self.assertEqual(run["phase"], "await-executor")
                self.assertEqual(run["last_delivery"]["detail"], f"remote_status={status}")

    def test_second_run_in_same_workspace_fails_closed_before_new_sessions(self) -> None:
        first = self.run_bridge("launch", "--cwd", str(self.root), "--task", "First run owns workspace.")
        self.assertEqual(first.returncode, 0, first.stderr)
        sessions_before = len(FakeState.sessions)
        prompts_before = len(FakeState.prompts)
        second = self.run_bridge("launch", "--cwd", str(self.root), "--task", "Second run must not start.")
        self.assertEqual(second.returncode, 2)
        self.assertIn("non-terminal Iron Triangle run", second.stderr)
        self.assertEqual(len(FakeState.sessions), sessions_before)
        self.assertEqual(len(FakeState.prompts), prompts_before)

    def test_allow_concurrent_is_an_explicit_escape_hatch(self) -> None:
        first = self.run_bridge("launch", "--cwd", str(self.root), "--task", "First concurrent run.")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_bridge(
            "launch",
            "--cwd",
            str(self.root),
            "--task",
            "Explicitly authorized concurrent run.",
            "--allow-concurrent",
        )
        self.assertEqual(second.returncode, 0, second.stderr)

    def test_dry_run_does_not_create_sessions(self) -> None:
        result = self.run_bridge(
            "launch",
            "--cwd",
            str(self.root),
            "--task",
            "Dry run only.",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(FakeState.sessions, {})
        self.assertEqual(FakeState.prompts, [])

    def test_stop_aborts_the_exact_run_owned_prompt(self) -> None:
        launched = self.run_bridge(
            "launch", "--cwd", str(self.root), "--task", "Stop this exact prompt."
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        run_id = json.loads(launched.stdout)["run_id"]
        stopped = self.run_bridge("arbiter", "--run-id", run_id, "--decision", "stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertEqual(len(FakeState.aborts), 1)
        run_path = self.root / "state" / "runs" / run_id / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(run["phase"], "stopped")
        self.assertEqual(run["stop_receipts"][0]["status"], "aborted")
        self.assertIsNone(run["pending_dispatch"])
        watched = self.run_bridge("watch-once")
        self.assertEqual(watched.returncode, 0, watched.stderr)
        run = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(run["phase"], "stopped")

    def test_stop_treats_runtime_not_active_codes_as_already_terminal(self) -> None:
        for code in (40903, 40402):
            with self.subTest(code=code):
                launched = self.run_bridge(
                    "launch",
                    "--cwd",
                    str(self.root),
                    "--task",
                    f"This prompt already ended before stop ({code}).",
                    "--allow-concurrent",
                )
                self.assertEqual(launched.returncode, 0, launched.stderr)
                run_id = json.loads(launched.stdout)["run_id"]
                FakeState.abort_active = False
                FakeState.abort_inactive_code = code
                stopped = self.run_bridge("arbiter", "--run-id", run_id, "--decision", "stop")
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                run_path = self.root / "state" / "runs" / run_id / "run.json"
                run = json.loads(run_path.read_text(encoding="utf-8"))
                self.assertEqual(run["phase"], "stopped")
                self.assertEqual(run["stop_receipts"][0]["status"], "already-terminal")

    def test_approvals_are_listed_and_resolved_without_ui_control(self) -> None:
        launched = self.run_bridge(
            "launch", "--cwd", str(self.root), "--task", "Resolve one approval through the API."
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        payload = json.loads(launched.stdout)
        run_path = self.root / "state" / "runs" / payload["run_id"] / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        session_id = run["executor"]["session_id"]
        FakeState.approvals[session_id] = [
            {
                "approval_id": "approval-1",
                "session_id": session_id,
                "tool_call_id": "tool-1",
                "tool_name": "shell",
                "action": "run command",
                "tool_input_display": {"command": "safe-test"},
                "created_at": "now",
                "expires_at": "later",
            }
        ]
        listed = self.run_bridge("approvals", "--run-id", payload["run_id"], "--role", "executor")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)[0]["approval_id"], "approval-1")
        resolved = self.run_bridge(
            "resolve-approval",
            "--run-id",
            payload["run_id"],
            "--role",
            "executor",
            "--approval-id",
            "approval-1",
            "--decision",
            "approved",
        )
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertEqual(FakeState.approvals[session_id], [])

    def test_terminal_event_dispatches_reviewer_when_summary_sequence_stays_zero(self) -> None:
        result = self.run_bridge(
            "launch",
            "--cwd",
            str(self.root),
            "--task",
            "Complete one executor turn.",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        run_path = self.root / "state" / "runs" / payload["run_id"] / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        executor_id = run["executor"]["session_id"]
        event = {"envelope": {"type": "turn.ended", "payload": {"turnId": 0}}}
        (self.events / f"{executor_id}.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
        FakeState.sessions[executor_id]["busy"] = False

        watched = self.run_bridge("watch-once")
        self.assertEqual(watched.returncode, 0, watched.stderr)
        run = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(run["phase"], "await-reviewer")
        self.assertEqual(len(FakeState.prompts), 2)
        self.assertEqual(FakeState.prompts[1]["body"]["model"], "provider-b/reviewer-v1")

    def test_ambiguous_model_fails_closed(self) -> None:
        result = self.run_bridge(
            "launch",
            "--cwd",
            str(self.root),
            "--task",
            "Do not run.",
            "--executor-model",
            "v1",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("ambiguous", result.stderr)

    def test_executor_and_reviewer_cannot_share_one_window(self) -> None:
        FakeState.sessions["s-existing"] = {
            "id": "s-existing",
            "title": "Shared window",
            "busy": False,
            "last_seq": 0,
            "pending_interaction": "none",
            "metadata": {"cwd": str(self.root)},
            "agent_config": {},
        }
        result = self.run_bridge(
            "launch",
            "--cwd",
            str(self.root),
            "--task",
            "Do not run.",
            "--executor-session",
            "Shared window",
            "--reviewer-session",
            "Shared window",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("distinct sessions", result.stderr)
        self.assertEqual(FakeState.prompts, [])


if __name__ == "__main__":
    unittest.main()
