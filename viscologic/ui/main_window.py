# viscologic/ui/main_window.py
# The "Motherboard" of the UI.
# Now uses a "Card Stack" layout.
# Navigation is now strictly controlled by Buttons (Operator -> Engineer, etc.)

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import logging
from typing import Any, Dict, Optional

# --- Safe Imports ---
def _safe_import(path, class_name):
    try:
        mod = __import__(path, fromlist=[class_name])
        return getattr(mod, class_name)
    except (ImportError, AttributeError) as e:
        print(f"[DEBUG] Import Failed: {class_name} from {path} -> {e}")
        return None

# UI Screens
OperatorScreen = _safe_import("viscologic.ui.operator_screen", "OperatorScreen")
EngineerScreen = _safe_import("viscologic.ui.engineer_screen", "EngineerScreen")
AlarmsScreen = _safe_import("viscologic.ui.alarms_screen", "AlarmsScreen")
CommissioningLock = _safe_import("viscologic.ui.commissioning_lock", "CommissioningLock")
CommissioningWizard = _safe_import("viscologic.ui.commissioning_wizard", "CommissioningWizard")
CalibrationWizard = _safe_import("viscologic.ui.calibration_wizard", "CalibrationWizard")

# Backend Logic
SqliteStore = _safe_import("viscologic.storage.sqlite_store", "SqliteStore")
CommissioningManager = _safe_import("viscologic.security.commissioning_manager", "CommissioningManager")
EngineerAuth = _safe_import("viscologic.security.auth_engineer", "EngineerAuth")
CalibrationStore = _safe_import("viscologic.model.calibration_store", "CalibrationStore")
CalibrationLUT = _safe_import("viscologic.model.calibration_lut", "CalibrationLUT")


class MainWindowApp:
    def __init__(self, config: Dict[str, Any], bus: Any, logger: Any):
        self.config = config
        self.bus = bus
        self.logger = logger
        self._running = True

        self._init_backend()
        self.root = tk.Tk()
        # Apply global theme first
        try:
            from viscologic.ui.theme import apply_theme
            apply_theme(self.root)
        except Exception as e:
            self.logger.warning(f"Failed to apply theme: {e}")
            # Fallback to basic styling
            self._setup_styles()
        self._setup_window()
        self._build_status_bar()
        self._build_card_stack()  # New Layout Method

        # Subscribe to events
        if self.bus:
            subscribe = getattr(self.bus, "subscribe", None) or getattr(self.bus, "on", None)
            if callable(subscribe):
                subscribe("ui.navigate", self._on_navigate_event)
                subscribe("commissioning.completed", self._on_commissioning_done)

        # Decide Startup Screen
        self.root.after(100, self._decide_startup_screen)
        self._poll_status_loop()

    def _init_backend(self):
        self.store = None
        self.comm_mgr = None
        self.auth_mgr = None
        self.cal_store = None
        self.cal_lut = None

        if SqliteStore:
            db_path = self.config.get("storage", {}).get("sqlite_path", "data/viscologic.db")
            if not os.path.isabs(db_path): db_path = os.path.abspath(db_path)
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            try:
                self.store = SqliteStore(db_path, logger=self.logger)
                if hasattr(self.store, "init_db"): self.store.init_db()
            except Exception as e:
                self.logger.error(f"UI DB Init Failed: {e}")

        if self.store:
            if CommissioningManager:
                self.comm_mgr = CommissioningManager(self.store, self.config, logger=self.logger)
                try: self.comm_mgr.ensure_password_initialized() 
                except: pass
            if EngineerAuth:
                self.auth_mgr = EngineerAuth(self.store, self.config, logger=self.logger)
                try: self.auth_mgr.ensure_password_initialized()
                except: pass
            if CalibrationStore:
                self.cal_store = CalibrationStore(self.store)
        
        if CalibrationLUT:
            cal_cfg = self.config.get("calibration", {})
            self.cal_lut = CalibrationLUT(cal_cfg)

    def _setup_styles(self):
        """Initialize ttk styles for enhanced UI"""
        try:
            style = ttk.Style()
            style.theme_use('clam')
            
            # Override all theme colors to remove cream/yellow tints
            bg_main = "#f5f5f5"  # Light gray for main background
            bg_card = "#ffffff"  # White for cards
            bg_status = "#e8e8e8"  # Slightly darker gray for status bar
            
            # Configure base widget styles with consistent backgrounds
            style.configure("TFrame", background=bg_main)
            style.configure("TLabel", background=bg_main, foreground="#2c3e50")
            style.configure("TButton", background="#e0e0e0", foreground="#2c3e50")
            style.map("TButton", background=[("active", "#d0d0d0"), ("pressed", "#c0c0c0")])
            style.configure("TEntry", background="#ffffff", fieldbackground="#ffffff")
            style.configure("TCombobox", background="#ffffff", fieldbackground="#ffffff")
            style.configure("TNotebook", background=bg_main)
            style.configure("TNotebook.Tab", background="#d0d0d0", padding=[12, 6])
            style.map("TNotebook.Tab", background=[("selected", bg_main)])
            
            # Configure card frame style with white background
            style.configure("Card.TFrame", background=bg_card, relief="flat", borderwidth=1)
            
            # Configure labels inside cards to have white background
            style.configure("Card.TLabel", background=bg_card, foreground="#2c3e50")
            
            # Configure status bar style
            style.configure("StatusBar.TFrame", background=bg_status)
            style.configure("StatusBar.TLabel", background=bg_status)
            
            # Configure top bar style (for operator screen header)
            style.configure("TopBar.TFrame", background=bg_main)
            style.configure("TopBar.TLabel", background=bg_main)
            
            # Configure button variants
            style.configure("Primary.TButton", background="#3498db", foreground="#ffffff")
            style.map("Primary.TButton", background=[("active", "#2980b9")])
            style.configure("Danger.TButton", background="#e74c3c", foreground="#ffffff")
            style.map("Danger.TButton", background=[("active", "#c0392b")])
            
            # Configure health progressbar style with default color (will be updated dynamically)
            try:
                style.configure("Health.TProgressbar", background="#27ae60", troughcolor=bg_main)
            except Exception:
                pass  # Some Tkinter versions may not support this
                
        except Exception:
            pass  # Fallback if styles not supported
    
    def _setup_window(self):
        app_name = self.config.get("app", {}).get("name", "ViscoLogic Meter")
        self.root.title(app_name)
        if self.config.get("app", {}).get("kiosk_mode", False):
            self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry("1024x600")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Set root window background to light gray for consistency
        self.root.configure(bg="#f5f5f5")

    def _build_status_bar(self):
        """Top bar that is ALWAYS visible - using Header style."""
        self.status_frame = ttk.Frame(self.root, style="Header.TFrame", padding=8)
        self.status_frame.pack(side="top", fill="x")
        self.var_visc = tk.StringVar(value="Visc: --.- cP")
        self.var_temp = tk.StringVar(value="Temp: --.- °C")
        self.var_health = tk.StringVar(value="Health: -- %")
        self.var_status = tk.StringVar(value="System: INIT")

        ttk.Label(self.status_frame, textvariable=self.var_visc, style="Header.TLabel", 
                 font=("Segoe UI", 12, "bold"), width=18).pack(side="left", padx=10)
        ttk.Label(self.status_frame, textvariable=self.var_temp, style="Header.TLabel",
                 font=("Segoe UI", 11)).pack(side="left", padx=10)
        ttk.Label(self.status_frame, textvariable=self.var_status, style="Header.TLabel",
                 font=("Segoe UI", 10)).pack(side="right", padx=10)
        ttk.Label(self.status_frame, textvariable=self.var_health, style="Header.TLabel",
                 font=("Segoe UI", 10)).pack(side="right", padx=10)

    def _build_card_stack(self):
        """
        Replaces Notebook. 
        Creates a container where all screens live at (0,0).
        We switch screens by bringing one to the front (tkraise).
        """
        self.stack_container = ttk.Frame(self.root)
        self.stack_container.pack(fill="both", expand=True)
        self.stack_container.grid_rowconfigure(0, weight=1)
        self.stack_container.grid_columnconfigure(0, weight=1)
        # Container will inherit TFrame style (light gray background)

        self.frames = {}

        # Define a helper to add screens to the stack
        def add_screen(name, screen_class, **kwargs):
            if screen_class:
                # Create instance
                frame = screen_class(self.stack_container, **kwargs)
                # Place in grid (all on top of each other)
                frame.grid(row=0, column=0, sticky="nsew")
                self.frames[name] = frame
                # Lower it to bottom initially
                frame.lower()

        # 1. Operator Screen
        if OperatorScreen:
            op_screen = OperatorScreen(self.stack_container, event_bus=self.bus, config_manager=self.config)
            op_screen.set_navigation_callbacks(
                open_engineer=lambda: self.navigate_to("engineer"),
                open_alarms=lambda: self.navigate_to("alarms"),
                open_calibration=lambda: self.navigate_to("calibration_wizard")
            )
            op_screen.grid(row=0, column=0, sticky="nsew")
            self.frames["operator"] = op_screen

        # 2. Alarms
        add_screen("alarms", AlarmsScreen, event_bus=self.bus,
                    navigate_callback=self.navigate_to)  # <--- Pass nav callback

        # 3. Engineer
        add_screen("engineer", EngineerScreen, 
                   config_manager=self.config, 
                   auth_engineer=self.auth_mgr,
                   commissioning_manager=self.comm_mgr, 
                   event_bus=self.bus,
                   navigate_callback=self.navigate_to)  # <--- Pass nav callback

        # 4. Calibration Wizard
        add_screen("calibration_wizard", CalibrationWizard,
                   calibration_store=self.cal_store, 
                   calibration_lut=self.cal_lut,
                   config_manager=self.config, 
                   event_bus=self.bus,
                   # --- ADD THIS LINE ---
                   navigate_callback=self.navigate_to, 
                   # --------------------- 
                   on_done=lambda: self.navigate_to("engineer"))

        # 5. Commissioning Wizard
        add_screen("commissioning_wizard", CommissioningWizard,
                   config_manager=self.config, 
                   commissioning_manager=self.comm_mgr,
                   event_bus=self.bus,
                    # --- ADD THIS LINE ---
                   navigate_callback=self.navigate_to, 
                   # --------------------- 
                   on_completed=self._on_commissioning_done_internal,
                   on_cancel=lambda: self.navigate_to("operator"))

        # 6. Commissioning Lock (Always created last to sit on top if needed)
        add_screen("lock", CommissioningLock,
                   commissioning_manager=self.comm_mgr,
                   event_bus=self.bus, 
                   on_unlocked=self._on_lock_unlocked)

    def _is_commissioned(self) -> bool:
        if self.comm_mgr:
            try:
                if hasattr(self.comm_mgr, "is_commissioned"):
                    val = self.comm_mgr.is_commissioned()
                    return bool(val() if callable(val) else val)
                elif hasattr(self.comm_mgr, "commissioned"):
                    return bool(self.comm_mgr.commissioned)
            except: pass
        return True

    def _decide_startup_screen(self):
        if not self._is_commissioned():
            self.logger.info("Startup: Not Commissioned -> Lock Screen")
            self.navigate_to("lock")
        else:
            self.logger.info("Startup: Commissioned -> Operator Screen")
            self.navigate_to("operator")

    def _on_lock_unlocked(self):
        # Allow navigation to wizard because we just unlocked the gate
        self.navigate_to("commissioning_wizard", force=True)

    def _on_commissioning_done_internal(self):
        self.logger.info("Wizard done. Forcing save...")
        if self.comm_mgr:
            try:
                saved = False
                for method in ["set_commissioned", "mark_commissioned", "commission"]:
                    if hasattr(self.comm_mgr, method):
                        fn = getattr(self.comm_mgr, method)
                        if callable(fn):
                            fn(True) if method == "set_commissioned" else fn()
                            saved = True
                            break
                if not saved: setattr(self.comm_mgr, "commissioned", True)
            except Exception as e:
                self.logger.error(f"Save failed: {e}")
        self.navigate_to("operator")

    def _on_commissioning_done(self, payload):
        self._on_commissioning_done_internal()

    def _on_navigate_event(self, payload):
        target = payload.get("to")
        force = payload.get("force", False)
        if target: 
            self.navigate_to(target, force=force)

    def navigate_to(self, target: str, force: bool = False):
        """
        Navigates by raising the target frame to the top of the stack.
        """
        target = target.lower()
        if target in ["main", "home", "dashboard"]: target = "operator"
        if target in ["cal", "calibration"]: target = "calibration_wizard"
        if target in ["comm", "setup", "commissioning"]: target = "commissioning_wizard"

        # --- GUARD CLAUSE ---
        if target == "commissioning_wizard" and not force:
            if self._is_commissioned():
                self.logger.warning("BLOCKED phantom navigation to Commissioning Wizard.")
                return

        self.logger.info(f"Navigating to: {target}")

        if target in self.frames:
            # The Magic: Bring this frame to the front
            print(f"[DEBUG] MainWindowApp: Raising frame '{target}'")

            frame = self.frames[target]
            frame.tkraise()
            
            # If navigating back to Operator, ensure focus/reset if needed
            if target == "operator":
                frame.focus_set()
                
        else:
            self.logger.warning(f"Unknown Nav Target: {target}")

    def _poll_status_loop(self):
        if not self._running: 
            return
        if self.bus:
            # Try get_latest_frame() method first (EventBus standard)
            frame = {}
            get_frame = getattr(self.bus, "get_latest_frame", None)
            if callable(get_frame):
                try:
                    frame = get_frame() or {}
                except Exception:
                    pass
            # Fallback to latest_frame attribute (for compatibility)
            elif hasattr(self.bus, "latest_frame"):
                frame = getattr(self.bus, "latest_frame", {}) or {}
            
            if frame and isinstance(frame, dict):
                v = frame.get("viscosity_cp", 0.0)
                t = frame.get("temp_c", None)
                h = frame.get("health_score", frame.get("health_pct", 0))
                state = frame.get("state", "IDLE")
                
                # Format viscosity
                if v and v > 0:
                    self.var_visc.set(f"Visc: {v:,.1f} cP")
                else:
                    self.var_visc.set("Visc: --.- cP")
                
                # Format temperature
                if t is not None and isinstance(t, (int, float)):
                    self.var_temp.set(f"Temp: {t:.1f} °C")
                else:
                    self.var_temp.set("Temp: --.- °C")
                
                # Format health
                self.var_health.set(f"Health: {int(h)}%")
                
                # Format status
                if frame.get("fault") or frame.get("fault_latched"):
                    state = "FAULT"
                elif frame.get("locked"):
                    state = "LOCKED"
                elif state:
                    state = str(state).upper()
                else:
                    state = "IDLE"
                self.var_status.set(f"Sys: {state}")
        self.root.after(250, self._poll_status_loop)

    def _on_close(self):
        if messagebox.askokcancel("Exit", "Stop ViscoLogic?"):
            self._running = False
            self.root.quit()

    def run(self) -> int:
        try:
            self.root.mainloop()
            return 0
        except KeyboardInterrupt:
            return 0