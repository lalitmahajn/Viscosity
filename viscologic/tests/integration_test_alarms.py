"""
integration_test_alarms.py
--------------------------
Integration test for Alarms Screen + Orchestrator + SafetyManager.
Runs on Windows using driver mocks. Verifies that ALARM_RESET truly clears the latch.

Test Scenario:
1. Start System (Mock Mode).
2. Inject Overheat Fault directly into the Mock Temp Driver.
3. Verify Fault Latch (UI turns RED).
4. Remove Overheat Condition.
5. User clicks "Reset Fault".
6. Verify Fault Latch Clears and System Resumes.
"""

import os
import time
import threading
import tkinter as tk
from tkinter import ttk

# Force Mock Mode for Orchestrator logic
os.environ["MOCK_MODE"] = "1"

from viscologic.core.event_bus import EventBus
from viscologic.core.orchestrator import Orchestrator
from viscologic.ui.alarms_screen import AlarmsScreen

def main():
    root = tk.Tk()
    root.title("Integration Test: Alarms + Orchestrator")
    root.geometry("800x600")

    # 1. Setup Backend
    bus = EventBus()
    # Minimal config
    config = {
        "app": {"mode": "tabletop"},
        "safety": {"max_temp_c": 90.0}
    }
    
    orch = Orchestrator(config, bus)
    
    # 2. Setup UI
    # We mock navigation since we don't have the main app router
    def mock_nav(route):
        print(f"[NAV] Requested: {route}")

    screen = AlarmsScreen(root, event_bus=bus, navigate_callback=mock_nav)
    screen.pack(fill="both", expand=True)

    # 3. Start Backend
    print("[TEST] Starting Orchestrator...")
    orch_thread = threading.Thread(target=orch.start, daemon=True)
    orch_thread.start()

    # 4. Simulation Controller
    def run_simulation_steps():
        print("[TEST] Step 1: Running normal for 3s...")
        time.sleep(3)

        print("[TEST] Step 2: INJECTING OVERHEAT FAULT (100C)")
        # Access the private mock sensor inside the driver
        # orch.temp is MAX31865Driver
        # orch.temp._sensor is _MockTemp
        if hasattr(orch.temp, "_sensor") and hasattr(orch.temp._sensor, "_current_temp"):
             orch.temp._sensor._current_temp = 100.0
             orch.temp._sensor._target_temp = 100.0 # prevent auto-cool
        
        print("[TEST] Waiting for latch (5s)...")
        time.sleep(5)
        
        # Verify latch in backend
        if orch.safety.fault_latched():
            print("[TEST] PASS: Fault is latched in SafetyManager!")
        else:
            print("[TEST] FAIL: SafetyManager did not latch fault!")

        print("[TEST] Step 3: Removing Overheat Condition (25C)")
        if hasattr(orch.temp, "_sensor"):
             orch.temp._sensor._current_temp = 25.0
             orch.temp._sensor._target_temp = 25.0
        
        print("[TEST] Step 4: Ready for Manual Reset. Click 'Reset Fault' in UI!")

    sim_thread = threading.Thread(target=run_simulation_steps, daemon=True)
    sim_thread.start()

    print("[TEST] UI Running. Watch for 'FAULT' in footer and click Reset.")
    root.mainloop()

    # Cleanup
    orch.stop()

if __name__ == "__main__":
    main()
