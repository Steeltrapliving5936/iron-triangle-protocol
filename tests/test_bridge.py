from __future__ import annotations

import http.server
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest


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

    def do_GET(self) -> None:
        if self.path == "/api/v1/models":
            self.reply({"items": FakeState.models})
            return
        if self.path == "/api/v1/sessions":
            self.reply({"items": list(FakeState.sessions.values()), "has_more": False})
            return
        if self.path.startswith("/api/v1/sessions/"):
            session_id = self.path.split("/")[4]
            self.reply(FakeState.sessions[session_id])
            return
        self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        if self.path == "/api/v1/sessions":
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
        if self.path.endswith("/prompts"):
            session_id = self.path.split("/")[4]
            FakeState.prompts.append({"session_id": session_id, "body": body})
            self.reply(
                {
                    "prompt_id": body["prompt_id"],
                    "user_message_id": "m-1",
                    "status": "accepted",
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
