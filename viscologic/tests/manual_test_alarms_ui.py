"""
manual_test_alarms_ui.py
------------------------
A standalone script to test the Alarms Screen UI behavior.
It simulates an EventBus and pushes fake status update frames
to demonstrate:
1. Active Alarm appear/disappear
2. Fault Latching
3. History logging
4. Reset command handling
"""

import tkinter as tk
from tkinter import ttk
import time
import threading
from typing import Dict, Any, Callable

# Mock EventBus
class MockEventBus:
    def __init__(self):
        self.subs = []
        self.cmd_subs = []
    
    def on(self, event: str, callback: Callable):
        if event == "ui.frame":
            self.subs.append(callback)
        elif event == "ui.command":
            self.cmd_subs.append(callback)

    def publish_frame(self, frame: Dict[str, Any]):
        for cb in self.subs:
            try:
                cb(frame)
            except Exception as e:
                print("Subscriber error:", e)

    def emit_command(self, cmd_payload: Dict[str, Any]):
        # This is called by the UI when buttons are clicked
        print(f"[BUS] Command Received: {cmd_payload}")
        # Notify whoever is listening to commands (our simulation loop)
        for cb in self.cmd_subs:
            cb(cmd_payload)

# Load the target UI class
from viscologic.ui.alarms_screen import AlarmsScreen

def main():
    root = tk.Tk()
    root.title("Alarms Screen Test Harness")
    root.geometry("800x600")

    bus = MockEventBus()
    
    # Navigation mock
    def mock_nav(route):
        print(f"[NAV] User requested navigation to: {route}")

    screen = AlarmsScreen(root, event_bus=bus, navigate_callback=mock_nav)
    screen.pack(fill="both", expand=True)

    # Simulation State
    sim_state = {
        "running": True,
        "alarms": {},
        "fault_latched": False,
        "last_error": "",
        "start_ts": time.time()
    }

    # Command Listener to handle Reset/Ack
    def on_command(payload):
        cmd = payload.get("cmd")
        if cmd == "ALARM_ACK":
            print(">>> SIMULATION: Acknowledged alarms (buzzer silence).")
        elif cmd == "ALARM_RESET":
            print(">>> SIMULATION: Resetting fault latch!")
            sim_state["fault_latched"] = False
            sim_state["last_error"] = ""
            sim_state["alarms"] = {}

    bus.on("ui.command", on_command)

    # Background Simulation Loop
    def sim_loop():
        while sim_state["running"]:
            now = time.time()
            elapsed = now - sim_state["start_ts"]

            # Scenario 1: T+2s -> Overheat Warning
            if 2.0 < elapsed < 6.0:
                sim_state["alarms"]["OVERHEAT_WARNING"] = True
            
            # Scenario 2: T+6s -> CRITICAL OVERHEAT + FAULT
            if elapsed > 6.0 and not sim_state.get("fault_cleared_once", False):
                sim_state["alarms"]["CRITICAL_TEMP"] = True
                sim_state["fault_latched"] = True
                sim_state["last_error"] = "CRITICAL: Sensor temp > 95C"
            
            # Build frame
            frame = {
                "ts_ms": int(now * 1000),
                "alarms": sim_state["alarms"],
                "fault_latched": sim_state["fault_latched"],
                "last_error": sim_state["last_error"],
                "mode": "simulation"
            }
            
            # Push to UI
            root.after(0, lambda f=frame: bus.publish_frame(f))
            
            time.sleep(0.5)

    t = threading.Thread(target=sim_loop, daemon=True)
    t.start()

    print("Test running... Close window to exit.")
    root.mainloop()
    sim_state["running"] = False

if __name__ == "__main__":
    main()
