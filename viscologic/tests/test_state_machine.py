# viscologic/tests/test_state_machine.py
# Unit tests for core/state_machine.py

import unittest
import time

from viscologic.core.state_machine import SystemStateMachine, SystemState


class TestStateMachine(unittest.TestCase):
    def test_initial_state(self):
        sm = SystemStateMachine()
        self.assertEqual(sm.state, SystemState.IDLE)

    def test_start_stop_flow(self):
        sm = SystemStateMachine()

        # Start request
        sm.handle_event("START", {"source": "local"})
        self.assertIn(sm.state, (SystemState.SWEEPING, SystemState.LOCKING, SystemState.RUNNING))

        # Stop request should always bring to IDLE (or STOPPING then IDLE)
        sm.handle_event("STOP", {"source": "local"})
        self.assertIn(sm.state, (SystemState.STOPPING, SystemState.IDLE))

        # advance tick
        for _ in range(10):
            sm.tick({})
        self.assertEqual(sm.state, SystemState.IDLE)

    def test_fault_latch(self):
        sm = SystemStateMachine()
        sm.handle_event("START", {"source": "local"})
        self.assertNotEqual(sm.state, SystemState.FAULT)

        sm.handle_event("FAULT", {"reason": "overcurrent"})
        self.assertEqual(sm.state, SystemState.FAULT)

        # ack alone should not clear latch if reset required
        sm.handle_event("ALARM_ACK", {})
        self.assertEqual(sm.state, SystemState.FAULT)

        sm.handle_event("ALARM_RESET", {})
        # after reset, should go to IDLE
        for _ in range(10):
            sm.tick({})
        self.assertEqual(sm.state, SystemState.IDLE)

    def test_comm_loss_action_safe_stop(self):
        sm = SystemStateMachine()
        sm.set_comm_loss_action("safe_stop")
        sm.handle_event("START", {"source": "remote"})
        self.assertIn(sm.state, (SystemState.SWEEPING, SystemState.LOCKING, SystemState.RUNNING))

        # comm loss event should stop
        sm.handle_event("COMM_LOSS", {"ms": 3000})
        for _ in range(10):
            sm.tick({})
        self.assertEqual(sm.state, SystemState.IDLE)

    def test_inline_mode_continuous(self):
        sm = SystemStateMachine()
        sm.set_mode("inline")
        sm.handle_event("START", {"source": "local"})
        self.assertIn(sm.state, (SystemState.SWEEPING, SystemState.LOCKING, SystemState.RUNNING))

        # in inline mode, "measurement end" should not auto-stop
        sm.handle_event("MEASUREMENT_COMPLETE", {})
        sm.tick({})
        self.assertNotEqual(sm.state, SystemState.IDLE)

    def test_tabletop_mode_can_stop_after_complete(self):
        sm = SystemStateMachine()
        sm.set_mode("tabletop")
        sm.handle_event("START", {"source": "local"})
        self.assertIn(sm.state, (SystemState.SWEEPING, SystemState.LOCKING, SystemState.RUNNING))

        sm.handle_event("MEASUREMENT_COMPLETE", {})
        # allow state machine to decide stop
        for _ in range(20):
            sm.tick({})
        # acceptable: may remain RUNNING until operator stops, or may go IDLE by policy
        self.assertIn(sm.state, (SystemState.RUNNING, SystemState.IDLE))

    def test_stop_overrides_start(self):
        sm = SystemStateMachine()

        sm.handle_event("STOP", {"source": "local"})
        self.assertEqual(sm.state, SystemState.IDLE)

        sm.handle_event("START", {"source": "local"})
        self.assertIn(sm.state, (SystemState.SWEEPING, SystemState.LOCKING, SystemState.RUNNING))

        sm.handle_event("STOP", {"source": "local"})
        for _ in range(10):
            sm.tick({})
        self.assertEqual(sm.state, SystemState.IDLE)


if __name__ == "__main__":
    unittest.main()
