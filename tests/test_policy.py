"""Pure policy state-machine tests: fail-closed invariants without I/O."""

from __future__ import annotations

import unittest

import _helpers  # noqa: F401  (sys.path bootstrap)

from iron_triangle import policy
from iron_triangle.policy import (
    Dispatch,
    Outbox,
    PolicyInput,
    RoleObservation,
    Transition,
    decide,
    apply_delivery,
    heartbeat,
)
from iron_triangle.store import extract_markers


def awaiting_executor(**kwargs) -> PolicyInput:
    defaults = dict(phase="await-executor", executor=RoleObservation(busy=False, turn_ended=True), review_round=0)
    defaults.update(kwargs)
    return PolicyInput(**defaults)


def awaiting_reviewer(**kwargs) -> PolicyInput:
    defaults = dict(
        phase="await-reviewer",
        reviewer=RoleObservation(busy=False, turn_ended=True),
        review_round=1,
        decision_status="ready",
        decision={"decision": "continue", "message": "next slice"},
    )
    defaults.update(kwargs)
    return PolicyInput(**defaults)


class DecideTests(unittest.TestCase):
    def test_idle_run_produces_no_actions(self):
        inp = awaiting_executor(executor=RoleObservation(busy=True, turn_ended=False))
        self.assertEqual(decide(inp), [])

    def test_executor_turn_ended_dispatches_reviewer_exactly_once(self):
        actions = decide(awaiting_executor())
        self.assertEqual([type(a) for a in actions], [Dispatch, Transition])
        self.assertEqual(actions[0].role, "reviewer")
        self.assertEqual(actions[1].phase, "await-reviewer")
        self.assertEqual(actions[1].extra["review_round"], 1)

    def test_duplicate_turn_ended_does_not_retrigger(self):
        # After the first pass the phase moved to await-reviewer; replaying the
        # same executor observation cannot produce a second reviewer dispatch.
        inp = awaiting_reviewer(reviewer=RoleObservation(busy=True, turn_ended=False))
        self.assertEqual(decide(inp), [])

    def test_pending_interaction_blocks_input(self):
        actions = decide(awaiting_executor(executor=RoleObservation(busy=False, pending_interaction="approval")))
        transition = next(a for a in actions if isinstance(a, Transition))
        self.assertEqual(transition.phase, "blocked-input")
        self.assertTrue(any(isinstance(a, Outbox) and a.kind == "NEEDS_ARBITER" for a in actions))

    def test_truncation_suspends_fail_closed(self):
        actions = decide(awaiting_executor(executor=RoleObservation(busy=False, turn_ended=False, truncated=True)))
        transition = next(a for a in actions if isinstance(a, Transition))
        self.assertEqual(transition.phase, "suspended")
        self.assertTrue(any(isinstance(a, Outbox) for a in actions))
        self.assertFalse(any(isinstance(a, Dispatch) for a in actions))

    def test_crash_residue_pending_dispatch_never_blind_retries(self):
        inp = awaiting_executor(pending_dispatch={"role": "executor", "prompt_id": "p-1"})
        actions = decide(inp)
        self.assertFalse(any(isinstance(a, Dispatch) for a in actions))
        transition = next(a for a in actions if isinstance(a, Transition))
        self.assertEqual(transition.phase, "transport-unknown")
        self.assertTrue(any(isinstance(a, Outbox) and a.kind == "NEEDS_ARBITER" for a in actions))

    def test_missing_decision_escalates(self):
        actions = decide(awaiting_reviewer(decision_status="absent"))
        transition = next(a for a in actions if isinstance(a, Transition))
        self.assertEqual(transition.phase, "await-arbiter")

    def test_malformed_decision_escalates(self):
        actions = decide(awaiting_reviewer(decision_status="malformed"))
        transition = next(a for a in actions if isinstance(a, Transition))
        self.assertEqual(transition.phase, "await-arbiter")

    def test_mismatched_decision_round_escalates(self):
        actions = decide(awaiting_reviewer(decision_status="mismatch"))
        self.assertTrue(any(isinstance(a, Transition) and a.phase == "await-arbiter" for a in actions))

    def test_continue_decision_dispatches_executor(self):
        actions = decide(awaiting_reviewer())
        dispatch = next(a for a in actions if isinstance(a, Dispatch))
        transition = next(a for a in actions if isinstance(a, Transition))
        self.assertEqual(dispatch.role, "executor")
        self.assertEqual(dispatch.literal, "next slice")
        self.assertEqual(transition.phase, "await-executor")
        self.assertTrue(transition.extra.get("round_next"))

    def test_continue_without_message_escalates(self):
        actions = decide(awaiting_reviewer(decision={"decision": "continue", "message": "  "}))
        self.assertTrue(any(isinstance(a, Transition) and a.phase == "await-arbiter" for a in actions))

    def test_needs_arbiter_decision_routes_to_outbox(self):
        actions = decide(awaiting_reviewer(decision={"decision": "needs-arbiter", "message": "which model?"}))
        self.assertTrue(any(isinstance(a, Outbox) and a.kind == "NEEDS_ARBITER" for a in actions))
        self.assertTrue(any(isinstance(a, Transition) and a.phase == "await-arbiter" for a in actions))

    def test_closure_pass_routes_to_final_acceptance(self):
        actions = decide(awaiting_reviewer(decision={"decision": "closure-pass", "message": "all checks reproduced"}))
        self.assertTrue(any(isinstance(a, Outbox) and a.kind == "ROUND_CLOSURE_PASS" for a in actions))
        self.assertTrue(any(isinstance(a, Transition) and a.phase == "await-final-acceptance" for a in actions))

    def test_unknown_decision_action_escalates(self):
        actions = decide(awaiting_reviewer(decision={"decision": "ship-it", "message": "trust me"}))
        self.assertTrue(any(isinstance(a, Transition) and a.phase == "await-arbiter" for a in actions))

    def test_terminal_phases_are_inert(self):
        for phase in ("await-arbiter", "await-final-acceptance", "blocked-input", "transport-unknown", "suspended", "complete", "stopped", "launching"):
            self.assertEqual(decide(PolicyInput(phase=phase)), [])


class DeliveryTests(unittest.TestCase):
    def test_accepted_advances_to_expected_phase(self):
        actions = apply_delivery(awaiting_executor(), "executor", policy.DELIVERY_ACCEPTED, "await-executor")
        self.assertEqual(actions, [Transition("await-executor")])

    def test_rejected_suspends_and_records_outbox(self):
        actions = apply_delivery(awaiting_executor(), "executor", policy.DELIVERY_REJECTED, "await-executor")
        self.assertFalse(any(isinstance(a, Transition) and a.phase == "await-executor" for a in actions))
        transition = next(a for a in actions if isinstance(a, Transition))
        self.assertEqual(transition.phase, "suspended")

    def test_unknown_delivery_blocks_retry(self):
        actions = apply_delivery(awaiting_executor(), "executor", policy.DELIVERY_UNKNOWN, "await-executor")
        transition = next(a for a in actions if isinstance(a, Transition))
        self.assertEqual(transition.phase, "transport-unknown")
        self.assertTrue(any(isinstance(a, Outbox) and a.kind == "NEEDS_ARBITER" for a in actions))


class HeartbeatTests(unittest.TestCase):
    def test_no_limit_no_wake(self):
        inp = awaiting_executor()
        self.assertEqual(heartbeat(inp, 999.0, None, False), [])

    def test_idle_below_limit_no_wake(self):
        inp = awaiting_executor()
        self.assertEqual(heartbeat(inp, 10.0, 30.0, False), [])

    def test_dual_idle_wakes_reviewer_once(self):
        inp = awaiting_executor()
        actions = heartbeat(inp, 45.0, 30.0, False)
        self.assertTrue(any(isinstance(a, Dispatch) and a.role == "reviewer" for a in actions))
        self.assertEqual(heartbeat(inp, 45.0, 30.0, True), [])

    def test_wake_only_in_active_phases(self):
        inp = PolicyInput(phase="await-arbiter")
        self.assertEqual(heartbeat(inp, 45.0, 30.0, False), [])


class MarkerTests(unittest.TestCase):
    def test_column_one_markers_emitted(self):
        text = "NEEDS_ARBITER: R-4 | reason | decision\nplain text\n"
        markers = extract_markers(text)
        self.assertEqual(markers[0]["marker"], "NEEDS_ARBITER")

    def test_indented_markers_ignored(self):
        text = "- NEEDS_ARBITER: R-4 | reason | decision\n  ROUND_CLOSURE_PASS: R-5 | s | r\n> NEEDS_ARBITER: x\n"
        self.assertEqual(extract_markers(text), [])

    def test_quoted_marker_ignored(self):
        self.assertEqual(extract_markers('"NEEDS_ARBITER: R-1 | a | b"'), [])


if __name__ == "__main__":
    unittest.main()
