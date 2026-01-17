# viscologic/ui/engineer_screen.py
# Engineer Screen (Tkinter)
# - Engineer password lock/unlock (session based)
# - Tabs: Overview, Settings, Calibration, Diagnostics, PLC/IO, Commissioning, Security
# - Uses duck-typed config_manager / auth_engineer / event_bus
#
# Listens:
#   - "frame" / "ui.frame"  (live status)
# Publishes:
#   - "ui.navigate"         (to operator / alarms / calibration / commissioning wizard)
#   - "ui.command"          (START/STOP/ALARM_ACK/ALARM_RESET)
#   - "settings.updated"    (optional broadcast)
#   - "diagnostics.export"  (optional)

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, Optional

try:
    from viscologic.ui.ui_styles import COLORS, FONTS, PADDING, get_status_color, get_health_color
except ImportError:
    COLORS = {"success": "#27ae60", "warning": "#f39c12", "danger": "#e74c3c", "text_secondary": "#7f8c8d", "primary": "#2c3e50"}
    FONTS = {"title": ("Segoe UI", 16, "bold"), "heading": ("Segoe UI", 12, "bold"), "body": ("Segoe UI", 10), "body_bold": ("Segoe UI", 10, "bold"), "subtitle": ("Segoe UI", 14, "bold")}
    PADDING = {"large": 12, "medium": 8}
    def get_status_color(s): return COLORS.get("text_secondary", "#333")
    def get_health_color(h): return COLORS.get("success" if h >= 80 else "warning" if h >= 60 else "danger", "#333")
except Exception as e:
    COLORS = {"success": "#27ae60", "warning": "#f39c12", "danger": "#e74c3c", "text_secondary": "#7f8c8d", "primary": "#2c3e50"}
    FONTS = {"title": ("Segoe UI", 16, "bold"), "heading": ("Segoe UI", 12, "bold"), "body": ("Segoe UI", 10), "body_bold": ("Segoe UI", 10, "bold"), "subtitle": ("Segoe UI", 14, "bold")}
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


def _safe_str(v: Any, default: str = "") -> str:
    try:
        if v is None:
            return default
        return str(v)
    except Exception:
        return default


class EngineerScreen(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        config_manager: Optional[Any] = None,
        auth_engineer: Optional[Any] = None,
        commissioning_manager: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        navigate_callback: Optional[Any] = None, # <--- 1. Add this argument
        title: str = "Engineer Mode",
    ) -> None:
        super().__init__(parent)

        self.nav_cb = navigate_callback          # <--- 2. Store it
        # Wrap dict config in ConfigManager if needed
        self.cfg = self._wrap_config(config_manager)
        self.auth = auth_engineer
        self.cm = commissioning_manager
        self.bus = event_bus

        self._cmd_seq = 0
        self._last_frame: Dict[str, Any] = {}

        # Session lock state
        self._unlocked = False

        # UI vars (overview)
        self.var_title = tk.StringVar(value=title)
        self.var_status = tk.StringVar(value="Locked")
        self.var_visc = tk.StringVar(value="--")
        self.var_temp = tk.StringVar(value="--.-")
        self.var_lock = tk.StringVar(value="SEARCHING")
        self.var_conf = tk.StringVar(value="--")
        self.var_health = tk.StringVar(value="--")
        self.var_freq = tk.StringVar(value="--.-")
        self.var_feature = tk.StringVar(value="--")

        # Lock UI vars
        self.var_pwd = tk.StringVar(value="")
        self.var_lock_msg = tk.StringVar(value="Enter engineer password.")

        # Settings vars
        self.var_mode = tk.StringVar(value="tabletop")              # tabletop / inline
        self.var_control = tk.StringVar(value="local")              # local / remote / mixed
        self.var_remote_enable = tk.BooleanVar(value=True)
        self.var_comm_loss = tk.StringVar(value="safe_stop")        # safe_stop / hold_last / pause
        self.var_inline_auto_resume = tk.BooleanVar(value=True)

        self.var_max_current_ma = tk.StringVar(value="150")
        self.var_max_temp_c = tk.StringVar(value="80")

        self.var_target_freq_hz = tk.StringVar(value="180.0")
        self.var_sweep_span_hz = tk.StringVar(value="5.0")
        self.var_sweep_step_hz = tk.StringVar(value="0.1")
        self.var_lockin_tau_s = tk.StringVar(value="0.2")

        # Security (change password)
        self.var_old_pwd = tk.StringVar(value="")
        self.var_new_pwd = tk.StringVar(value="")
        self.var_new_pwd2 = tk.StringVar(value="")

        self._build_ui()
        self._hook_bus()
        self._load_from_config()
        self.after(350, self._poll_refresh)

    # ---------------------------
    # UI build
    # ---------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.container = ttk.Frame(self)
        self.container.grid(row=0, column=0, sticky="nsew")
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(0, weight=1)

        # Locked view
        self.lock_view = ttk.Frame(self.container, style="Card.TFrame", padding=30)
        self.lock_view.grid(row=0, column=0, sticky="nsew")
        self.lock_view.columnconfigure(0, weight=1)

        ttk.Label(self.lock_view, textvariable=self.var_title, style="Card.TLabel", 
                 font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(self.lock_view, text="Engineer settings are protected. This is only for authorized users.",
                 style="CardSecondary.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 20))

        frm = ttk.Frame(self.lock_view)
        frm.grid(row=2, column=0, sticky="ew")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Password:", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.ent_pwd = ttk.Entry(frm, textvariable=self.var_pwd, show="•")
        self.ent_pwd.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self.ent_pwd.bind("<Return>", lambda _e: self._unlock())

        btns = ttk.Frame(self.lock_view)
        btns.grid(row=3, column=0, sticky="w", pady=(18, 0))

        ttk.Button(btns, text="Unlock", command=self._unlock, style="Green.TButton").grid(row=0, column=0, padx=(0, 10))
        ttk.Button(btns, text="Back to Operator", command=lambda: self._navigate("operator"), style="Blue.TButton").grid(row=0, column=1)

        ttk.Label(self.lock_view, textvariable=self.var_lock_msg, foreground="#C0392B", 
                 font=("Segoe UI", 10)).grid(row=4, column=0, sticky="w", pady=(16, 0))

        # Unlocked view
        self.main_view = ttk.Frame(self.container, padding=(12, 12, 12, 12))
        self.main_view.grid(row=0, column=0, sticky="nsew")
        self.main_view.columnconfigure(0, weight=1)
        self.main_view.rowconfigure(1, weight=1)

        # Header
        header = ttk.Frame(self.main_view)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, textvariable=self.var_title, font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        hbtn = ttk.Frame(header)
        hbtn.grid(row=0, column=1, sticky="e")

        ttk.Button(hbtn, text="Operator", command=lambda: self._navigate("operator")).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(hbtn, text="Alarms", command=lambda: self._navigate("alarms")).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(hbtn, text="Lock", command=self._lock).grid(row=0, column=2)

        ttk.Label(header, textvariable=self.var_status, style="Header.TLabel").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )

        # Notebook tabs
        self.nb = ttk.Notebook(self.main_view)
        self.nb.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

        self.tab_overview = ttk.Frame(self.nb)
        self.tab_settings = ttk.Frame(self.nb)
        self.tab_cal = ttk.Frame(self.nb)
        self.tab_diag = ttk.Frame(self.nb)
        self.tab_plc = ttk.Frame(self.nb)
        self.tab_comm = ttk.Frame(self.nb)
        self.tab_sec = ttk.Frame(self.nb)

        self.nb.add(self.tab_overview, text="Overview")
        self.nb.add(self.tab_settings, text="Settings")
        self.nb.add(self.tab_cal, text="Calibration")
        self.nb.add(self.tab_diag, text="Diagnostics")
        self.nb.add(self.tab_plc, text="PLC / IO")
        self.nb.add(self.tab_comm, text="Commissioning")
        self.nb.add(self.tab_sec, text="Security")

        self._build_tab_overview()
        self._build_tab_settings()
        self._build_tab_cal()
        self._build_tab_diag()
        self._build_tab_plc()
        self._build_tab_comm()
        self._build_tab_sec()

        # Start locked by default
        self._set_locked_ui(True)

    def _set_locked_ui(self, locked: bool) -> None:
        if locked:
            self.main_view.grid_remove()
            self.lock_view.grid()
            self._unlocked = False
            self.var_status.set("Locked")
            try:
                self.ent_pwd.focus_set()
            except Exception:
                pass
        else:
            self.lock_view.grid_remove()
            self.main_view.grid()
            self._unlocked = True
            self.var_status.set("Engineer unlocked (session).")

    # ---------------------------
    # Tabs
    # ---------------------------

    def _build_tab_overview(self) -> None:
        f = self.tab_overview
        f.columnconfigure(0, weight=1)

        card = ttk.Frame(f, style="Card.TFrame", padding=15)
        card.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        card.columnconfigure(1, weight=1)

        def row(r: int, label: str, var: tk.StringVar) -> None:
            ttk.Label(card, text=label, style="CardSecondary.TLabel").grid(row=r, column=0, sticky="w", pady=(8, 0))
            ttk.Label(card, textvariable=var, style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(row=r, column=1, sticky="w", pady=(8, 0))

        row(0, "Viscosity (cP):", self.var_visc)
        row(1, "Temperature (°C):", self.var_temp)
        row(2, "Lock Status:", self.var_lock)
        row(3, "Confidence (%):", self.var_conf)
        row(4, "Health Score:", self.var_health)
        row(5, "Resonant Frequency (Hz):", self.var_freq)
        row(6, "Feature Value:", self.var_feature)

        act = ttk.Frame(f, style="Card.TFrame", padding=15)
        act.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))

        ttk.Label(act, text="Quick Actions", style="Card.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")

        btns = ttk.Frame(act)
        btns.grid(row=1, column=0, sticky="w", pady=(12, 0))

        ttk.Button(btns, text="START", command=lambda: self._send_cmd("START"), style="Green.TButton").grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="STOP", command=lambda: self._send_cmd("STOP"), style="Red.TButton").grid(row=0, column=1, padx=(0, 8))
        ttk.Button(btns, text="ALARM ACK", command=lambda: self._send_cmd("ALARM_ACK")).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(btns, text="ALARM RESET", command=lambda: self._send_cmd("ALARM_RESET"), style="Red.TButton").grid(row=0, column=3)

        note = (
            "Rule: STOP always overrides START.\n"
            "During commissioning, START may be blocked by Safety Manager."
        )
        ttk.Label(act, text=note, style="CardSecondary.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))

    def _build_tab_settings(self) -> None:
        f = self.tab_settings
        f.columnconfigure(0, weight=1)

        card = ttk.Frame(f, padding=12, relief="groove")
        card.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="Core Settings", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

        # Mode / control
        ttk.Label(card, text="Mode:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        cbo_mode = ttk.Combobox(card, textvariable=self.var_mode, values=["tabletop", "inline"], state="readonly", width=18)
        cbo_mode.grid(row=1, column=1, sticky="w", pady=(10, 0))

        ttk.Label(card, text="Control Source:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        cbo_ctrl = ttk.Combobox(card, textvariable=self.var_control, values=["local", "remote", "mixed"], state="readonly", width=18)
        cbo_ctrl.grid(row=2, column=1, sticky="w", pady=(8, 0))

        ttk.Checkbutton(card, text="PLC Remote Enable", variable=self.var_remote_enable).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        ttk.Label(card, text="Comm-loss Action:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        cbo_loss = ttk.Combobox(card, textvariable=self.var_comm_loss, values=["safe_stop", "hold_last", "pause"], state="readonly", width=18)
        cbo_loss.grid(row=4, column=1, sticky="w", pady=(8, 0))

        ttk.Checkbutton(card, text="Inline Auto-Resume (after reboot)", variable=self.var_inline_auto_resume).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        # Safety
        ttk.Separator(card).grid(row=6, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(card, text="Safety Limits", font=("Segoe UI", 11, "bold")).grid(row=7, column=0, sticky="w")

        ttk.Label(card, text="Max Current (mA):").grid(row=8, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(card, textvariable=self.var_max_current_ma, width=14).grid(row=8, column=1, sticky="w", pady=(10, 0))

        ttk.Label(card, text="Max Temp (°C):").grid(row=9, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.var_max_temp_c, width=14).grid(row=9, column=1, sticky="w", pady=(8, 0))

        # DSP / sweep
        ttk.Separator(card).grid(row=10, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(card, text="Signal / Lock Settings", font=("Segoe UI", 11, "bold")).grid(row=11, column=0, sticky="w")

        ttk.Label(card, text="Target Freq (Hz):").grid(row=12, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(card, textvariable=self.var_target_freq_hz, width=14).grid(row=12, column=1, sticky="w", pady=(10, 0))

        ttk.Label(card, text="Sweep Span (Hz):").grid(row=13, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.var_sweep_span_hz, width=14).grid(row=13, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text="Sweep Step (Hz):").grid(row=14, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.var_sweep_step_hz, width=14).grid(row=14, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text="Lock-in Tau (s):").grid(row=15, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.var_lockin_tau_s, width=14).grid(row=15, column=1, sticky="w", pady=(8, 0))

        btns = ttk.Frame(card)
        btns.grid(row=16, column=0, columnspan=2, sticky="w", pady=(14, 0))
        ttk.Button(btns, text="Reload", command=self._load_from_config).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="Save", command=self._save_to_config).grid(row=0, column=1)

        ttk.Label(
            card,
            text="Note: STOP is always allowed. If Control=remote, UI START may be disabled by core logic.",
            style="CardSecondary.TLabel",
        ).grid(row=17, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _build_tab_cal(self) -> None:
        f = self.tab_cal
        f.columnconfigure(0, weight=1)

        box = ttk.Frame(f, style="Card.TFrame", padding=15)
        box.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        box.columnconfigure(0, weight=1)

        ttk.Label(box, text="Calibration", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            box,
            text="Use calibration wizard to add unlimited points (Air/Water/Std Oils/Custom).",
            style="CardSecondary.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        btns = ttk.Frame(box)
        btns.grid(row=2, column=0, sticky="w", pady=(12, 0))

        ttk.Button(btns, text="Open Calibration Wizard", command=lambda: self._navigate("calibration")).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="Open Operator Screen", command=lambda: self._navigate("operator")).grid(row=0, column=1)

    def _build_tab_diag(self) -> None:
        f = self.tab_diag
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        head = ttk.Frame(f, style="Card.TFrame", padding=15)
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        head.columnconfigure(0, weight=1)

        ttk.Label(head, text="Diagnostics", style="Card.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(head, text="Live system view for troubleshooting.", style="CardSecondary.TLabel").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )

        btns = ttk.Frame(head)
        btns.grid(row=0, column=1, sticky="e")
        ttk.Button(btns, text="Export Diagnostics", command=self._export_diagnostics).grid(row=0, column=0)

        self.txt_diag = tk.Text(f, wrap="word")
        self.txt_diag.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.txt_diag.insert("1.0", "Waiting for frames...\n")
        self.txt_diag.configure(state="disabled")

    def _build_tab_plc(self) -> None:
        f = self.tab_plc
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        head = ttk.Frame(f, style="Card.TFrame", padding=15)
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        head.columnconfigure(0, weight=1)

        ttk.Label(head, text="PLC / IO", style="Card.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")

        note = (
            "Remote control uses Modbus registers.\n"
            "Start/Stop can be from PLC depending on commissioning settings.\n"
            "Comm-loss action is configurable in Settings."
        )
        ttk.Label(head, text=note, style="CardSecondary.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))

        self.txt_plc = tk.Text(f, wrap="word")
        self.txt_plc.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.txt_plc.insert("1.0", "Waiting for Modbus status...\n")
        self.txt_plc.configure(state="disabled")

    def _build_tab_comm(self) -> None:
        f = self.tab_comm
        f.columnconfigure(0, weight=1)

        box = ttk.Frame(f, style="Card.TFrame", padding=15)
        box.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        box.columnconfigure(0, weight=1)

        ttk.Label(box, text="Commissioning", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.lbl_comm_state = ttk.Label(box, text="Commissioned: --", style="Card.TLabel")
        self.lbl_comm_state.grid(row=1, column=0, sticky="w", pady=(8, 0))

        btns = ttk.Frame(box)
        btns.grid(row=2, column=0, sticky="w", pady=(12, 0))

        ttk.Button(btns, text="Open Commissioning Wizard", command=lambda: self._navigate("commissioning", force=True)).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(btns, text="Lock Engineer Mode", command=self._lock).grid(row=0, column=1)

        ttk.Label(
            box,
            text="Commissioning is one-time lock for new machine.\nAfter completion, password is not asked on next boot.",
            style="CardSecondary.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(12, 0))

    def _build_tab_sec(self) -> None:
        f = self.tab_sec
        f.columnconfigure(0, weight=1)

        box = ttk.Frame(f, style="Card.TFrame", padding=15)
        box.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Engineer Security", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

        ttk.Label(box, text="Old Password:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(box, textvariable=self.var_old_pwd, show="•").grid(row=1, column=1, sticky="ew", pady=(10, 0))

        ttk.Label(box, text="New Password:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(box, textvariable=self.var_new_pwd, show="•").grid(row=2, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(box, text="Confirm New:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(box, textvariable=self.var_new_pwd2, show="•").grid(row=3, column=1, sticky="ew", pady=(8, 0))

        btns = ttk.Frame(box)
        btns.grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Button(btns, text="Change Password", command=self._change_password).grid(row=0, column=0)

        ttk.Label(
            box,
            text="If password change API is not supported by auth_engineer, this button will show error.",
            style="CardSecondary.TLabel",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

    # ---------------------------
    # Lock / Unlock
    # ---------------------------

    def _unlock(self) -> None:
        pwd = (self.var_pwd.get() or "").strip()
        if not pwd:
            self.var_lock_msg.set("Password required.")
            return

        if self._auth_verify(pwd):
            self.var_lock_msg.set("")
            self.var_pwd.set("")
            self._set_locked_ui(False)
            return

        self.var_lock_msg.set("Wrong password.")

    def _lock(self) -> None:
        self._auth_lock()
        self._set_locked_ui(True)

    # ---------------------------
    # Auth (duck-typed)
    # ---------------------------

    def _auth_verify(self, password: str) -> bool:
            a = self.auth
            if a is None:
                # If no auth module provided, allow unlock (for development)
                return True

            # 1. Explicitly check for 'login' method (This is what auth_engineer.py uses)
            if hasattr(a, "login"):
                try:
                    res = a.login(password)
                    # The backend returns an AuthResult object, so we must check '.ok'
                    if hasattr(res, "ok"):
                        return bool(res.ok)
                    # If it returns a simple boolean, just use it
                    return bool(res)
                except Exception:
                    return False

            # 2. Fallback for other naming conventions (legacy support)
            for fn_name in ("verify", "verify_password", "check_password", "authenticate"):
                fn = getattr(a, fn_name, None)
                if callable(fn):
                    try:
                        return bool(fn(password))
                    except Exception:
                        continue

            # 3. Attribute-based fallback (plain text attribute check)
            try:
                if hasattr(a, "password") and str(getattr(a, "password")) == password:
                    return True
            except Exception:
                pass
                
            return False

    def _auth_lock(self) -> None:
        a = self.auth
        if a is None:
            return
        for fn_name in ("lock", "reset_session", "logout"):
            fn = getattr(a, fn_name, None)
            if callable(fn):
                try:
                    fn()
                    return
                except Exception:
                    return

    # ---------------------------
    # Config wrapper
    # ---------------------------
    
    def _wrap_config(self, config: Optional[Any]) -> Optional[Any]:
        """
        If config is a dict, wrap it in a ConfigManager instance for save support.
        Otherwise return as-is.
        """
        if config is None:
            return None
        
        # If it's already a ConfigManager (has save method), use it
        if hasattr(config, "save") or hasattr(config, "set"):
            return config
        
        # If it's a dict, create a ConfigManager wrapper
        if isinstance(config, dict):
            try:
                from viscologic.core.config_manager import ConfigManager
                mgr = ConfigManager()
                mgr._config_dict = config  # Set the dict directly
                return mgr
            except Exception:
                # Fallback: return dict as-is (will use event bus fallback)
                return config
        
        return config

    # ---------------------------
    # Config read/write
    # ---------------------------

    def _load_from_config(self) -> None:
        self.var_mode.set(_safe_str(self._cfg_get("app.mode", "tabletop")).lower())
        self.var_control.set(_safe_str(self._cfg_get("app.control_source", "local")).lower())
        self.var_remote_enable.set(bool(self._cfg_get("protocols.remote_enable", True)))
        self.var_comm_loss.set(_safe_str(self._cfg_get("protocols.comm_loss_action", "safe_stop")).lower())
        self.var_inline_auto_resume.set(bool(self._cfg_get("app.inline_auto_resume", True)))

        self.var_max_current_ma.set(str(_safe_float(self._cfg_get("safety.max_current_ma", 150), 150)))
        self.var_max_temp_c.set(str(_safe_float(self._cfg_get("safety.max_temp_c", 80), 80)))

        self.var_target_freq_hz.set(str(_safe_float(self._cfg_get("dsp.target_freq_hz", 180.0), 180.0)))
        self.var_sweep_span_hz.set(str(_safe_float(self._cfg_get("dsp.sweep_span_hz", 5.0), 5.0)))
        self.var_sweep_step_hz.set(str(_safe_float(self._cfg_get("dsp.sweep_step_hz", 0.1), 0.1)))
        self.var_lockin_tau_s.set(str(_safe_float(self._cfg_get("dsp.lockin_tau_s", 0.2), 0.2)))

    def _save_to_config(self) -> None:
        # Validate
        try:
            max_i = float(self.var_max_current_ma.get().strip())
            max_t = float(self.var_max_temp_c.get().strip())
            tf = float(self.var_target_freq_hz.get().strip())
            span = float(self.var_sweep_span_hz.get().strip())
            step = float(self.var_sweep_step_hz.get().strip())
            tau = float(self.var_lockin_tau_s.get().strip())
        except Exception:
            messagebox.showerror("Validation", "Numeric fields must be valid numbers.")
            return

        if max_i <= 0 or max_i > 500:
            messagebox.showerror("Validation", "Max Current must be 1..500 mA")
            return
        if max_t <= 0 or max_t > 200:
            messagebox.showerror("Validation", "Max Temp must be 1..200 °C")
            return
        if tf <= 0 or tf > 1000:
            messagebox.showerror("Validation", "Target Freq must be 1..1000 Hz")
            return
        if span <= 0 or span > 200:
            messagebox.showerror("Validation", "Sweep Span must be 0..200 Hz")
            return
        if step <= 0 or step > 10:
            messagebox.showerror("Validation", "Sweep Step must be 0..10 Hz")
            return
        if tau <= 0 or tau > 10:
            messagebox.showerror("Validation", "Lock-in Tau must be 0..10 s")
            return

        # Write
        self._cfg_set("app.mode", (self.var_mode.get() or "tabletop").lower())
        self._cfg_set("app.control_source", (self.var_control.get() or "local").lower())
        self._cfg_set("app.inline_auto_resume", bool(self.var_inline_auto_resume.get()))

        self._cfg_set("protocols.remote_enable", bool(self.var_remote_enable.get()))
        self._cfg_set("protocols.comm_loss_action", (self.var_comm_loss.get() or "safe_stop").lower())

        self._cfg_set("safety.max_current_ma", float(max_i))
        self._cfg_set("safety.max_temp_c", float(max_t))

        self._cfg_set("dsp.target_freq_hz", float(tf))
        self._cfg_set("dsp.sweep_span_hz", float(span))
        self._cfg_set("dsp.sweep_step_hz", float(step))
        self._cfg_set("dsp.lockin_tau_s", float(tau))

        # Save to config
        save_success = self._cfg_save()
        
        if not save_success:
            messagebox.showwarning("Warning", "Settings were applied but may not have been saved to disk. Check logs for details.")

        # Apply settings to orchestrator via event bus
        self._emit("settings.updated", {
            "ts_ms": now_ms(),
            "mode": (self.var_mode.get() or "tabletop").lower(),
            "control_source": (self.var_control.get() or "local").lower(),
            "remote_enable": bool(self.var_remote_enable.get()),
            "comm_loss_action": (self.var_comm_loss.get() or "safe_stop").lower(),
            "inline_auto_resume": bool(self.var_inline_auto_resume.get()),
            "max_current_ma": float(max_i),
            "max_temp_c": float(max_t),
            "target_freq_hz": float(tf),
            "sweep_span_hz": float(span),
            "sweep_step_hz": float(step),
            "lockin_tau_s": float(tau),
        })
        
        if save_success:
            messagebox.showinfo("Saved", "Settings saved successfully and applied.")
        else:
            messagebox.showinfo("Applied", "Settings applied (save to disk may have failed).")

    def _cfg_get(self, key: str, default: Any) -> Any:
        c = self.cfg
        if c is None:
            return default
        fn = getattr(c, "get", None)
        if callable(fn):
            try:
                v = fn(key)
                return default if v is None else v
            except Exception:
                return default
        # dict-like
        try:
            if isinstance(c, dict):
                return c.get(key, default)
        except Exception:
            pass
        return default

    def _cfg_set(self, key: str, value: Any) -> None:
        c = self.cfg
        if c is None:
            self._emit("config.set", {"key": key, "value": value, "ts_ms": now_ms()})
            return
        for fn_name in ("set", "set_value", "put", "set_setting"):
            fn = getattr(c, fn_name, None)
            if callable(fn):
                try:
                    fn(key, value)
                    return
                except Exception:
                    continue
        self._emit("config.set", {"key": key, "value": value, "ts_ms": now_ms()})

    def _cfg_save(self) -> bool:
        """
        Save config to disk. Returns True if successful, False otherwise.
        """
        c = self.cfg
        if c is None:
            return False
        for fn_name in ("save", "persist", "flush", "write"):
            fn = getattr(c, fn_name, None)
            if callable(fn):
                try:
                    result = fn()
                    # Some save methods return bool, others return None
                    if result is False:
                        return False
                    return True
                except Exception as e:
                    # Log error but continue
                    try:
                        import logging
                        logging.getLogger("viscologic.engineer_screen").warning(f"Config save failed: {e}")
                    except Exception:
                        pass
                    continue
        return False

    # ---------------------------
    # Event bus
    # ---------------------------

    def _hook_bus(self):
        """
        Attach to event bus if possible,
        otherwise fall back to polling latest_frame.
        """
        if not self.bus:
            self._bus_subscribed = False
            return

        # If someone passed the CLASS instead of an instance
        if isinstance(self.bus, type):
            self._bus_subscribed = False
            return

        # Try EventBus-specific subscribe_frames method first (preferred)
        subscribe_frames = getattr(self.bus, "subscribe_frames", None)
        if callable(subscribe_frames):
            try:
                subscribe_frames(self._on_frame)
                self._bus_subscribed = True
                return
            except Exception:
                pass

        # Fallback to generic subscribe/on methods
        subscribe = getattr(self.bus, "subscribe", None) or getattr(self.bus, "on", None)

        if callable(subscribe):
            try:
                subscribe("frame", self._on_frame)
                subscribe("ui.frame", self._on_frame)
                self._bus_subscribed = True
                return
            except Exception:
                pass

        # If all subscription methods fail, use polling fallback
        self._bus_subscribed = False




    def _emit(self, topic: str, payload: Dict[str, Any]) -> None:
        if self.bus is None:
            return
        
        for pub_name in ("publish", "emit", "post", "put"):
            fn = getattr(self.bus, pub_name, None)
            if callable(fn):
                try:
                    fn(topic, payload)
                    return
                except Exception:
                    return

    def _send_cmd(self, cmd: str) -> None:
        self._cmd_seq += 1
        self._emit(
            "ui.command",
            {"cmd": str(cmd).upper(), "source": "local", "seq": self._cmd_seq, "ts_ms": now_ms()},
        )

    def _navigate(self, to: str, force: bool = False) -> None:
        # normalized routes used by app router
        if callable(self.nav_cb):
            # Check if callback supports force parameter
            import inspect
            sig = inspect.signature(self.nav_cb)
            if "force" in sig.parameters:
                self.nav_cb(to, force=force)
            else:
                # For commissioning, always force (engineer should have access)
                if to == "commissioning" or to == "commissioning_wizard":
                    # Try to call with force=True if supported
                    try:
                        self.nav_cb(to, force=True)
                    except TypeError:
                        # Fallback: call without force (may be blocked)
                        self.nav_cb(to)
                else:
                    self.nav_cb(to)
            return
        # Fallback (which we know fails, but keep for safety)
        route_map = {
            "operator": "operator",
            "alarms": "alarms",
            "calibration": "calibration_wizard",
            "commissioning": "commissioning_wizard",
        }
        target = route_map.get(to, to)
        # For commissioning, add force flag in payload
        payload: Dict[str, Any] = {"to": target}
        if to == "commissioning" or target == "commissioning_wizard":
            payload["force"] = True
        self._emit("ui.navigate", payload)

    # ---------------------------
    # Frame updates
    # ---------------------------

    def _on_frame(self, *args, **kwargs) -> None:
        """
        Handles frame updates from EventBus.
        EventBus calls: cb(frame_dict)
        Generic subscribe may call: cb(topic, payload) or cb(payload)
        """
        try:
            frame = None

            # If called with keyword argument
            if "payload" in kwargs:
                frame = kwargs["payload"]
            # If called with single argument (EventBus standard)
            elif len(args) == 1:
                frame = args[0]
            # If called with multiple arguments (topic, payload)
            elif len(args) >= 2:
                frame = args[-1]

            if isinstance(frame, dict):
                self._last_frame = dict(frame)
        except Exception:
            pass


    def _poll_refresh(self) -> None:
        # Always poll for latest frame (ensures we get data even if subscription fails)
        if self.bus:
            # Try get_latest_frame() method first (EventBus standard)
            get_frame = getattr(self.bus, "get_latest_frame", None)
            if callable(get_frame):
                try:
                    frame = get_frame()
                    if frame and isinstance(frame, dict):
                        self._on_frame(frame)
                except Exception:
                    pass
            # Fallback to latest_frame attribute (for compatibility)
            elif hasattr(self.bus, "latest_frame"):
                frame = getattr(self.bus, "latest_frame", {})
                if frame and isinstance(frame, dict):
                    self._on_frame(frame)

        # Update commissioning state label
        self._update_comm_state()

        # Update overview from last frame
        f = self._last_frame or {}
        
        visc = f.get("viscosity_cp", f.get("visc_cp", None))
        temp = f.get("temp_c", None)
        locked = f.get("status", "LOCKED" if bool(f.get("locked", False)) else "SEARCHING")
        conf = f.get("confidence", f.get("confidence_pct", None))
        health = f.get("health_score", f.get("health", None))
        freq = f.get("f_peak_hz", f.get("freq_hz", None))

        feature = f.get("feature_value", f.get("magnitude_clean", f.get("magnitude", None)))

        # Update UI variables
        if visc is None:
            self.var_visc.set("--")
        else:
            self.var_visc.set(f"{_safe_float(visc, 0.0):.3f}")

        if isinstance(temp, (int, float)):
            self.var_temp.set(f"{_safe_float(temp, 0.0):.1f}")
        else:
            self.var_temp.set("--.-")

        self.var_lock.set(_safe_str(locked, "SEARCHING"))

        if conf is None:
            self.var_conf.set("--")
        else:
            self.var_conf.set(f"{_safe_float(conf, 0.0):.1f}")

        if health is None:
            self.var_health.set("--")
        else:
            self.var_health.set(f"{_safe_float(health, 0.0):.1f}")

        self.var_freq.set(f"{_safe_float(freq, 0.0):.2f}" if freq is not None else "--.-")
        self.var_feature.set(f"{_safe_float(feature, 0.0):.6f}" if feature is not None else "--")

        # Diagnostics text
        if hasattr(self, "txt_diag"):
            self._render_diag_text()

        # PLC text
        if hasattr(self, "txt_plc"):
            self._render_plc_text()

        # Status line
        last_err = _safe_str(f.get("last_error", f.get("error", "")), "")
        if bool(f.get("fault_latched", False)):
            self.var_status.set(f"FAULT LATCHED: {last_err[:140]}")
        else:
            self.var_status.set(last_err[:160] if last_err else "OK")

        self.after(350, self._poll_refresh)

    def _render_diag_text(self) -> None:
        f = self._last_frame or {}
        
        # Format values with proper defaults
        def fmt(key: str, default: str = "", alt_keys: Optional[list] = None) -> str:
            if alt_keys:
                for k in [key] + alt_keys:
                    val = f.get(k)
                    if val is not None and val != "":
                        return str(val)
            val = f.get(key)
            return str(val) if val is not None and val != "" else default
        
        def fmt_float(key: str, default: str = "", alt_keys: Optional[list] = None, decimals: int = 3) -> str:
            if alt_keys:
                for k in [key] + alt_keys:
                    val = f.get(k)
                    if val is not None:
                        try:
                            return f"{float(val):.{decimals}f}"
                        except (ValueError, TypeError):
                            continue
            val = f.get(key)
            if val is not None:
                try:
                    return f"{float(val):.{decimals}f}"
                except (ValueError, TypeError):
                    pass
            return default
        
        lines = [
            "=== System State ===",
            f"State: {fmt('state', 'UNKNOWN', ['status'])}",
            f"Mode: {fmt('mode', 'unknown')}",
            f"Control Source: {fmt('control_source', 'unknown')}",
            f"Locked: {fmt('locked', 'False')}",
            f"Fault: {fmt('fault', 'False', ['fault_latched'])}",
            f"Alarm Active: {fmt('alarm_active', 'False', ['alarms'])}",
            "",
            "=== Measurements ===",
            f"Timestamp (s): {fmt_float('ts', '', ['timestamp_ms'], 3)}",
            f"Viscosity (cP): {fmt_float('viscosity_cp', '0.000', ['visc_cp'], 3)}",
            f"Temperature (°C): {fmt_float('temp_c', '0.0', None, 1)}",
            f"Frequency (Hz): {fmt_float('freq_hz', '0.00', ['f_peak_hz'], 2)}",
            f"Magnitude: {fmt_float('magnitude', '0.000', ['magnitude_clean'], 6)}",
            f"Phase (deg): {fmt_float('phase_deg', '0.0', None, 1)}",
            f"ADC Raw: {fmt_float('adc_raw', '0.000', ['adc'], 3)}",
            f"Duty: {fmt_float('duty', '0.000', None, 3)}",
            "",
            "=== Quality Metrics ===",
            f"Confidence (%): {fmt_float('confidence', '0', ['confidence_pct'], 1)}",
            f"Health Score: {fmt_float('health_score', '0', ['health_pct'], 1)}",
            f"Health OK: {fmt('health_ok', 'False')}",
            "",
            "=== System Info ===",
            f"Remote Enabled: {fmt('remote_enabled', 'False')}",
            f"Last Command Source: {fmt('last_cmd_source', 'unknown')}",
            f"Active Profile: {fmt('active_profile', 'Default')}",
            f"Last Fault Reason: {fmt('last_fault_reason', 'None', ['last_error', 'error'])}",
        ]
        
        text = "\n".join(lines) + "\n"

        self.txt_diag.configure(state="normal")
        self.txt_diag.delete("1.0", tk.END)
        self.txt_diag.insert("1.0", text)
        self.txt_diag.configure(state="disabled")

    def _render_plc_text(self) -> None:
        f = self._last_frame or {}
        
        # Format helper
        def fmt(key: str, default: str = "", alt_keys: Optional[list] = None) -> str:
            if alt_keys:
                for k in [key] + alt_keys:
                    val = f.get(k)
                    if val is not None and val != "":
                        return str(val)
            val = f.get(key)
            return str(val) if val is not None and val != "" else default
        
        # Get modbus status if available (may not be in frame)
        mb = f.get("modbus", None)
        if not isinstance(mb, dict):
            mb = {}
        
        # Get effective control settings from frame or UI vars
        control_source = fmt("control_source", self.var_control.get())
        remote_enabled = fmt("remote_enabled", str(self.var_remote_enable.get()))
        comm_loss_action = self.var_comm_loss.get()
        
        # Try to get from config if not in frame
        if not control_source or control_source == "":
            control_source = _safe_str(self._cfg_get("app.control_source", "local"))
        if remote_enabled == "":
            remote_enabled = str(bool(self._cfg_get("protocols.remote_enable", True)))
        if not comm_loss_action:
            comm_loss_action = _safe_str(self._cfg_get("protocols.comm_loss_action", "safe_stop"))
        
        lines = [
            "=== Modbus Communication ===",
            f"Status: {'Connected' if mb.get('connected') or mb.get('comm_ok') else 'Not Available'}",
            f"Last RX (ms): {mb.get('last_rx_ms', 'N/A')}",
            f"Last TX (ms): {mb.get('last_tx_ms', 'N/A')}",
            f"Comm OK: {mb.get('comm_ok', 'N/A')}",
            "",
            "Note: Detailed Modbus status requires ModbusServer to publish status in frame.",
            "",
            "=== Remote Control Configuration ===",
            f"Control Source: {control_source}",
            f"Remote Enable: {remote_enabled}",
            f"Comm Loss Action: {comm_loss_action}",
            "",
            "=== Current System State ===",
            f"State: {fmt('state', 'UNKNOWN', ['status'])}",
            f"Mode: {fmt('mode', 'unknown')}",
            f"Last Command Source: {fmt('last_cmd_source', 'local')}",
            f"Remote Enabled (effective): {fmt('remote_enabled', 'False')}",
            "",
            "=== PLC Control Behavior ===",
            "• START/STOP can be from PLC if:",
            "  - Remote Enable = True",
            "  - Control Source = 'remote' or 'mixed'",
            "• Comm-loss action applies when:",
            "  - Remote control is active",
            "  - Communication timeout occurs",
            f"• Current action on comm-loss: {comm_loss_action}",
        ]
        
        text = "\n".join(lines) + "\n"

        self.txt_plc.configure(state="normal")
        self.txt_plc.delete("1.0", tk.END)
        self.txt_plc.insert("1.0", text)
        self.txt_plc.configure(state="disabled")

    def _update_comm_state(self) -> None:
        commissioned = False
        if self.cm is not None:
            for name in ("is_commissioned", "get_commissioned", "commissioned"):
                if hasattr(self.cm, name):
                    try:
                        v = getattr(self.cm, name)
                        commissioned = bool(v() if callable(v) else v)
                        break
                    except Exception:
                        commissioned = False
        try:
            self.lbl_comm_state.config(text=f"Commissioned: {'YES' if commissioned else 'NO'}")
        except Exception:
            pass

    # ---------------------------
    # Diagnostics export
    # ---------------------------

    def _export_diagnostics(self) -> None:
        self._emit("diagnostics.export", {"ts_ms": now_ms(), "frame": self._last_frame})

        messagebox.showinfo(
            "Diagnostics",
            "Export request sent.\n(If generate_report/diagnostics module is wired, it will save a file.)",
        )

    # ---------------------------
    # Security: change password
    # ---------------------------

    def _change_password(self) -> None:
        oldp = (self.var_old_pwd.get() or "").strip()
        newp = (self.var_new_pwd.get() or "").strip()
        newp2 = (self.var_new_pwd2.get() or "").strip()

        if not oldp or not newp or not newp2:
            messagebox.showerror("Validation", "All password fields are required.")
            return
        if newp != newp2:
            messagebox.showerror("Validation", "New password confirmation does not match.")
            return
        if len(newp) < 4:
            messagebox.showerror("Validation", "New password too short (min 4 chars).")
            return

        a = self.auth
        if a is None:
            messagebox.showerror("Error", "auth_engineer not provided.")
            return

        # First verify old password to get session token
        login_result = None
        if hasattr(a, "login"):
            try:
                login_result = a.login(oldp)
                if not (hasattr(login_result, "ok") and login_result.ok):
                    messagebox.showerror("Error", "Old password is incorrect.")
                    return
            except Exception as e:
                messagebox.showerror("Error", f"Password verification failed:\n{e}")
                return

        # Now change password using session token
        session_token = None
        if login_result and hasattr(login_result, "session_token"):
            session_token = login_result.session_token

        # Try change_password method (new secure API)
        if hasattr(a, "change_password") and session_token:
            try:
                result = a.change_password(session_token, newp)
                if hasattr(result, "ok"):
                    if result.ok:
                        messagebox.showinfo("Done", "Engineer password updated successfully.")
                        self.var_old_pwd.set("")
                        self.var_new_pwd.set("")
                        self.var_new_pwd2.set("")
                        # Logout after password change for security
                        if hasattr(a, "logout"):
                            a.logout()
                        return
                    else:
                        reason = getattr(result, "reason", "Unknown error")
                        messagebox.showerror("Error", f"Password change failed: {reason}")
                        return
            except Exception as e:
                messagebox.showerror("Error", f"Password change failed:\n{e}")
                return

        # Fallback to legacy methods (for compatibility)
        for fn_name in ("set_password", "update_password"):
            fn = getattr(a, fn_name, None)
            if callable(fn):
                try:
                    # Try (old, new) pattern first
                    try:
                        out = fn(oldp, newp)
                    except TypeError:
                        # Try (new) pattern
                        out = fn(newp)
                    if isinstance(out, bool) and not out:
                        messagebox.showerror("Error", "Password change failed.")
                        return
                    messagebox.showinfo("Done", "Engineer password updated.")
                    self.var_old_pwd.set("")
                    self.var_new_pwd.set("")
                    self.var_new_pwd2.set("")
                    return
                except Exception as e:
                    messagebox.showerror("Error", f"Password change failed:\n{e}")
                    return

        messagebox.showerror("Error", "auth_engineer does not support password change API.")

