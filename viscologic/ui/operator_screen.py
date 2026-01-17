# viscologic/ui/operator_screen.py
# Simple Operator UI (Tkinter) - With DEBUG PRINTS

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Callable, Dict, Optional

try:
    from viscologic.ui.ui_styles import COLORS, FONTS, PADDING, get_status_color, get_health_color
except ImportError:
    # Fallback if styles module not available
    COLORS = {"success": "#27ae60", "warning": "#f39c12", "danger": "#e74c3c", "text_secondary": "#7f8c8d", "primary": "#2c3e50"}
    FONTS = {"title": ("Segoe UI", 16, "bold"), "heading": ("Segoe UI", 12, "bold"), "body": ("Segoe UI", 10), "large": ("Segoe UI", 32, "bold"), "medium": ("Segoe UI", 22, "bold"), "body_bold": ("Segoe UI", 10, "bold")}
    PADDING = {"large": 12, "medium": 8}
    def get_status_color(s): return COLORS.get("text_secondary", "#333")
    def get_health_color(h): return COLORS.get("success" if h >= 80 else "warning" if h >= 60 else "danger", "#333")
except Exception:
    COLORS = {"success": "#27ae60", "warning": "#f39c12", "danger": "#e74c3c", "text_secondary": "#7f8c8d", "primary": "#2c3e50"}
    FONTS = {"title": ("Segoe UI", 16, "bold"), "heading": ("Segoe UI", 12, "bold"), "body": ("Segoe UI", 10), "large": ("Segoe UI", 32, "bold"), "medium": ("Segoe UI", 22, "bold"), "body_bold": ("Segoe UI", 10, "bold")}
    PADDING = {"large": 12, "medium": 8}
    def get_status_color(s): return COLORS.get("text_secondary", "#333")
    def get_health_color(h): return COLORS.get("success" if h >= 80 else "warning" if h >= 60 else "danger", "#333")


def now_ms() -> int:
    return int(time.time() * 1000)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _fmt_cp(cp: float) -> str:
    if cp < 0:
        cp = 0.0
    if cp >= 10000:
        return f"{cp:,.0f}"
    if cp >= 1000:
        return f"{cp:,.1f}"
    if cp >= 100:
        return f"{cp:,.2f}"
    return f"{cp:,.3f}"


def _fmt_temp(t: Optional[float]) -> str:
    if t is None:
        return "--.-"
    return f"{t:.1f}"


class OperatorScreen(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        event_bus: Optional[Any] = None,
        config_manager: Optional[Any] = None,
        title: str = "ViscoAI",
    ):
        super().__init__(parent)
        self.event_bus = event_bus
        self.config_manager = config_manager

        self._cmd_seq = 0
        self._last_frame: Dict[str, Any] = {}
        self._nav_open_engineer: Optional[Callable[[], None]] = None
        self._nav_open_alarms: Optional[Callable[[], None]] = None
        self._nav_open_calibration: Optional[Callable[[], None]] = None

        # UI state vars
        self.var_mode = tk.StringVar(value="tabletop")
        self.var_source = tk.StringVar(value="local")
        self.var_status = tk.StringVar(value="BOOTING")
        self.var_visc = tk.StringVar(value="0.000")
        self.var_temp = tk.StringVar(value="--.-")
        self.var_freq = tk.StringVar(value="---.-")
        self.var_health = tk.IntVar(value=0)
        self.var_health_text = tk.StringVar(value="Health: 0%")
        self.var_conf_text = tk.StringVar(value="Confidence: 0%")
        self.var_last_error = tk.StringVar(value="")
        self.var_run_text = tk.StringVar(value="Start")
        self.var_log_text = tk.StringVar(value="Start Log")

        self._build_ui(title)
        self._hook_bus()

        # Start polling loop immediately
        print("[DEBUG UI] Starting Operator Screen polling loop...")
        self.after(250, self._poll_update)

    # ---------------- Navigation hooks ----------------

    def set_navigation_callbacks(
        self,
        *,
        open_engineer: Optional[Callable[[], None]] = None,
        open_alarms: Optional[Callable[[], None]] = None,
        open_calibration: Optional[Callable[[], None]] = None,
    ) -> None:
        self._nav_open_engineer = open_engineer
        self._nav_open_alarms = open_alarms
        self._nav_open_calibration = open_calibration

    # ---------------- UI Build ----------------

    def _build_ui(self, title: str) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Top bar - using Header style
        top = ttk.Frame(self, style="Header.TFrame", padding=15)
        top.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        top.columnconfigure(0, weight=1)

        if self.config_manager:
            # Helper to get nested keys
            def get_cfg(key, default=""):
                if hasattr(self.config_manager, "get"):
                    # Try direct get (for ConfigManager)
                    val = self.config_manager.get(key)
                    if val is not None:
                         return str(val)
                
                # Fallback: manual dict traversal
                if isinstance(self.config_manager, dict):
                    parts = key.split(".")
                    curr = self.config_manager
                    try:
                        for p in parts:
                            if isinstance(curr, dict):
                                curr = curr.get(p)
                            else:
                                return default
                        return str(curr) if curr is not None else default
                    except:
                        pass
                return default

            val = get_cfg("drivers.adc_type").lower()
            if val == "audio":
                is_audio = True

        if is_audio:
            title += " (AUDIO)"
        elif os.environ.get("MOCK_MODE", "1") == "1":
            title += " (SIMULATION)"
        
        lbl_title = ttk.Label(top, text=title, style="HeaderTitle.TLabel")
        lbl_title.grid(row=0, column=0, sticky="w")

        # Mode + source (display)
        right = ttk.Frame(top, style="Header.TFrame")
        right.grid(row=0, column=1, sticky="e")

        ttk.Label(right, text="Mode:", style="Header.TLabel").grid(row=0, column=0, padx=(0, 6), sticky="e")
        self.lbl_mode = ttk.Label(right, textvariable=self.var_mode, style="Header.TLabel")
        self.lbl_mode.grid(row=0, column=1, padx=(0, 12), sticky="e")

        ttk.Label(right, text="Control:", style="Header.TLabel").grid(row=0, column=2, padx=(0, 6), sticky="e")
        self.lbl_source = ttk.Label(right, textvariable=self.var_source, style="Header.TLabel")
        self.lbl_source.grid(row=0, column=3, padx=(0, 12), sticky="e")

        btn_eng = ttk.Button(right, text="Engineer", command=self._on_engineer, style="Blue.TButton")
        btn_eng.grid(row=0, column=4, sticky="e", padx=(12, 0))

        # Main readings
        main = ttk.Frame(self)
        main.grid(row=1, column=0, sticky="ew", padx=15, pady=10)
        main.columnconfigure(0, weight=2)
        main.columnconfigure(1, weight=1)
        main.columnconfigure(2, weight=1)

        # Viscosity card
        visc_card = ttk.Frame(main, style="Card.TFrame", padding=15)
        visc_card.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=0)
        visc_card.columnconfigure(0, weight=1)

        ttk.Label(visc_card, text="Viscosity (cP)", style="CardSecondary.TLabel").grid(row=0, column=0, sticky="w")
        self.lbl_visc = ttk.Label(visc_card, textvariable=self.var_visc, style="Value.TLabel")
        self.lbl_visc.grid(row=1, column=0, sticky="w", pady=(10, 0))

        # Temperature card
        temp_card = ttk.Frame(main, style="Card.TFrame", padding=15)
        temp_card.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=0)
        temp_card.columnconfigure(0, weight=1)
        ttk.Label(temp_card, text="Temperature (°C)", style="CardSecondary.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(temp_card, textvariable=self.var_temp, style="ValueMedium.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))

        # Frequency card
        freq_card = ttk.Frame(main, style="Card.TFrame", padding=15)
        freq_card.grid(row=0, column=2, sticky="ew", pady=0)
        freq_card.columnconfigure(0, weight=1)
        ttk.Label(freq_card, text="Frequency (Hz)", style="CardSecondary.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(freq_card, textvariable=self.var_freq, style="ValueMedium.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))

        # Status + health
        mid = ttk.Frame(self)
        mid.grid(row=2, column=0, sticky="nsew", padx=15, pady=(0, 10))
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(1, weight=1)

        status_card = ttk.Frame(mid, style="Card.TFrame", padding=15)
        status_card.grid(row=0, column=0, sticky="ew", pady=0)
        status_card.columnconfigure(1, weight=1)

        ttk.Label(status_card, text="Status:", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.lbl_status = ttk.Label(status_card, textvariable=self.var_status, style="Card.TLabel",
                                   font=("Segoe UI", 10, "bold"))
        self.lbl_status.grid(row=0, column=1, sticky="w", padx=(10, 0))

        ttk.Label(status_card, textvariable=self.var_conf_text, style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Label(status_card, textvariable=self.var_health_text, style="Card.TLabel").grid(
            row=1, column=1, sticky="w", padx=(10, 0), pady=(10, 0)
        )

        # Health progressbar
        try:
            self.pb_health = ttk.Progressbar(status_card, orient="horizontal", mode="determinate", maximum=100,
                                             style="Health.TProgressbar")
        except Exception:
            self.pb_health = ttk.Progressbar(status_card, orient="horizontal", mode="determinate", maximum=100)
        self.pb_health.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        # Error message
        self.lbl_error = ttk.Label(mid, textvariable=self.var_last_error, 
                                  foreground="#C0392B",
                                  font=("Segoe UI", 10))
        self.lbl_error.grid(row=3, column=0, sticky="w", pady=(8, 0))

        # Controls
        ctrl = ttk.Frame(self)
        ctrl.grid(row=3, column=0, sticky="ew", padx=15, pady=(0, 15))
        for i in range(6):
            ctrl.columnconfigure(i, weight=1)

        # Buttons with theme styles
        self.btn_run = ttk.Button(ctrl, textvariable=self.var_run_text, command=self._on_run_toggle,
                                 style="Green.TButton")
        self.btn_run.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.btn_stop = ttk.Button(ctrl, text="Stop", command=self._on_stop, style="Red.TButton")
        self.btn_stop.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        self.btn_log = ttk.Button(ctrl, textvariable=self.var_log_text, command=self._on_log_toggle)
        self.btn_log.grid(row=0, column=2, sticky="ew", padx=(0, 8))

        self.btn_export = ttk.Button(ctrl, text="Export", command=self._on_export)
        self.btn_export.grid(row=0, column=3, sticky="ew", padx=(0, 8))

        self.btn_alarms = ttk.Button(ctrl, text="Alarm Details", command=self._on_alarms)
        self.btn_alarms.grid(row=0, column=4, sticky="ew", padx=(0, 8))

        self.btn_cal = ttk.Button(ctrl, text="Calibration", command=self._on_calibration)
        self.btn_cal.grid(row=0, column=5, sticky="ew")

    # ---------------- Event bus wiring ----------------

    def _hook_bus(self) -> None:
        bus = self.event_bus
        if bus is None:
            return

        # subscribe frame updates if supported
        for sub_name in ["subscribe", "on"]:
            fn = getattr(bus, sub_name, None)
            if callable(fn):
                try:
                    fn("frame", self._on_frame_event)
                    fn("ui.frame", self._on_frame_event)
                    return
                except Exception:
                    continue

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        bus = self.event_bus
        if bus is None:
            return
        for pub_name in ["publish", "emit", "post"]:
            fn = getattr(bus, pub_name, None)
            if callable(fn):
                try:
                    fn(event, payload)
                    return
                except Exception:
                    continue

    # ---------------- Frame updates ----------------

    def _on_frame_event(self, payload: Any) -> None:
        if isinstance(payload, dict):
            self._apply_frame(payload)

    def _poll_update(self) -> None:
        """
        Fetch data from bus explicitly.
        """
        # print("[DEBUG UI] Poll...")  # Uncomment if loop isn't running at all

        if self.event_bus:
            # Check for standard 'latest_frame'
            fresh_frame = getattr(self.event_bus, "latest_frame", None)
            
            # If not found, try method
            if fresh_frame is None and hasattr(self.event_bus, "get_latest_frame"):
                try:
                    fresh_frame = self.event_bus.get_latest_frame()
                except Exception:
                    pass

            if fresh_frame and isinstance(fresh_frame, dict):
                # Apply it to the UI
                self._apply_frame(fresh_frame)
            else:
                pass
                # print("[DEBUG UI] No fresh frame found on bus.")
        
        # 2. Schedule next update
        self.after(250, self._poll_update)

    def _apply_frame(self, frame: Dict[str, Any]) -> None:
        # --- DEBUG PRINT ---
        # visc = frame.get("viscosity_cp", 0.0)
        # temp = frame.get("temp_c", 0.0)
        # status = frame.get("status", "UNKNOWN")
        # print(f"[DEBUG UI] Received Frame: Visc={visc:.3f} cP, Temp={temp:.1f} C, Status={status}")
        # -------------------

        self._last_frame = dict(frame)

        cp = frame.get("viscosity_cp_display", frame.get("viscosity_cp", 0.0))
        temp = frame.get("temp_c", None)
        freq = frame.get("freq_hz", None)
        status = frame.get("status", None)

        if not status:
            locked = bool(frame.get("locked", False))
            fault = bool(frame.get("fault_latched", False) or frame.get("fault", False))
            if fault:
                status = "ERROR"
            elif locked:
                status = "LOCKED"
            else:
                status = "SEARCHING"

        conf = _safe_int(frame.get("confidence_pct", 0), 0)
        health = _safe_int(frame.get("health_score", frame.get("health_pct", 0)), 0)

        # ---------------- TEMP TEST BLOCK ----------------
        # Force health bar to swing between 10% and 90% every 5 seconds
        # import time
        # if int(time.time()) % 10 < 5:
        #     health = 10
        # else:
        #     health = 90
        # -------------- END TEMP TEST BLOCK --------------

        mode = str(frame.get("mode", self.var_mode.get()) or self.var_mode.get()).lower()
        if mode not in ("tabletop", "inline"):
            mode = "tabletop"

        src = str(frame.get("control_source", self.var_source.get()) or self.var_source.get()).lower()
        if src not in ("local", "remote", "mixed"):
            src = "local"

        self.var_visc.set(_fmt_cp(_safe_float(cp, 0.0)))
        self.var_temp.set(_fmt_temp(temp if isinstance(temp, (int, float)) else None))
        self.var_freq.set(f"{_safe_float(freq, 0.0):.2f}" if isinstance(freq, (int, float)) else "---.-")

        self.var_status.set(str(status))
        self.var_conf_text.set(f"Confidence: {max(0, min(100, conf))}%")
        self.var_health.set(max(0, min(100, health)))
        self.var_health_text.set(f"Health: {max(0, min(100, health))}%")
        self.pb_health["value"] = max(0, min(100, health))
        
        # Color code status label
        status_color = get_status_color(status)
        self.lbl_status.config(foreground=status_color)
        
        # Color code health progress bar
        health_val = max(0, min(100, health))
        health_color = get_health_color(health_val)
        try:
            style = ttk.Style()
            style.configure("Health.TProgressbar", background=health_color)
        except Exception:
            pass

        self.var_mode.set(mode)
        self.var_source.set(src)

        err = frame.get("last_error") or frame.get("error") or ""
        self.var_last_error.set(str(err)[:180])

        self._refresh_controls_from_frame(frame)

    def _refresh_controls_from_frame(self, frame: Dict[str, Any]) -> None:
        mode = str(frame.get("mode", self.var_mode.get()) or "tabletop").lower()
        src = str(frame.get("control_source", self.var_source.get()) or "local").lower()

        running = bool(frame.get("running", frame.get("enabled", False)))
        logging_on = bool(frame.get("logging", False))
        fault = bool(frame.get("fault_latched", frame.get("fault", False)))

        # Button labels based on mode
        if mode == "inline":
            self.var_run_text.set("Pause" if running else "Enable")
        else:
            self.var_run_text.set("Start")

        self.var_log_text.set("Stop Log" if logging_on else "Start Log")

        # enable/disable rules
        start_allowed = (src != "remote") and (not fault)

        if mode == "inline":
            self.btn_run.state(["!disabled"] if start_allowed else ["disabled"])
            self.btn_stop.state(["!disabled"])
        else:
            # Tabletop: Start button disabled if already running
            self.btn_run.state(["!disabled"] if (start_allowed and not running) else ["disabled"])
            self.btn_stop.state(["!disabled"])

        self.btn_log.state(["!disabled"])
        self.btn_export.state(["!disabled"])

    # ---------------- Command handlers ----------------

    def _next_seq(self) -> int:
        self._cmd_seq += 1
        return self._cmd_seq

    def _send_cmd(self, cmd: str, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "cmd": str(cmd).upper(),
            "source": "local",
            "mode": self.var_mode.get(),
            "seq": self._next_seq(),
            "ts_ms": now_ms(),
        }
        if extra:
            payload.update(extra)
        self._emit("ui.command", payload)

    def _on_run_toggle(self) -> None:
        mode = self.var_mode.get().lower()
        running = bool(self._last_frame.get("running", self._last_frame.get("enabled", False)))

        if mode == "inline":
            if running:
                self._send_cmd("PAUSE")
            else:
                self._send_cmd("ENABLE")
        else:
            # Tabletop: Button is disabled if running, so we only handle START here
            self._send_cmd("START")

    def _on_stop(self) -> None:
        self._send_cmd("STOP")

    def _on_log_toggle(self) -> None:
        logging_on = bool(self._last_frame.get("logging", False))
        self._send_cmd("LOG_STOP" if logging_on else "LOG_START")

    def _on_export(self) -> None:
        self._send_cmd("EXPORT")

    def _on_alarms(self) -> None:
        if self._nav_open_alarms:
            self._nav_open_alarms()
        else:
            messagebox.showinfo("Alarms", "Alarm screen not connected yet.")

    def _on_calibration(self) -> None:
        if self._nav_open_calibration:
            self._nav_open_calibration()
        else:
            messagebox.showinfo("Calibration", "Calibration wizard not connected yet.")

    def _on_engineer(self) -> None:
        if self._nav_open_engineer:
            self._nav_open_engineer()
        else:
            messagebox.showinfo("Engineer", "Engineer screen not connected yet.")