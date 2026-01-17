# viscologic/ui/alarms_screen.py
# Alarm Details UI (Tkinter): shows active alarms + history list. Supports Ack/Reset commands.

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional, Callable

try:
    from viscologic.ui.ui_styles import COLORS, FONTS, PADDING, get_status_color, get_health_color
except ImportError:
    COLORS = {"success": "#27ae60", "warning": "#f39c12", "danger": "#e74c3c", "text_secondary": "#7f8c8d", "primary": "#2c3e50"}
    FONTS = {"title": ("Segoe UI", 16, "bold"), "heading": ("Segoe UI", 12, "bold"), "body": ("Segoe UI", 10), "subtitle": ("Segoe UI", 14, "bold")}
    PADDING = {"large": 12, "medium": 8}
    def get_status_color(s): return COLORS.get("text_secondary", "#333")
    def get_health_color(h): return COLORS.get("success" if h >= 80 else "warning" if h >= 60 else "danger", "#333")
except Exception as e:
    COLORS = {"success": "#27ae60", "warning": "#f39c12", "danger": "#e74c3c", "text_secondary": "#7f8c8d", "primary": "#2c3e50"}
    FONTS = {"title": ("Segoe UI", 16, "bold"), "heading": ("Segoe UI", 12, "bold"), "body": ("Segoe UI", 10), "subtitle": ("Segoe UI", 14, "bold")}
    PADDING = {"large": 12, "medium": 8}
    def get_status_color(s): return COLORS.get("text_secondary", "#333")
    def get_health_color(h): return COLORS.get("success" if h >= 80 else "warning" if h >= 60 else "danger", "#333")



def now_ms() -> int:
    return int(time.time() * 1000)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


class AlarmsScreen(ttk.Frame):
    """
    Expects frames with:
      - alarms: dict{name: bool}
      - alarm_word: int (optional)
      - status_word: int (optional)
      - fault_latched: bool
      - last_error: str
      - ts_ms: int
    Publishes:
      - "ui.command": {cmd="ALARM_ACK"/"ALARM_RESET", source="local", seq, ts_ms}
    """

    def __init__(
        self,
        parent: tk.Misc,
        event_bus: Optional[Any] = None,
        navigate_callback: Optional[Callable[[str], None]] = None
        )-> None:
        super().__init__(parent)

        self.event_bus = event_bus
        self._cmd_seq = 0
        
        self.nav_cb = navigate_callback  # navigation callback stored
        self._history: List[Dict[str, Any]] = []
        self._max_hist = 200
        self._last_frame: Dict[str, Any] = {}

        self._build_ui()
        self._hook_bus()
        self.after(400, self._poll_refresh)

    # ---------------- Navigation ----------------
    def _navigate(self, to: str) -> None:
        # normalized routes used by app router
        print(f"AlarmScreen: Navigating to '{to}'")

        # <--- 3. Use the callback if available
        if callable(self.nav_cb):
            self.nav_cb(to)
            return

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        top.columnconfigure(0, weight=1)

        ttk.Label(top, text="Alarm Details", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")

        btns = ttk.Frame(top)
        btns.grid(row=0, column=2, sticky="e")

        self.btn_back = ttk.Button(btns, text="Go Back", command=lambda:self._navigate("operator"))
        self.btn_back.grid(row=0, column=0, padx=(0, 8))

        self.btn_ack = ttk.Button(btns, text="Acknowledge", command=self._on_ack)
        self.btn_ack.grid(row=0, column=1, padx=(0, 8))

        self.btn_reset = ttk.Button(btns, text="Reset Fault", command=self._on_reset)
        self.btn_reset.grid(row=0, column=2)

        # Active alarms
        active = ttk.Frame(self, style="Card.TFrame", padding=15)
        active.grid(row=1, column=0, sticky="ew", padx=15, pady=10)
        active.columnconfigure(0, weight=1)

        ttk.Label(active, text="Active Alarms", style="Card.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")

        self.active_list = tk.Listbox(active, height=6)
        self.active_list.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        # History
        hist = ttk.Frame(self, style="Card.TFrame", padding=15)
        hist.grid(row=2, column=0, sticky="nsew", padx=15, pady=(0, 15))
        hist.columnconfigure(0, weight=1)
        hist.rowconfigure(1, weight=1)

        ttk.Label(hist, text="Recent History", style="Card.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")

        cols = ("time", "type", "detail")
        self.tree = ttk.Treeview(hist, columns=cols, show="headings", height=10)
        self.tree.heading("time", text="Time")
        self.tree.heading("type", text="Type")
        self.tree.heading("detail", text="Detail")
        self.tree.column("time", width=160, anchor="w")
        self.tree.column("type", width=120, anchor="w")
        self.tree.column("detail", width=600, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        vsb = ttk.Scrollbar(hist, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=1, column=1, sticky="ns", pady=(8, 0))

        self.lbl_footer = ttk.Label(self, text="", foreground="#C0392B", font=("Segoe UI", 10))
        self.lbl_footer.grid(row=3, column=0, sticky="w", padx=15, pady=(0, 10))

    # ---------------- Bus ----------------

    def _hook_bus(self) -> None:
        bus = self.event_bus
        if bus is None:
            return
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

    def _next_seq(self) -> int:
        self._cmd_seq += 1
        return self._cmd_seq

    # ---------------- Frame processing ----------------

    def _on_frame_event(self, payload: Any) -> None:
        if isinstance(payload, dict):
            self._apply_frame(payload)

    def _apply_frame(self, frame: Dict[str, Any]) -> None:
        self._last_frame = dict(frame)

        # active alarms
        alarms = frame.get("alarms") or {}
        active_names = []
        if isinstance(alarms, dict):
            for k, v in alarms.items():
                if bool(v):
                    active_names.append(str(k))

        # Update active listbox with color coding
        self.active_list.delete(0, tk.END)
        acknowledged = bool(frame.get("alarm_acknowledged", False))
        
        if not active_names:
            self.active_list.insert(tk.END, "No active alarms")
            self.active_list.config(bg="#d4edda", fg="#155724")  # Green background
        else:
            for n in sorted(active_names):
                self.active_list.insert(tk.END, n)
            if acknowledged:
                self.active_list.config(bg="#fff3cd", fg="#856404")  # Orange/Yellow background (Acknowledged)
            else:
                self.active_list.config(bg="#f8d7da", fg="#721c24")  # Red background (Active)

        # footer shows last_error/fault with color coding
        fault = bool(frame.get("fault_latched", False))
        last_error = str(frame.get("last_error") or frame.get("error") or "")
        if fault:
            if acknowledged:
                self.lbl_footer.config(text=f"ACKNOWLEDGED FAULT: {last_error[:140]}", foreground="#856404")
            else:
                self.lbl_footer.config(text=f"FAULT: {last_error[:160]}", foreground="#C0392B")
        else:
            self.lbl_footer.config(text=last_error[:160], foreground="#7f8c8d")

        # record history transitions
        self._update_history(frame, active_names)

    def _update_history(self, frame: Dict[str, Any], active_names: List[str]) -> None:
        ts = int(frame.get("ts_ms") or now_ms())
        tstr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts / 1000.0))

        # store current snapshot in history when:
        # - new fault appears
        # - alarm count changes
        # - last_error changes (non-empty)
        last = self._history[-1] if self._history else {}
        last_active = last.get("active", [])
        last_err = str(last.get("last_error") or "")

        cur_err = str(frame.get("last_error") or frame.get("error") or "")
        changed = (sorted(active_names) != sorted(last_active)) or (cur_err and cur_err != last_err)

        if not changed:
            return

        item = {
            "ts": ts,
            "time": tstr,
            "active": list(active_names),
            "last_error": cur_err,
        }
        self._history.append(item)
        if len(self._history) > self._max_hist:
            self._history = self._history[-self._max_hist :]

        # re-render tree
        self._render_tree()

    def _render_tree(self) -> None:
        # clear
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        # newest first
        for item in reversed(self._history[-200:]):
            active = item.get("active") or []
            if active:
                detail = ", ".join(active[:12]) + (" ..." if len(active) > 12 else "")
                typ = "ALARM"
            else:
                detail = str(item.get("last_error") or "")[:200]
                typ = "INFO" if detail else "STATE"
            self.tree.insert("", "end", values=(item.get("time", ""), typ, detail))

    def _poll_refresh(self) -> None:
        # keep buttons enabled even without frames
        fault = bool(self._last_frame.get("fault_latched", False))
        # reset only meaningful if fault latched
        if fault:
            self.btn_reset.state(["!disabled"])
        else:
            self.btn_reset.state(["disabled"])
        self.btn_ack.state(["!disabled"])
        self.after(400, self._poll_refresh)

    # ---------------- Commands ----------------

    def _send_cmd(self, cmd: str) -> None:
        self._emit(
            "ui.command",
            {
                "cmd": str(cmd).upper(),
                "source": "local",
                "seq": self._next_seq(),
                "ts_ms": now_ms(),
            },
        )

    def _on_ack(self) -> None:
        self._send_cmd("ALARM_ACK")
        messagebox.showinfo("Acknowledge", "Alarm acknowledge command sent.")

    def _on_reset(self) -> None:
        if not bool(self._last_frame.get("fault_latched", False)):
            messagebox.showinfo("Reset", "No latched fault to reset.")
            return
        if messagebox.askyesno("Reset Fault", "Reset fault latch?"):
            self._send_cmd("ALARM_RESET")
