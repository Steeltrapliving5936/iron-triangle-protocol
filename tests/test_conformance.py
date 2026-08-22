"""Adapter conformance tests (docs/platform-adapters.md section 11).

Exercises the real runner + store + policy stack over an in-memory backend,
including restart and replay behavior.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import _helpers  # noqa: F401  (sys.path bootstrap)

from _helpers import FakeBackend, base_config, make_run

from iron_triangle import policy, store
from iron_triangle.runner import watch_once


class ConformanceBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.config = base_config(self.root)
        (self.root / "events").mkdir()
        self.backend = FakeBackend(self.config)
        self.bridge = _helpers.ROOT / "scripts" / "iron_triangle_bridge.py"
        self.config_path = self.root / "runtime.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def watch(self) -> int:
        from iron_triangle.runner import idle_limit_from_config

        return watch_once(
            self.config,
            self.config_path,
            self.bridge,
            backend=self.backend,
            idle_limit_seconds=idle_limit_from_config(self.config),
        )

    def load_run(self, run: dict) -> dict:
        return store.load_run(self.config, run["run_id"])

    def outbox(self) -> list[dict]:
        path = pathlib.Path(self.config["state_dir"]) / "arbiter-outbox.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def reviewer_dispatch_count(self) -> int:
        return sum(1 for d in self.backend.dispatches if d["role"] == "reviewer")


class OneEventOneDispatchTests(ConformanceBase):
    def test_one_terminal_event_produces_exactly_one_reviewer_dispatch(self):
        run = make_run(self.config, self.backend, self.root)
        self.backend.end_turn(run["executor"]["session_id"])
        self.assertEqual(self.watch(), 1)
        run = self.load_run(run)
        self.assertEqual(run["phase"], "await-reviewer")
        self.assertEqual(self.reviewer_dispatch_count(), 1)

    def test_replaying_the_same_event_produces_no_second_dispatch(self):
        run = make_run(self.config, self.backend, self.root)
        self.backend.end_turn(run["executor"]["session_id"])
        self.watch()
        # A second watcher pass sees the same stream state: no new dispatch.
        self.assertEqual(self.watch(), 0)
        self.assertEqual(self.reviewer_dispatch_count(), 1)


class MarkerWatchTests(ConformanceBase):
    def test_indented_marker_ignored_and_column_one_emitted(self):
        text = "- NEEDS_ARBITER: R-1 | indented | ignored\nNEEDS_ARBITER: R-2 | column one | decision\n"
        markers = store.extract_markers(text)
        self.assertEqual([m["marker"] for m in markers], ["NEEDS_ARBITER"])
        self.assertEqual(markers[0]["payload"], "R-2 | column one | decision")


class TruncationTests(ConformanceBase):
    def test_ledger_stream_truncation_stops_the_watcher_fail_closed(self):
        run = make_run(self.config, self.backend, self.root)
        executor_id = run["executor"]["session_id"]
        event_file = pathlib.Path(self.config["adapters"]["kimi-code"]["event_dir"]) / f"{executor_id}.jsonl"
        self.backend.end_turn(executor_id)
        data = event_file.read_bytes()
        run = self.load_run(run)
        # Record a cursor past the appended event, as the watcher would.
        run["executor_event_offset"] = len(data)
        store.save_run(self.config, run)
        # Shrink the stream below the recorded cursor: append-only broken.
        event_file.write_bytes(data[:10])
        self.assertEqual(self.watch(), 1)
        run = self.load_run(run)
        self.assertEqual(run["phase"], "suspended")
        self.assertEqual(run.get("suspension_reason"), "event-stream-truncation")
        self.assertTrue(any(item["kind"] == "NEEDS_ARBITER" for item in self.outbox()))
        self.assertEqual(self.reviewer_dispatch_count(), 0)


class DeliveryStateTests(ConformanceBase):
    def test_rejected_delivery_is_recorded_failed_not_accepted(self):
        self.backend.fail_mode = "rejected"
        run = make_run(self.config, self.backend, self.root)
        run = self.load_run(run)
        self.assertEqual(run["phase"], "suspended")
        self.assertNotEqual((run.get("last_delivery") or {}).get("status"), "accepted")
        self.assertTrue(any(item["kind"] == "NEEDS_ARBITER" for item in self.outbox()))

    def test_unknown_delivery_state_does_not_trigger_blind_retry(self):
        self.backend.fail_mode = "unknown"
        make_run(self.config, self.backend, self.root)
        self.assertGreaterEqual(len(self.backend.dispatches), 1)
        run = self.load_run(self.latest_run())
        self.assertEqual(run["phase"], "transport-unknown")
        dispatches_after_first = len(self.backend.dispatches)
        # Repeated watcher passes must not resend while the state is unknown.
        self.watch()
        self.watch()
        self.assertEqual(len(self.backend.dispatches), dispatches_after_first)

    def latest_run(self) -> dict:
        runs = list(store.iter_runs(self.config))
        return runs[-1]


class CrashResumeTests(ConformanceBase):
    def test_process_restart_with_unresolved_dispatch_fails_closed(self):
        run = make_run(self.config, self.backend, self.root)
        # Simulate a crash between send and save: pending_dispatch recorded,
        # phase still await-executor, no delivery confirmation.
        run = self.load_run(run)
        run["pending_dispatch"] = {
            "role": "executor",
            "prompt_id": "it_test_p_1",
            "baseline_seq": 0,
            "recorded_at": "2026-08-21T00:00:00+00:00",
        }
        store.save_run(self.config, run)
        before = len(self.backend.dispatches)
        self.watch()
        run = self.load_run(run)
        self.assertEqual(run["phase"], "transport-unknown")
        self.assertEqual(len(self.backend.dispatches), before)  # no blind resend
        self.assertTrue(any(item["kind"] == "NEEDS_ARBITER" for item in self.outbox()))

    def test_rotated_bindings_and_cursors_survive_watcher_restart(self):
        run = make_run(self.config, self.backend, self.root)
        executor_id = run["executor"]["session_id"]
        self.backend.end_turn(executor_id)
        self.watch()
        run = self.load_run(run)
        self.assertEqual(run["phase"], "await-reviewer")
        # Simulate a full process restart: fresh runner objects, state from disk.
        fresh_backend = FakeBackend(self.config)
        fresh_backend.sessions = {sid: dict(sess) for sid, sess in self.backend.sessions.items()}
        reviewer_id = run["reviewer"]["session_id"]
        fresh_backend.end_turn(reviewer_id)
        count = watch_once(
            self.config,
            self.config_path,
            self.bridge,
            backend=fresh_backend,
        )
        run = self.load_run(run)
        # The reviewer turn ended without a decision file: fail closed across
        # the restart, using bindings reloaded from run.json.
        self.assertEqual(count, 1)
        self.assertEqual(run["phase"], "await-arbiter")
        # The original watcher performed both role dispatches; the restarted
        # one correctly dispatched nothing (decision missing → escalate only).
        self.assertEqual(
            {d["session_id"] for d in self.backend.dispatches},
            {executor_id, reviewer_id},
        )
        self.assertEqual(fresh_backend.dispatches, [])


class DecisionFlowTests(ConformanceBase):
    def prepare_review_round(self) -> dict:
        run = make_run(self.config, self.backend, self.root)
        self.backend.end_turn(run["executor"]["session_id"])
        self.watch()
        return self.load_run(run)

    def test_missing_decision_escalates_to_manual_arbiter_path(self):
        run = self.prepare_review_round()
        self.backend.end_turn(run["reviewer"]["session_id"], busy=False)
        self.watch()
        run = self.load_run(run)
        self.assertEqual(run["phase"], "await-arbiter")
        kinds = [item["kind"] for item in self.outbox()]
        self.assertIn("NEEDS_ARBITER", kinds)

    def test_continue_decision_redispatches_executor_once(self):
        run = self.prepare_review_round()
        from iron_triangle.util import atomic_json

        atomic_json(
            store.decision_file(self.config, run["run_id"], run["review_round"]),
            {"run_id": run["run_id"], "review_round": run["review_round"], "decision": "continue", "message": "next slice", "recorded_at": "t"},
        )
        executor_dispatches_before = sum(1 for d in self.backend.dispatches if d["role"] == "executor")
        self.backend.end_turn(run["reviewer"]["session_id"], busy=False)
        self.watch()
        run = self.load_run(run)
        self.assertEqual(run["phase"], "await-executor")
        executor_dispatches_now = sum(1 for d in self.backend.dispatches if d["role"] == "executor")
        self.assertEqual(executor_dispatches_now, executor_dispatches_before + 1)
        # Replay adds nothing.
        self.watch()
        self.assertEqual(sum(1 for d in self.backend.dispatches if d["role"] == "executor"), executor_dispatches_now)

    def test_closure_pass_writes_round_closure_outbox(self):
        run = self.prepare_review_round()
        from iron_triangle.util import atomic_json

        atomic_json(
            store.decision_file(self.config, run["run_id"], run["review_round"]),
            {"run_id": run["run_id"], "review_round": run["review_round"], "decision": "closure-pass", "ledger_sequence": "R-2", "message": "reproduced", "recorded_at": "t"},
        )
        self.backend.end_turn(run["reviewer"]["session_id"], busy=False)
        self.watch()
        run = self.load_run(run)
        self.assertEqual(run["phase"], "await-final-acceptance")
        self.assertIn("ROUND_CLOSURE_PASS", [item["kind"] for item in self.outbox()])


class IdleWakeTests(ConformanceBase):
    def test_dual_idle_timeout_wakes_reviewer_once(self):
        config = base_config(self.root, idle_wake_seconds=30)
        (self.root / "events").mkdir(exist_ok=True)
        backend = FakeBackend(config)
        self.backend = backend
        self.config = config
        run = make_run(config, backend, self.root)
        run = store.load_run(config, run["run_id"])
        stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        run["last_progress_at"] = stale
        store.save_run(config, run)
        self.watch()
        self.assertEqual(self.reviewer_dispatch_count(), 1)
        run = store.load_run(config, run["run_id"])
        self.assertTrue(run.get("wake_sent"))
        # Second pass does not wake again.
        self.watch()
        self.assertEqual(self.reviewer_dispatch_count(), 1)


if __name__ == "__main__":
    unittest.main()
