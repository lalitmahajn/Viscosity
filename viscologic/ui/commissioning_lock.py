from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, Any


class CommissioningLock(ttk.Frame):
    """
    One-time Commissioning Lock Screen.

    Requirement:
    - If commissioned == False: show password lock screen (only this screen).
    - If password correct: allow opening Commissioning Wizard.
    - If commissioned == True: caller should skip this screen.

    Notes:
    - This screen DOES NOT mark commissioned=True. That must happen at the end of commissioning_wizard.py
    - It only gates access to the wizard (first-run enable).
    """

    def __init__(
        self,
        parent: tk.Misc,
        commissioning_manager: Optional[Any] = None,
        on_unlocked: Optional[Callable[[], None]] = None,
        event_bus: Optional[Any] = None,
        title: str = "First Time Setup (Commissioning)",
    ) -> None:
        super().__init__(parent)

        self._cm = commissioning_manager
        self._event_bus = event_bus
        self._on_unlocked = on_unlocked

        self._tries = 0
        self._lockout_until = 0.0
        self._unlocked_this_session = False

        self._build_ui(title=title)
        self.refresh()

    # -------------------------
    # Public API
    # -------------------------

    def refresh(self) -> None:
        """
        Call whenever this screen is shown.
        If already commissioned, auto-bypass (safe).
        """
        if self._is_commissioned():
            self._status_var.set("Already commissioned. Redirecting...")
            #self.after(150, self._proceed_unlocked)
            return

        self._status_var.set("Enter commissioning password to continue.")
        self._pwd_var.set("")
        self._tries = 0
        self._lockout_until = 0.0
        self._unlocked_this_session = False
        self._update_lockout_ui()

        try:
            self._pwd_entry.focus_set()
        except Exception:
            pass

    def set_on_unlocked(self, cb: Optional[Callable[[], None]]) -> None:
        self._on_unlocked = cb

    # -------------------------
    # UI
    # -------------------------

    def _build_ui(self, title: str) -> None:
        self.columnconfigure(0, weight=1)

        wrap = ttk.Frame(self, padding=18)
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)

        self._title_lbl = ttk.Label(wrap, text=title, font=("Segoe UI", 16, "bold"))
        self._title_lbl.grid(row=0, column=0, sticky="w", pady=(0, 10))

        info = (
            "This device is not commissioned yet.\n"
            "Commissioning password is required only on a fresh device.\n\n"
            "Safety: During commissioning, Drive should remain OFF and PLC commands are ignored "
            "(until commissioning completes)."
        )
        self._info_lbl = ttk.Label(wrap, text=info, justify="left")
        self._info_lbl.grid(row=1, column=0, sticky="w", pady=(0, 14))

        form = ttk.Frame(wrap)
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Commissioning Password:").grid(row=0, column=0, sticky="w", padx=(0, 10))

        self._pwd_var = tk.StringVar(value="")
        self._pwd_entry = ttk.Entry(form, textvariable=self._pwd_var, show="•")
        self._pwd_entry.grid(row=0, column=1, sticky="ew")
        self._pwd_entry.bind("<Return>", lambda _e: self._handle_unlock())

        self._show_var = tk.BooleanVar(value=False)
        show_chk = ttk.Checkbutton(
            form,
            text="Show",
            variable=self._show_var,
            command=self._toggle_show,
        )
        show_chk.grid(row=0, column=2, sticky="w", padx=(10, 0))

        btns = ttk.Frame(wrap)
        btns.grid(row=3, column=0, sticky="w", pady=(14, 0))

        self._unlock_btn = ttk.Button(btns, text="Unlock", command=self._handle_unlock, style="Green.TButton")
        self._unlock_btn.grid(row=0, column=0, padx=(0, 10))

        self._clear_btn = ttk.Button(btns, text="Clear", command=self._clear, style="Blue.TButton")
        self._clear_btn.grid(row=0, column=1)

        self._status_var = tk.StringVar(value="")
        self._status_lbl = ttk.Label(wrap, textvariable=self._status_var, style="Card.TLabel")
        self._status_lbl.grid(row=4, column=0, sticky="w", pady=(16, 0))

        self._lockout_var = tk.StringVar(value="")
        self._lockout_lbl = ttk.Label(wrap, textvariable=self._lockout_var, foreground="#a00")
        self._lockout_lbl.grid(row=5, column=0, sticky="w", pady=(6, 0))

    def _toggle_show(self) -> None:
        self._pwd_entry.configure(show="" if self._show_var.get() else "•")

    def _clear(self) -> None:
        self._pwd_var.set("")
        self._status_var.set("Enter commissioning password to continue.")
        self._lockout_var.set("")
        try:
            self._pwd_entry.focus_set()
        except Exception:
            pass

    # -------------------------
    # Logic
    # -------------------------

    def _handle_unlock(self) -> None:
        now = time.time()
        if now < self._lockout_until:
            self._update_lockout_ui()
            return

        pwd = (self._pwd_var.get() or "").strip()
        if not pwd:
            self._status_var.set("Password required.")
            return

        ok = self._verify_commissioning_password(pwd)
        if ok:
            self._status_var.set("Unlocked. Opening setup wizard...")
            self._lockout_var.set("")
            self._unlocked_this_session = True

            # Optional publish (if your app listens)
            self._publish_event("ui.commissioning.unlocked", {"ts": int(now * 1000)})

            self.after(150, self._proceed_unlocked)
            return

        # Wrong password
        self._tries += 1
        self._status_var.set("Wrong password. Try again.")

        # Simple lockout policy: after 5 wrong tries, 30 sec lockout
        if self._tries >= 5:
            self._lockout_until = time.time() + 30.0
            self._lockout_var.set("Too many attempts. Locked for 30 seconds.")
            self._update_lockout_ui()
        else:
            left = max(0, 5 - self._tries)
            self._lockout_var.set(f"Attempts left: {left}")

    def _proceed_unlocked(self) -> None:
        """
        Continue to commissioning wizard (caller decides navigation).
        """
        if callable(self._on_unlocked):
            try:
                self._on_unlocked()
                return
            except Exception:
                # If callback fails, still publish an event as fallback
                pass

        self._publish_event("ui.navigate", {"to": "commissioning_wizard"})

    # -------------------------
    # Commissioning manager integration (duck-typed)
    # -------------------------

    def _is_commissioned(self) -> bool:
        cm = self._cm
        if cm is None:
            return False

        for name in ("is_commissioned", "get_commissioned", "commissioned"):
            if hasattr(cm, name):
                try:
                    attr = getattr(cm, name)
                    return bool(attr() if callable(attr) else attr)
                except Exception:
                    return False
        return False

    def _verify_commissioning_password(self, password: str) -> bool:
        cm = self._cm
        if cm is None:
            return False

        candidates = (
            "verify_commissioning_password",
            "verify_password",
            "check_commissioning_password",
            "check_password",
            "verify",
            "authenticate",
        )
        for fn_name in candidates:
            if hasattr(cm, fn_name):
                try:
                    fn = getattr(cm, fn_name)
                    if callable(fn):
                        return bool(fn(password))
                except Exception:
                    return False

        return False

    # -------------------------
    # Event bus (optional)
    # -------------------------

    def _publish_event(self, topic: str, payload: dict) -> None:
        eb = self._event_bus
        if eb is None:
            return

        # Duck-type publish APIs
        for fn_name in ("publish", "emit", "put", "post"):
            if hasattr(eb, fn_name):
                try:
                    fn = getattr(eb, fn_name)
                    if callable(fn):
                        fn(topic, payload)
                        return
                except Exception:
                    return

    def _update_lockout_ui(self) -> None:
        now = time.time()
        if now < self._lockout_until:
            self._unlock_btn.state(["disabled"])
            self._clear_btn.state(["!disabled"])
            remaining = int(self._lockout_until - now)
            self._lockout_var.set(f"Locked. Try again in {remaining}s.")
            self.after(250, self._update_lockout_ui)
        else:
            self._unlock_btn.state(["!disabled"])
            # keep lockout text if we want, otherwise clear:
            if "Locked." in (self._lockout_var.get() or ""):
                self._lockout_var.set("")
