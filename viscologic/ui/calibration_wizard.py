# viscologic/ui/calibration_wizard.py
# Calibration Wizard (Tkinter)
# Goals:
# - Air / Water / Oil (and unlimited custom points)
# - "Capture Point" takes current stable feature from live frame (lock-in magnitude/feature_value)
# - User enters known viscosity (cP) + name
# - Saves point to calibration_store, rebuilds calibration_lut (if provided)
# - Supports multiple profiles (fluid/products) and lets user select profile
#
# Events:
# - listens: "frame" / "ui.frame"
# - publishes: "ui.command" (START/STOP, etc optional), "calibration.updated", "ui.navigate"

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Any, Dict, Optional, Callable, List, Tuple

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


class CalibrationWizard(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        calibration_store: Optional[Any] = None,
        calibration_lut: Optional[Any] = None,
        config_manager: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        navigate_callback: Optional[Any] = None, # <--- 1. Add this argument
        on_done: Optional[Callable[[], None]] = None,
        title: str = "Calibration Wizard",
    ) -> None:
        super().__init__(parent)

        self.store = calibration_store
        self.lut = calibration_lut
        self.cfg = config_manager
        self.bus = event_bus
        self.nav_cb = navigate_callback  # <--- 2. Store it
        self.on_done = on_done

        self._cmd_seq = 0
        self._last_frame: Dict[str, Any] = {}

        # UI vars
        self.var_profile = tk.StringVar(value="")
        self.var_status = tk.StringVar(value="Waiting for live signal...")
        self.var_feature = tk.StringVar(value="--")
        self.var_temp = tk.StringVar(value="--.-")
        self.var_locked = tk.StringVar(value="Searching")

        self.var_known_cp = tk.StringVar(value="1.0")
        self.var_point_name = tk.StringVar(value="Water")
        self.var_unit = tk.StringVar(value="cP")

        # Profiles: depends on calibration backend.
        # In the current implementation, CalibrationStore uses profile as a STRING (not an integer id).
        self._profiles: List[str] = []
        self._lut_model: Optional[Any] = None

        self._build_ui(title)
        self._hook_bus()
        self._load_profiles()

        self.after(300, self._poll_refresh)

    # ---------------- UI ----------------

    def _build_ui(self, title: str) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, style="Header.TFrame", padding=15)
        top.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        top.columnconfigure(0, weight=1)

        ttk.Label(top, text=title, style="HeaderTitle.TLabel").grid(row=0, column=0, sticky="w")

        # Profile row
        prof = ttk.Frame(top)
        prof.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        prof.columnconfigure(1, weight=1)

        ttk.Label(prof, text="Profile:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.cbo_profile = ttk.Combobox(prof, textvariable=self.var_profile, state="readonly")
        self.cbo_profile.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.cbo_profile.bind("<<ComboboxSelected>>", lambda _e: self._refresh_points_table())

        ttk.Button(prof, text="New Profile", command=self._new_profile).grid(row=0, column=2, sticky="e")

        # Live snapshot card
        live = ttk.Frame(self, style="Card.TFrame", padding=15)
        live.grid(row=1, column=0, sticky="ew", padx=15, pady=10)
        live.columnconfigure(1, weight=1)

        ttk.Label(live, text="Live Signal", style="Card.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")

        ttk.Label(live, text="Feature:", style="CardSecondary.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Label(live, textvariable=self.var_feature, style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(row=1, column=1, sticky="w", pady=(12, 0))

        ttk.Label(live, text="Temp (°C):", style="CardSecondary.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(live, textvariable=self.var_temp, style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(row=2, column=1, sticky="w", pady=(8, 0))

        ttk.Label(live, text="Lock:", style="CardSecondary.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Label(live, textvariable=self.var_locked, style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(row=3, column=1, sticky="w", pady=(8, 0))

        ttk.Label(live, textvariable=self.var_status, style="CardSecondary.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))

        # Points table + Capture panel
        mid = ttk.Frame(self)
        mid.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        mid.columnconfigure(0, weight=2)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(0, weight=1)

        # Table
        tbl = ttk.Frame(mid, style="Card.TFrame", padding=15)
        tbl.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=0)
        tbl.columnconfigure(0, weight=1)
        tbl.rowconfigure(1, weight=1)

        ttk.Label(tbl, text="Calibration Points", style="Card.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")

        cols = ("name", "known_cp", "feature", "temp_c", "time")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings", height=10)
        self.tree.heading("name", text="Name")
        self.tree.heading("known_cp", text="Known (cP)")
        self.tree.heading("feature", text="Feature")
        self.tree.heading("temp_c", text="Temp")
        self.tree.heading("time", text="Captured At")

        self.tree.column("name", width=160, anchor="w")
        self.tree.column("known_cp", width=110, anchor="e")
        self.tree.column("feature", width=140, anchor="e")
        self.tree.column("temp_c", width=80, anchor="e")
        self.tree.column("time", width=170, anchor="w")

        self.tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        vsb = ttk.Scrollbar(tbl, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=1, column=1, sticky="ns", pady=(8, 0))

        btn_row = ttk.Frame(tbl)
        btn_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(btn_row, text="Delete Selected", command=self._delete_selected, style="Red.TButton").grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btn_row, text="Rebuild LUT", command=self._rebuild_lut, style="Green.TButton").grid(row=0, column=1)

        # Capture panel
        cap = ttk.Frame(mid, style="Card.TFrame", padding=15)
        cap.grid(row=0, column=1, sticky="nsew", pady=0)
        cap.columnconfigure(1, weight=1)

        ttk.Label(cap, text="Capture New Point", style="Card.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(cap, text="Name:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(cap, textvariable=self.var_point_name).grid(row=1, column=1, sticky="ew", pady=(10, 0))

        ttk.Label(cap, text="Known Viscosity (cP):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(cap, textvariable=self.var_known_cp).grid(row=2, column=1, sticky="ew", pady=(8, 0))

        ttk.Button(cap, text="Capture Point (Use Live Feature)", command=self._capture_point).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0)
        )

        ttk.Separator(cap).grid(row=4, column=0, columnspan=2, sticky="ew", pady=14)

        ttk.Button(cap, text="Quick: Air (0)", command=lambda: self._quick_set("Air", 0.0)).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )
        ttk.Button(cap, text="Quick: Water (1)", command=lambda: self._quick_set("Water", 1.0)).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )
        ttk.Button(cap, text="Quick: Std Oil (100)", command=lambda: self._quick_set("Std Oil", 100.0)).grid(
            row=7, column=0, columnspan=2, sticky="ew"
        )

        # Footer
        foot = ttk.Frame(self, padding=15)
        foot.grid(row=3, column=0, sticky="ew", padx=15, pady=10)
        foot.columnconfigure(0, weight=1)

        ttk.Button(foot, text="Done", command=self._done, style="Green.TButton").grid(row=0, column=1, sticky="e")
        ttk.Button(foot, text="Go Operator", command=lambda: self._navigate("operator"), style="Blue.TButton").grid(row=0, column=2, sticky="e", padx=(8, 0))

    # ---------------- Bus ----------------

    def _hook_bus(self) -> None:
        """
        Attach to event bus if possible.
        IMPORTANT: Tkinter is not thread-safe, so we don't update UI directly from bus callbacks.
        We only store frames in _on_frame(), and the Tkinter after() loop renders them.
        """
        if self.bus is None:
            self._bus_subscribed = False
            return

        # If someone passed the CLASS instead of an instance
        if isinstance(self.bus, type):
            self._bus_subscribed = False
            return

        # Prefer EventBus.subscribe_frames(cb) if present
        subscribe_frames = getattr(self.bus, "subscribe_frames", None)
        if callable(subscribe_frames):
            try:
                subscribe_frames(self._on_frame)
                self._bus_subscribed = True
                return
            except Exception:
                pass

        # Fallback: generic subscribe/on(topic, cb)
        subscribe = getattr(self.bus, "subscribe", None) or getattr(self.bus, "on", None)
        if callable(subscribe):
            try:
                subscribe("frame", self._on_frame)
                subscribe("ui.frame", self._on_frame)
                self._bus_subscribed = True
                return
            except Exception:
                pass

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

    # ---------------- Profiles ----------------

    def _load_profiles(self) -> None:
        """
        Load available calibration profiles.

        The current CalibrationStore (`viscologic/model/calibration_store.py`) uses:
          - profile as STRING (e.g. "Default", "ISO46")
          - active selection stored in calibration_active(mode, profile, active_set_id)
        """
        self._profiles = []

        # Prefer modern CalibrationStore (profile as string)
        if self.store is not None and hasattr(self.store, "db"):
            try:
                db = getattr(self.store, "db", None)
                q = getattr(db, "query_all", None)
                if callable(q):
                    rows = q(
                        """
                        SELECT DISTINCT profile FROM calibration_active
                        UNION
                        SELECT DISTINCT profile FROM sensor_calibration_points
                        ORDER BY profile ASC
                        """
                    )
                    for r in rows or []:
                        prof = (r or {}).get("profile")
                        if isinstance(prof, str) and prof.strip():
                            self._profiles.append(prof.strip())
            except Exception:
                pass

        # Fallback: older store may expose list_profiles()
        if not self._profiles and self.store is not None:
            fn = getattr(self.store, "list_profiles", None)
            if callable(fn):
                try:
                    rows = fn()
                    for r in rows or []:
                        if isinstance(r, dict):
                            name = r.get("name")
                            if isinstance(name, str) and name.strip():
                                self._profiles.append(name.strip())
                        elif isinstance(r, (list, tuple)) and len(r) >= 1:
                            name = r[-1]
                            if isinstance(name, str) and name.strip():
                                self._profiles.append(name.strip())
                except Exception:
                    pass

        # Ensure at least one default profile exists
        if not self._profiles:
            self._profiles = ["Default"]

        # Ensure active set exists for current selection (best-effort)
        prof0 = self._profiles[0]
        try:
            if self.store is not None and hasattr(self.store, "ensure_active_set"):
                self.store.ensure_active_set(self._get_mode(), prof0)
        except Exception:
            pass

        # Update combobox
        self.cbo_profile["values"] = list(self._profiles)

        if not (self.var_profile.get() or "").strip():
            self.var_profile.set(self._profiles[0])

        self._refresh_points_table()

    def _get_mode(self) -> str:
        # config_manager is usually a dict in MainWindowApp
        c = self.cfg
        try:
            if isinstance(c, dict):
                return str((c.get("app", {}) or {}).get("mode", "tabletop"))
            g = getattr(c, "get", None)
            if callable(g):
                return str(g("app.mode", "tabletop"))
        except Exception:
            pass
        return "tabletop"

    def _get_selected_profile(self) -> str:
        name = (self.var_profile.get() or "").strip()
        if name:
            return name
        return self._profiles[0] if self._profiles else "Default"

    def _new_profile(self) -> None:
        nm = simpledialog.askstring("New Profile", "Enter profile name (Product/Fluid):")
        if not nm:
            return
        if self.store is None:
            messagebox.showerror("Error", "Calibration store not available.")
            return

        name = str(nm).strip()
        if not name:
            return

        # Modern CalibrationStore: create profile by ensuring active set exists
        if hasattr(self.store, "ensure_active_set"):
            try:
                self.store.ensure_active_set(self._get_mode(), name)
                if name not in self._profiles:
                    self._profiles.append(name)
                    self._profiles = sorted(set(self._profiles), key=lambda s: s.lower())
                    self.cbo_profile["values"] = list(self._profiles)
                self.var_profile.set(name)
                self._refresh_points_table()
                return
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create profile:\n{e}")
                return

        # Legacy store API: create_profile(name) -> id
        fn = getattr(self.store, "create_profile", None)
        if callable(fn):
            try:
                fn(name)
                if name not in self._profiles:
                    self._profiles.append(name)
                    self.cbo_profile["values"] = list(self._profiles)
                self.var_profile.set(name)
                self._refresh_points_table()
                return
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create profile:\n{e}")
                return

        messagebox.showerror("Error", "Calibration store does not support profile creation.")

    # ---------------- Live frame ----------------

    def _on_frame(self, *args, **kwargs) -> None:
        """
        Store the latest frame.
        DO NOT call _render_live() here because this callback may run off the Tkinter thread.
        """
        try:
            payload = None
            if "payload" in kwargs:
                payload = kwargs["payload"]
            elif len(args) == 1:
                payload = args[0]
            elif len(args) >= 2:
                payload = args[-1]

            if isinstance(payload, dict):
                self._last_frame = dict(payload)
        except Exception:
            pass

    def _render_live(self, frame: Dict[str, Any]) -> None:
        # feature selection order
        feature = frame.get("feature_value")
        if feature is None:
            # follow model.feature_key if config has it
            feature_key = "magnitude_clean"
            if self.cfg is not None:
                try:
                    g = getattr(self.cfg, "get", None)
                    if callable(g):
                        feature_key = g("model.feature_key") or feature_key
                except Exception:
                    pass
            feature = frame.get(feature_key, frame.get("magnitude_clean", frame.get("magnitude")))

        temp = frame.get("temp_c")
        locked = frame.get("locked")
        status = frame.get("status")

        if status:
            lock_text = str(status)
        else:
            lock_text = "LOCKED" if bool(locked) else "SEARCHING"

        self.var_feature.set(f"{_safe_float(feature, 0.0):.6f}" if feature is not None else "--")
        self.var_temp.set(f"{_safe_float(temp, 0.0):.1f}" if isinstance(temp, (int, float)) else "--.-")
        self.var_locked.set(lock_text)

        if bool(frame.get("fault_latched", False)):
            self.var_status.set("Fault latched: reset alarms before calibration.")
        else:
            self.var_status.set("Ready. Ensure stable lock before capturing points.")

    def _poll_refresh(self) -> None:
        # Always poll for latest frame (ensures we update even if subscription is not available)
        if self.bus:
            get_frame = getattr(self.bus, "get_latest_frame", None)
            if callable(get_frame):
                try:
                    frame = get_frame()
                    if isinstance(frame, dict) and frame:
                        self._last_frame = dict(frame)
                except Exception:
                    pass
            elif hasattr(self.bus, "latest_frame"):
                try:
                    frame = getattr(self.bus, "latest_frame", None)
                    if isinstance(frame, dict) and frame:
                        self._last_frame = dict(frame)
                except Exception:
                    pass

        # Render from Tkinter thread
        if self._last_frame:
            self._render_live(self._last_frame)
        self.after(300, self._poll_refresh)

    # ---------------- Points ----------------

    def _refresh_points_table(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        prof = self._get_selected_profile()
        pts = self._list_points(prof)

        for p in pts:
            self.tree.insert(
                "",
                "end",
                values=(
                    p.get("name", ""),
                    f'{_safe_float(p.get("known_cp"), 0.0):.3f}',
                    f'{_safe_float(p.get("feature"), 0.0):.6f}',
                    f'{_safe_float(p.get("temp_c"), 0.0):.1f}' if p.get("temp_c") is not None else "--",
                    p.get("time", ""),
                ),
                tags=(str(p.get("id", "")),),
            )

    def _list_points(self, profile: str) -> List[Dict[str, Any]]:
        if self.store is None or not profile:
            return []

        mode = self._get_mode()

        # Modern CalibrationStore: get_active_points(mode, profile) -> List[CalibrationPoint]
        fn = getattr(self.store, "get_active_points", None)
        if callable(fn):
            try:
                rows = fn(mode, profile)
                out: List[Dict[str, Any]] = []
                for p in rows or []:
                    # p may be dataclass CalibrationPoint
                    try:
                        ts = int(getattr(p, "ts_ms", 0) or 0)
                        tstr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts / 1000.0)) if ts else ""
                        out.append(
                            {
                                "id": int(getattr(p, "id", 0) or 0),
                                "name": str(getattr(p, "label", "") or ""),
                                "known_cp": float(getattr(p, "viscosity_cp", 0.0) or 0.0),
                                "feature": float(getattr(p, "amp_v", 0.0) or 0.0),
                                "temp_c": getattr(p, "temp_c", None),
                                "time": tstr,
                            }
                        )
                    except Exception:
                        continue
                return out
            except Exception:
                return []

        # Legacy store API (dict rows)
        fn2 = getattr(self.store, "list_points", None)
        if callable(fn2):
            try:
                rows = fn2(profile)  # some stores may accept profile name
                return [r for r in (rows or []) if isinstance(r, dict)]
            except Exception:
                return []

        return []

    def _capture_point(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            messagebox.showerror("Error", "No profile selected.")
            return
        if self.store is None:
            messagebox.showerror("Error", "Calibration store not available.")
            return

        # must have a usable feature
        frame = self._last_frame or {}
        feature = frame.get("feature_value")
        if feature is None:
            feature = frame.get("magnitude_clean", frame.get("magnitude"))
        if feature is None:
            messagebox.showerror("Error", "Live feature not available yet.")
            return

        # recommend capture when locked
        if not bool(frame.get("locked", False)) and str(frame.get("status", "")).upper() != "LOCKED":
            if not messagebox.askyesno("Not Locked", "Signal not LOCKED. Capture anyway?"):
                return

        try:
            known_cp = float((self.var_known_cp.get() or "").strip())
        except Exception:
            messagebox.showerror("Error", "Known viscosity must be numeric.")
            return

        name = (self.var_point_name.get() or "Point").strip()
        temp = frame.get("temp_c")
        ts = int(frame.get("ts_ms") or frame.get("timestamp_ms") or now_ms())

        # Modern CalibrationStore: add_point(mode, profile, set_id, ...)
        if hasattr(self.store, "ensure_active_set") and hasattr(self.store, "add_point"):
            try:
                mode = self._get_mode()
                set_id = int(self.store.ensure_active_set(mode, profile))
                phase = frame.get("phase_deg", frame.get("phase", 0.0))
                freq = frame.get("freq_hz", frame.get("f_peak_hz", 0.0))
                conf = frame.get("confidence_pct", frame.get("confidence", 0))

                self.store.add_point(
                    mode=mode,
                    profile=profile,
                    set_id=set_id,
                    label=name,
                    viscosity_cp=float(known_cp),
                    amp_v=float(_safe_float(feature, 0.0)),
                    phase_deg=float(_safe_float(phase, 0.0)),
                    freq_hz=float(_safe_float(freq, 0.0)),
                    confidence=int(_safe_float(conf, 0.0)),
                    temp_c=float(temp) if isinstance(temp, (int, float)) else None,
                    ts_ms=ts,
                )
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save point:\n{e}")
                return
        else:
            messagebox.showerror("Error", "Calibration store does not support adding points.")
            return

        self._rebuild_lut(silent=True)

        self._emit("calibration.updated", {"profile": profile, "ts_ms": now_ms()})
        self.var_status.set(f"Saved point '{name}' ({known_cp} cP). LUT updated.")
        self._refresh_points_table()

    def _quick_set(self, name: str, cp: float) -> None:
        self.var_point_name.set(name)
        self.var_known_cp.set(str(cp))
        self._capture_point()

    def _delete_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Delete", "Select a point to delete.")
            return
        if not messagebox.askyesno("Delete", "Delete selected calibration point?"):
            return

        profile = self._get_selected_profile()
        if not profile or self.store is None:
            return

        # We stored id inside tag if present; else use row name+feature match delete
        iid = sel[0]
        vals = self.tree.item(iid, "values")
        name = vals[0]
        feature = _safe_float(vals[2], 0.0)
        known = _safe_float(vals[1], 0.0)

        deleted = False

        # Prefer direct delete by id for current CalibrationStore schema
        tags = self.tree.item(iid, "tags")
        if tags and hasattr(self.store, "db"):
            try:
                point_id = int(tags[0])
                db = getattr(self.store, "db", None)
                ex = getattr(db, "exec", None)
                if callable(ex):
                    ex("DELETE FROM sensor_calibration_points WHERE id=?", (point_id,))
                    deleted = True
            except Exception:
                deleted = False

        if not deleted:
            messagebox.showwarning("Delete", "Could not delete point.")
            return

        self._rebuild_lut(silent=True)
        self._emit("calibration.updated", {"profile": profile, "ts_ms": now_ms()})
        self._refresh_points_table()

    def _rebuild_lut(self, silent: bool = False) -> None:
        """
        Rebuild the LUT from store points.
        Works even if LUT object is optional.
        """
        profile = self._get_selected_profile()
        if not profile:
            return

        if self.lut is None:
            if not silent:
                messagebox.showinfo("LUT", "No LUT module linked. Points saved only.")
            return

        mode = self._get_mode()

        # Preferred: CalibrationLUT.build(mode, profile, cal_points) -> LutModel
        fn_build = getattr(self.lut, "build", None)
        fn_eval = getattr(self.lut, "evaluate", None)
        if callable(fn_build) and callable(fn_eval) and hasattr(self.store, "get_active_points"):
            try:
                cal_points = self.store.get_active_points(mode, profile)
                self._lut_model = fn_build(mode, profile, cal_points)
                if not silent:
                    messagebox.showinfo("LUT", "Calibration LUT rebuilt.")
                return
            except Exception:
                pass

        # Fallback: older LUT APIs (best-effort)
        points = self._list_points(profile)
        for fn_name in ("rebuild", "update_profile", "refresh"):
            fn = getattr(self.lut, fn_name, None)
            if callable(fn):
                try:
                    fn(profile, points)
                    if not silent:
                        messagebox.showinfo("LUT", "Calibration LUT rebuilt.")
                    return
                except Exception:
                    continue

        if not silent:
            messagebox.showwarning("LUT", "LUT does not support rebuild/build methods.")

    # ---------------- Navigation ----------------
    def _navigate(self, to: str) -> None:
        # normalized routes used by app router
        if callable(self.nav_cb):
            self.nav_cb(to)
            return


    def _done(self) -> None:
        if callable(self.on_done):
            self.on_done()
        else:
            self._emit("ui.navigate", {"to": "engineer"})

    def _go_operator(self, to: str) -> None:
        #Use the callback if available
        if callable(self.nav_cb):
            self.nav_cb(to)
            return
        # Fallback
        self._emit("ui.navigate", {"to": "operator"})
