# viscologic/ui/commissioning_wizard.py
# One-time Commissioning Wizard (Tkinter)
# - Select Mode (Tabletop/Inline)
# - Select Control Source (Local/Remote/Mixed)
# - Remote enable + comm-loss action
# - Safety limits view (and optional edit)
# - Complete setup -> mark commissioned=true (via commissioning_manager)

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, Optional, Callable


def now_ms() -> int:
    return int(time.time() * 1000)


class CommissioningWizard(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        config_manager: Optional[Any] = None,
        commissioning_manager: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        navigate_callback: Optional[Any] = None,
        on_completed: Optional[Callable[[], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        title: str = "Commissioning Wizard (One-time)",
    ) -> None:
        super().__init__(parent)

        self._cfg = config_manager
        self._cm = commissioning_manager
        self._bus = event_bus
        self._navigate = navigate_callback
        self._on_completed = on_completed
        self._on_cancel = on_cancel

        self._step_idx = 0
        self._steps = ["Mode & Control", "PLC / Remote", "Safety", "Finish"]
        self._cmd_seq = 0

        # Force safe stop while commissioning UI is open
        self._publish_cmd("STOP")

        # UI vars
        self.var_mode = tk.StringVar(value="tabletop")          # tabletop / inline
        self.var_control = tk.StringVar(value="local")          # local / remote / mixed
        self.var_remote_enable = tk.BooleanVar(value=True)
        self.var_comm_loss = tk.StringVar(value="safe_stop")    # safe_stop / hold_last / pause
        self.var_inline_auto_resume = tk.BooleanVar(value=True)

        # safety (view + optional edit)
        self.var_max_current_ma = tk.StringVar(value="150")
        self.var_max_temp_c = tk.StringVar(value="80")
        self.var_allow_safety_edit = tk.BooleanVar(value=False)

        self.var_status = tk.StringVar(value="")

        self._build_ui(title)
        self._load_existing_defaults()
        self._render_step()

    # -----------------------------
    # UI
    # -----------------------------

    def _build_ui(self, title: str) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style="Header.TFrame", padding=15)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text=title, style="HeaderTitle.TLabel").grid(row=0, column=0, sticky="w")

        self.lbl_status = ttk.Label(header, textvariable=self.var_status, style="Header.TLabel")
        self.lbl_status.grid(row=1, column=0, sticky="w", pady=(10, 0))

        # Left steps list
        left = ttk.Frame(self, padding=(14, 0, 10, 14))
        left.grid(row=1, column=0, sticky="nsw")
        ttk.Label(left, text="Steps", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.step_list = tk.Listbox(left, height=len(self._steps), width=22)
        self.step_list.grid(row=1, column=0, sticky="nsw")
        self.step_list.bind("<<ListboxSelect>>", self._on_step_click)

        # Right content
        self.content = ttk.Frame(self, padding=(10, 0, 14, 14))
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        # Footer buttons
        footer = ttk.Frame(self, padding=(14, 10, 14, 14))
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        footer.columnconfigure(0, weight=1)

        self.btn_back = ttk.Button(footer, text="Back", command=self._back, style="Blue.TButton")
        self.btn_back.grid(row=0, column=1, padx=(0, 8), sticky="e")

        self.btn_next = ttk.Button(footer, text="Next", command=self._next, style="Green.TButton")
        self.btn_next.grid(row=0, column=2, padx=(0, 8), sticky="e")

        self.btn_finish = ttk.Button(footer, text="Complete Setup", command=self._finish, style="Green.TButton")
        self.btn_finish.grid(row=0, column=3, sticky="e")

        self.btn_cancel = ttk.Button(footer, text="Cancel", command=self._cancel, style="Red.TButton")
        self.btn_cancel.grid(row=0, column=4, sticky="e", padx=(8, 0))

        footer.grid_columnconfigure(0, weight=1)

        # Populate steps list
        self.step_list.delete(0, tk.END)
        for s in self._steps:
            self.step_list.insert(tk.END, s)

    def _clear_content(self) -> None:
        for w in self.content.winfo_children():
            w.destroy()

    def _render_step(self) -> None:
        self._clear_content()
        self._select_step(self._step_idx)

        if self._step_idx == 0:
            self._ui_step_mode_control()
        elif self._step_idx == 1:
            self._ui_step_remote()
        elif self._step_idx == 2:
            self._ui_step_safety()
        else:
            self._ui_step_finish()

        # Button states
        self.btn_back.state(["disabled"] if self._step_idx == 0 else ["!disabled"])
        self.btn_next.state(["disabled"] if self._step_idx >= len(self._steps) - 1 else ["!disabled"])
        self.btn_finish.state(["!disabled"] if self._step_idx == len(self._steps) - 1 else ["disabled"])

        self.var_status.set("Drive is kept OFF during commissioning (safety).")

    def _select_step(self, idx: int) -> None:
        try:
            self.step_list.selection_clear(0, tk.END)
            self.step_list.selection_set(idx)
            self.step_list.activate(idx)
        except Exception:
            pass

    def _on_step_click(self, _e: Any) -> None:
        try:
            sel = self.step_list.curselection()
            if not sel:
                return
            idx = int(sel[0])
            # Allow only backward navigation without finishing current validations
            if idx <= self._step_idx:
                self._step_idx = idx
                self._render_step()
        except Exception:
            return

    # -----------------------------
    # Step UIs
    # -----------------------------

    def _ui_step_mode_control(self) -> None:
        box = ttk.Frame(self.content, style="Card.TFrame", padding=15)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)

        ttk.Label(box, text="1) Select Operating Mode", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        mode_frame = ttk.Frame(box)
        mode_frame.grid(row=1, column=0, sticky="w", pady=(10, 0))

        ttk.Radiobutton(mode_frame, text="Tabletop (Manual Start/Stop)", value="tabletop", variable=self.var_mode).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Radiobutton(mode_frame, text="Inline (24x7 Continuous)", value="inline", variable=self.var_mode).grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )

        ttk.Separator(box).grid(row=2, column=0, sticky="ew", pady=14)

        ttk.Label(box, text="2) Select Control Source", font=("Segoe UI", 12, "bold")).grid(
            row=3, column=0, sticky="w"
        )

        ctrl_frame = ttk.Frame(box)
        ctrl_frame.grid(row=4, column=0, sticky="w", pady=(10, 0))

        ttk.Radiobutton(ctrl_frame, text="Local (only UI)", value="local", variable=self.var_control).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Radiobutton(ctrl_frame, text="Remote (only PLC)", value="remote", variable=self.var_control).grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Radiobutton(ctrl_frame, text="Mixed (UI + PLC)", value="mixed", variable=self.var_control).grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )

        note = (
            "Rule: STOP is always allowed from both sides.\n"
            "If Control=Remote, UI Start/Enable is disabled (safe)."
        )
        ttk.Label(box, text=note, style="CardSecondary.TLabel").grid(row=5, column=0, sticky="w", pady=(14, 0))

    def _ui_step_remote(self) -> None:
        box = ttk.Frame(self.content, style="Card.TFrame", padding=15)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)

        ttk.Label(box, text="3) PLC / Remote Integration", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        ttk.Checkbutton(box, text="Enable PLC Remote Commands", variable=self.var_remote_enable).grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )

        ttk.Label(box, text="On PLC communication loss, do:", font=("Segoe UI", 10, "bold")).grid(
            row=2, column=0, sticky="w", pady=(12, 0)
        )

        comm_frame = ttk.Frame(box)
        comm_frame.grid(row=3, column=0, sticky="w", pady=(8, 0))

        ttk.Radiobutton(comm_frame, text="Safe Stop (Drive OFF + Alarm)", value="safe_stop",
                        variable=self.var_comm_loss).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(comm_frame, text="Hold Last (keep running but show warning)", value="hold_last",
                        variable=self.var_comm_loss).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Radiobutton(comm_frame, text="Pause (Drive OFF, no latch)", value="pause",
                        variable=self.var_comm_loss).grid(row=2, column=0, sticky="w", pady=(6, 0))

        ttk.Separator(box).grid(row=4, column=0, sticky="ew", pady=14)

        ttk.Label(box, text="Inline Auto-Resume (after power fail)", font=("Segoe UI", 10, "bold")).grid(
            row=5, column=0, sticky="w"
        )
        ttk.Checkbutton(
            box,
            text="Enable auto-resume in Inline mode after self-check OK",
            variable=self.var_inline_auto_resume,
        ).grid(row=6, column=0, sticky="w", pady=(8, 0))

        hint = (
            "Tabletop: software auto-opens, but measurement starts only when Start pressed.\n"
            "Inline: if Auto-Resume enabled, it can auto-run after reboot (safe checks first)."
        )
        ttk.Label(box, text=hint, style="CardSecondary.TLabel").grid(row=7, column=0, sticky="w", pady=(14, 0))

    def _ui_step_safety(self) -> None:
        box = ttk.Frame(self.content, style="Card.TFrame", padding=15)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="4) Safety Limits (View)", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )

        ttk.Checkbutton(
            box,
            text="Allow editing safety limits (engineer only)",
            variable=self.var_allow_safety_edit,
            command=self._toggle_safety_edit,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        ttk.Label(box, text="Max Drive Current (mA):").grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.ent_i = ttk.Entry(box, textvariable=self.var_max_current_ma, width=12)
        self.ent_i.grid(row=2, column=1, sticky="w", pady=(12, 0))

        ttk.Label(box, text="Max Temperature (°C):").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.ent_t = ttk.Entry(box, textvariable=self.var_max_temp_c, width=12)
        self.ent_t.grid(row=3, column=1, sticky="w", pady=(8, 0))

        rule = (
            "Safety rules:\n"
            "- Over-current / Over-temp / Critical fault -> Drive OFF + Alarm + Latch\n"
            "- ADC saturation -> auto warning (and PGA auto adjust if enabled)\n"
            "- STOP command always overrides START (local or PLC)\n"
        )
        ttk.Label(box, text=rule, style="CardSecondary.TLabel", justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(14, 0)
        )

        self._toggle_safety_edit()

    def _ui_step_finish(self) -> None:
        box = ttk.Frame(self.content, style="Card.TFrame", padding=15)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)

        ttk.Label(box, text="5) Confirm & Complete", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        summary = self._summary_text()
        self.txt = tk.Text(box, height=14, wrap="word")
        self.txt.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.txt.insert("1.0", summary)
        self.txt.configure(state="disabled")

        note = (
            "After you click 'Complete Setup':\n"
            "- commissioned=true will be saved\n"
            "- commissioning password will never be asked again on boot\n"
            "- you can still protect Engineer settings with Engineer password\n"
        )
        ttk.Label(box, text=note, foreground="#333").grid(row=2, column=0, sticky="w", pady=(12, 0))

    # -----------------------------
    # Navigation
    # -----------------------------

    def _next(self) -> None:
        if not self._validate_step(self._step_idx):
            return
        self._step_idx = min(self._step_idx + 1, len(self._steps) - 1)
        self._render_step()

    def _back(self) -> None:
        self._step_idx = max(self._step_idx - 1, 0)
        self._render_step()

    def _cancel(self) -> None:
        if messagebox.askyesno("Cancel", "Cancel commissioning wizard? (No changes will be marked commissioned)"):
            if callable(self._on_cancel):
                self._on_cancel()
            else:
                self._publish_event("ui.navigate", {"to": "operator"})

    # -----------------------------
    # Finish
    # -----------------------------

    def _finish(self) -> None:
        if not self._validate_step(self._step_idx):
            return

        if not messagebox.askyesno("Complete Setup", "Save settings and mark device as commissioned?"):
            return

        try:
            self._apply_settings()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply settings:\n{e}")
            return

        ok = self._mark_commissioned()
        if not ok:
            messagebox.showwarning(
                "Warning",
                "Settings saved, but commissioned flag could not be set.\n"
                "Device may ask commissioning password again on next boot.",
            )
        else:
            messagebox.showinfo("Done", "Commissioning completed successfully.")

        self._publish_event("commissioning.completed", {"ts_ms": now_ms()})

        if callable(self._on_completed):
            self._on_completed()
        else:
            self._publish_event("ui.navigate", {"to": "operator"})

    # -----------------------------
    # Validation / Summary
    # -----------------------------

    def _validate_step(self, idx: int) -> bool:
        mode = (self.var_mode.get() or "").strip().lower()
        ctrl = (self.var_control.get() or "").strip().lower()

        if idx == 0:
            if mode not in ("tabletop", "inline"):
                messagebox.showerror("Validation", "Select a valid Mode.")
                return False
            if ctrl not in ("local", "remote", "mixed"):
                messagebox.showerror("Validation", "Select a valid Control Source.")
                return False

        if idx == 2:
            # safety numbers
            try:
                i_ma = float(self.var_max_current_ma.get().strip())
                t_c = float(self.var_max_temp_c.get().strip())
            except Exception:
                messagebox.showerror("Validation", "Safety limits must be numeric.")
                return False

            if i_ma <= 0 or i_ma > 500:
                messagebox.showerror("Validation", "Max current must be within 1..500 mA (safe range).")
                return False
            if t_c <= 0 or t_c > 200:
                messagebox.showerror("Validation", "Max temp must be within 1..200 °C (safe range).")
                return False

        return True

    def _summary_text(self) -> str:
        return (
            f"Mode: {self.var_mode.get()}\n"
            f"Control Source: {self.var_control.get()}\n"
            f"PLC Remote Enabled: {self.var_remote_enable.get()}\n"
            f"Comm-loss Action: {self.var_comm_loss.get()}\n"
            f"Inline Auto-Resume: {self.var_inline_auto_resume.get()}\n"
            f"Max Current (mA): {self.var_max_current_ma.get()}\n"
            f"Max Temp (°C): {self.var_max_temp_c.get()}\n"
        )

    def _toggle_safety_edit(self) -> None:
        editable = bool(self.var_allow_safety_edit.get())
        st = "!disabled" if editable else "disabled"
        try:
            self.ent_i.state([st])
            self.ent_t.state([st])
        except Exception:
            pass

    # -----------------------------
    # Config load / apply (duck-typed)
    # -----------------------------

    def _load_existing_defaults(self) -> None:
        # Try pulling from config_manager if available
        mode = self._cfg_get(["app.mode", "mode"], default=None)
        ctrl = self._cfg_get(["app.control_source", "control_source"], default=None)
        remote_en = self._cfg_get(["protocols.remote_enable", "remote_enable"], default=None)
        comm_loss = self._cfg_get(["protocols.comm_loss_action", "comm_loss_action"], default=None)
        auto_resume = self._cfg_get(["app.inline_auto_resume", "inline_auto_resume"], default=None)
        max_i = self._cfg_get(["safety.max_current_ma", "max_current_ma"], default=None)
        max_t = self._cfg_get(["safety.max_temp_c", "max_temp_c"], default=None)

        if isinstance(mode, str) and mode.lower() in ("tabletop", "inline"):
            self.var_mode.set(mode.lower())
        if isinstance(ctrl, str) and ctrl.lower() in ("local", "remote", "mixed"):
            self.var_control.set(ctrl.lower())
        if isinstance(remote_en, bool):
            self.var_remote_enable.set(remote_en)
        if isinstance(comm_loss, str) and comm_loss.lower() in ("safe_stop", "hold_last", "pause"):
            self.var_comm_loss.set(comm_loss.lower())
        if isinstance(auto_resume, bool):
            self.var_inline_auto_resume.set(auto_resume)

        if isinstance(max_i, (int, float)):
            self.var_max_current_ma.set(str(int(max_i)))
        if isinstance(max_t, (int, float)):
            self.var_max_temp_c.set(str(int(max_t)))

    def _apply_settings(self) -> None:
        # Build a compact settings dict
        settings = {
            "app": {
                "mode": self.var_mode.get().lower(),
                "control_source": self.var_control.get().lower(),
                "inline_auto_resume": bool(self.var_inline_auto_resume.get()),
            },
            "protocols": {
                "remote_enable": bool(self.var_remote_enable.get()),
                "comm_loss_action": self.var_comm_loss.get().lower(),
            },
            "safety": {
                "max_current_ma": float(self.var_max_current_ma.get().strip()),
                "max_temp_c": float(self.var_max_temp_c.get().strip()),
            },
        }

        # Apply via config_manager (duck-typed)
        cfg = self._cfg
        if cfg is None:
            # publish event fallback
            self._publish_event("config.update", {"settings": settings, "ts_ms": now_ms()})
            return

        # Prefer bulk update methods
        for fn_name in ("update_settings", "merge", "update", "set_many", "apply"):
            fn = getattr(cfg, fn_name, None)
            if callable(fn):
                try:
                    fn(settings)
                    self._save_cfg_if_supported()
                    return
                except Exception:
                    pass

        # Fallback: set key-by-key with dotted paths
        self._cfg_set("app.mode", settings["app"]["mode"])
        self._cfg_set("app.control_source", settings["app"]["control_source"])
        self._cfg_set("app.inline_auto_resume", settings["app"]["inline_auto_resume"])

        self._cfg_set("protocols.remote_enable", settings["protocols"]["remote_enable"])
        self._cfg_set("protocols.comm_loss_action", settings["protocols"]["comm_loss_action"])

        self._cfg_set("safety.max_current_ma", settings["safety"]["max_current_ma"])
        self._cfg_set("safety.max_temp_c", settings["safety"]["max_temp_c"])

        self._save_cfg_if_supported()

        # Also publish for live modules
        self._publish_event("settings.updated", {"settings": settings, "ts_ms": now_ms()})

    def _save_cfg_if_supported(self) -> None:
        cfg = self._cfg
        if cfg is None:
            return
        for fn_name in ("save", "persist", "flush", "write"):
            fn = getattr(cfg, fn_name, None)
            if callable(fn):
                try:
                    fn()
                    return
                except Exception:
                    return

    def _cfg_get(self, keys: list, default: Any = None) -> Any:
        cfg = self._cfg
        if cfg is None:
            return default

        # If config_manager supports get(key)
        get_fn = getattr(cfg, "get", None)
        if callable(get_fn):
            for k in keys:
                try:
                    v = get_fn(k)
                    if v is not None:
                        return v
                except Exception:
                    continue

        # Try dict-like
        for k in keys:
            try:
                if isinstance(cfg, dict) and k in cfg:
                    return cfg[k]
            except Exception:
                pass

        return default

    def _cfg_set(self, key: str, value: Any) -> None:
        cfg = self._cfg
        if cfg is None:
            return

        for fn_name in ("set", "set_value", "put", "set_setting"):
            fn = getattr(cfg, fn_name, None)
            if callable(fn):
                try:
                    fn(key, value)
                    return
                except Exception:
                    continue

        # publish fallback
        self._publish_event("config.set", {"key": key, "value": value, "ts_ms": now_ms()})

    # -----------------------------
    # Commissioning flag
    # -----------------------------

    def _mark_commissioned(self) -> bool:
        cm = self._cm
        if cm is None:
            return False

        for fn_name in ("mark_commissioned", "set_commissioned", "complete_commissioning", "commission"):
            fn = getattr(cm, fn_name, None)
            if callable(fn):
                try:
                    out = fn(True) if fn_name == "set_commissioned" else fn()
                    # if function returns bool, honor it; otherwise assume ok
                    if isinstance(out, bool):
                        return out
                    return True
                except Exception:
                    return False

        # as a last fallback, if it has attribute
        try:
            if hasattr(cm, "commissioned"):
                setattr(cm, "commissioned", True)
                return True
        except Exception:
            pass
        return False

    # -----------------------------
    # Event bus helpers
    # -----------------------------

    def _publish_event(self, topic: str, payload: Dict[str, Any]) -> None:
        bus = self._bus
        if bus is None:
            return
        for fn_name in ("publish", "emit", "post", "put"):
            fn = getattr(bus, fn_name, None)
            if callable(fn):
                try:
                    fn(topic, payload)
                    return
                except Exception:
                    return

    def _publish_cmd(self, cmd: str) -> None:
        self._cmd_seq += 1
        self._publish_event(
            "ui.command",
            {"cmd": str(cmd).upper(), "source": "local", "seq": self._cmd_seq, "ts_ms": now_ms()},
        )
