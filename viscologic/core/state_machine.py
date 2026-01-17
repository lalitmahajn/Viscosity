# viscologic/core/state_machine.py
from __future__ import annotations
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Dict, Any

# 1. Define SystemState as an Enum (Required by Orchestrator)
class SystemState(Enum):
    BOOT = auto()
    SELF_CHECK = auto()
    IDLE = auto()
    SWEEPING = auto()
    LOCKING = auto()
    RUNNING = auto()     # ← NEW
    LOCKED = auto()
    PAUSED = auto()
    FAULT = auto()
    COMMISSIONING = auto()
    STOPPING = auto()  # Added: Used in Orchestrator logic

# 2. Define Event Constants (Internal use)
EV_TICK = "TICK"
EV_START = "START"
EV_STOP = "STOP"
EV_PAUSE = "PAUSE"
EV_RESUME = "RESUME"
EV_ABORT = "ABORT"
EV_LOCK_ACQUIRED = "LOCK_ACQUIRED"
EV_LOCK_LOST = "LOCK_LOST"
EV_FAULT = "FAULT"
EV_FAULT_CLEARED = "FAULT_CLEARED"
EV_COMMISSIONING_REQUIRED = "COMMISSIONING_REQUIRED"
EV_COMMISSIONING_DONE = "COMMISSIONING_DONE"
EV_SELF_CHECK_OK = "SELF_CHECK_OK"
EV_SELF_CHECK_FAIL = "SELF_CHECK_FAIL"

@dataclass
class TransitionResult:
    prev_state: SystemState
    new_state: SystemState
    changed: bool
    reason: str = ""

# 3. Rename class to SystemStateMachine (Required by Orchestrator)
class SystemStateMachine:
    def __init__(self):
        self.state = SystemState.BOOT
        self.last_reason = "init"
        self._mode = "tabletop" # Default mode
        self._comm_loss_action = "safe_stop"

    # --- Methods expected by Orchestrator ---
    
    def set_mode(self, mode: str) -> None:
        """Set application mode (tabletop vs inline)."""
        self._mode = mode

    def set_comm_loss_action(self, action: str) -> None:
        """Set behavior on comms loss."""
        self._comm_loss_action = action

    def is_locked(self) -> bool:
        """Helper to check if currently locked."""
        return self.state == SystemState.RUNNING

    def tick(self, ctx: Dict[str, Any]) -> None:
        """Orchestrator calls this every loop iteration."""
        # Map .tick() to the internal event handler
        self.handle_event(EV_TICK, ctx)

    def handle_event(self, event: str, ctx: Optional[Dict[str, Any]] = None) -> TransitionResult:
        """
        Main transition logic (formerly on_event).
        Renamed to match Orchestrator call signature.
        """
        ctx = ctx or {}
        prev = self.state
        reason = ""

        # --- Global Guards ---
        if event == EV_COMMISSIONING_REQUIRED:
            return self._transition(SystemState.COMMISSIONING, "commissioning_required")
            
        if event == EV_FAULT:
            # Extract reason from context if available
            r = ctx.get("reason", "fault_triggered")
            return self._transition(SystemState.FAULT, r)

        # --- State Logic ---
        
        # BOOT
        if prev == SystemState.BOOT:
            if event == EV_TICK:
                return self._transition(SystemState.SELF_CHECK, "boot_complete")

        # SELF_CHECK
        elif prev == SystemState.SELF_CHECK:
            # In real logic, orchestrator might drive this via tick or specific result events
            # For now, auto-pass on tick for simulation if not implemented
            if event == EV_TICK:
                return self._transition(SystemState.IDLE, "self_check_pass") 
            if event == EV_SELF_CHECK_FAIL:
                 return self._transition(SystemState.FAULT, "self_check_fail")

        # IDLE
        elif prev == SystemState.IDLE:
            if event == EV_START:
                return self._transition(SystemState.SWEEPING, "start_command")

        # SWEEPING
        elif prev == SystemState.SWEEPING:
            if event == EV_STOP:
                return self._transition(SystemState.IDLE, "stop_command")
            if event == "SWEEP_DONE":
                return self._transition(SystemState.LOCKING, "sweep_done")
            if event == EV_LOCK_ACQUIRED:
                return self._transition(SystemState.LOCKED, "direct_lock")

        # LOCKING
        elif prev == SystemState.LOCKING:
            if event == EV_STOP:
                return self._transition(SystemState.IDLE, "stop_command")
            if event == "LOCK_OK": # inferred from Orchestrator usage
                return self._transition(SystemState.RUNNING, "lock_acquired")

        # RUNNING
        elif prev == SystemState.RUNNING:
            if event == EV_STOP:
                return self._transition(SystemState.IDLE, "stop_command")
            if event == EV_LOCK_LOST:
                return self._transition(SystemState.LOCKING, "lock_lost")

        # FAULT
        elif prev == SystemState.FAULT:
            if event == "ALARM_RESET" or event == EV_FAULT_CLEARED:
                return self._transition(SystemState.IDLE, "fault_reset") # or SELF_CHECK

        # COMMISSIONING
        elif prev == SystemState.COMMISSIONING:
            if event == EV_COMMISSIONING_DONE:
                return self._transition(SystemState.IDLE, "commissioning_done")
            if event == EV_STOP:
                return self._transition(SystemState.IDLE, "stop_command")

        # Default: No change
        return TransitionResult(prev, self.state, False, "ignored")

    def _transition(self, new_state: SystemState, reason: str) -> TransitionResult:
        prev = self.state
        self.state = new_state
        self.last_reason = reason
        return TransitionResult(prev, new_state, True, reason)