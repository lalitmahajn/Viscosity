# viscologic/security/commissioning_manager.py
# One-time commissioning password manager (new machine only)
# Stores password hash in SQLite meta table, and commissioning flag in device_state.

from __future__ import annotations

import os
import secrets
import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

from viscologic.storage.sqlite_store import SqliteStore


PBKDF2_ITERATIONS_DEFAULT = 200_000
META_KEY_HASH = "commissioning_password_hash"
META_KEY_HINT = "commissioning_password_hint"   # optional, not secret
META_KEY_INIT = "commissioning_password_inited" # "1" when set


@dataclass
class VerifyResult:
    ok: bool
    reason: str = ""


def _pbkdf2_hash(password: str, *, iterations: int, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def _pbkdf2_verify(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_hex, dk_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


class CommissioningManager:
    """
    Commissioning rules:
      - If device_state.commissioned == 0 => commissioning required
      - Commissioning password hash stored in meta[commissioning_password_hash]
      - After successful commissioning wizard completion => mark_commissioned()

    Password sources (first match wins):
      1) env VISC_COMMISSION_PW
      2) config['security']['commissioning_password']  (plain, used only for hashing init)
      3) fallback default "1234" (WARNING logged) OR auto-generated (if enabled)
    """

    def __init__(
        self,
        store: SqliteStore,
        config: Dict[str, Any],
        logger: Optional[logging.Logger] = None,
    ):
        self.store = store
        self.config = config
        self.logger = logger or logging.getLogger("viscologic.commissioning")

        sec_cfg = (config or {}).get("security", {}) or {}
        self.required_on_first_run = bool(sec_cfg.get("commissioning_required_on_first_run", True))

        # Hashing params
        self.iterations = int(sec_cfg.get("pbkdf2_iterations", PBKDF2_ITERATIONS_DEFAULT))

        # Behavior: generate random password if nothing provided
        self.auto_generate_if_missing = bool(sec_cfg.get("auto_generate_commissioning_password", False))

        # Optional hint (non-secret)
        self.password_hint = str(sec_cfg.get("commissioning_password_hint", "")).strip()

        # Optional plain password in config (only used if no hash exists yet)
        self.config_plain_pw = sec_cfg.get("commissioning_password", None)

    # -------------------------
    # State queries
    # -------------------------

    def is_commissioned(self) -> bool:
        return self.store.is_commissioned()

    def needs_commissioning(self) -> bool:
        if not self.required_on_first_run:
            return False
        return not self.is_commissioned()

    # -------------------------
    # Password hash init
    # -------------------------

    def ensure_password_initialized(self) -> None:
        """
        Ensures a commissioning password hash exists in meta.
        If missing, creates it using:
          env VISC_COMMISSION_PW > config password > generated/default
        """
        inited = self.store.get_meta(META_KEY_INIT, default="0")
        existing_hash = self.store.get_meta(META_KEY_HASH, default=None)

        if inited == "1" and existing_hash:
            return

        pw = self._get_initial_plain_password()
        salt = secrets.token_bytes(16)
        pw_hash = _pbkdf2_hash(pw, iterations=self.iterations, salt=salt)

        self.store.set_meta(META_KEY_HASH, pw_hash)
        self.store.set_meta(META_KEY_INIT, "1")

        if self.password_hint:
            self.store.set_meta(META_KEY_HINT, self.password_hint)

        # Log message (do not print password unless it was auto-generated and user requested)
        if self.auto_generate_if_missing and self._is_generated_password(pw):
            self.logger.warning(
                "Commissioning password auto-generated. SAVE IT NOW: %s (You can change later via engineer settings).",
                pw,
            )
        else:
            # do not log the password
            self.logger.info("Commissioning password hash initialized (password not printed).")

    def _get_initial_plain_password(self) -> str:
        env_pw = os.environ.get("VISC_COMMISSION_PW", "").strip()
        if env_pw:
            return env_pw

        cfg_pw = (self.config_plain_pw or "")
        if isinstance(cfg_pw, str) and cfg_pw.strip():
            return cfg_pw.strip()

        if self.auto_generate_if_missing:
            # mark so we can detect and log it once
            pw = "AUTO-" + secrets.token_urlsafe(8)
            return pw

        # Safe fallback (user can change later)
        self.logger.warning(
            "No commissioning password provided (env/config). Using DEFAULT '1234'. "
            "Recommended: set VISC_COMMISSION_PW or config.security.commissioning_password."
        )
        return "1234"

    def _is_generated_password(self, pw: str) -> bool:
        return pw.startswith("AUTO-")

    # -------------------------
    # Verification
    # -------------------------

    def get_password_hint(self) -> str:
        return self.store.get_meta(META_KEY_HINT, default="") or ""

    def verify_commissioning_password(self, password: str) -> VerifyResult:
        """
        Returns VerifyResult(ok=True) if password matches stored hash.
        """
        if not self.required_on_first_run:
            return VerifyResult(ok=True, reason="Commissioning not required by config.")

        if not password or not password.strip():
            return VerifyResult(ok=False, reason="Password empty.")

        # Ensure hash exists
        self.ensure_password_initialized()

        stored_hash = self.store.get_meta(META_KEY_HASH, default=None)
        if not stored_hash:
            return VerifyResult(ok=False, reason="Password hash missing (DB meta).")

        ok = _pbkdf2_verify(password.strip(), stored_hash)
        return VerifyResult(ok=ok, reason="" if ok else "Wrong password.")

    # -------------------------
    # Complete / Reset
    # -------------------------

    def mark_commissioned(self) -> None:
        """
        Call after commissioning wizard completes successfully.
        """
        self.store.mark_commissioned()
        try:
            self.store.log_event("COMMISSIONED", {"ts": "ok"})
        except Exception:
            pass
        self.logger.info("Device marked as commissioned.")

    def reset_commissioning(self) -> None:
        """
        Engineer-only action should call this.
        After this, next boot will require commissioning password again.
        """
        self.store.reset_commissioning()
        try:
            self.store.log_event("COMMISSION_RESET", {"ts": "ok"})
        except Exception:
            pass
        self.logger.warning("Commissioning reset. Next boot will require commissioning lock again.")

    def change_commissioning_password(self, new_password: str, hint: str = "") -> VerifyResult:
        """
        Engineer-only method: overwrites commissioning password hash.
        This does NOT change commissioned flag. (Only lock password changes.)
        """
        if not new_password or len(new_password.strip()) < 4:
            return VerifyResult(ok=False, reason="Password too short (min 4).")

        salt = secrets.token_bytes(16)
        pw_hash = _pbkdf2_hash(new_password.strip(), iterations=self.iterations, salt=salt)

        self.store.set_meta(META_KEY_HASH, pw_hash)
        self.store.set_meta(META_KEY_INIT, "1")
        if hint is not None:
            self.store.set_meta(META_KEY_HINT, str(hint).strip())

        try:
            self.store.log_event("COMMISSION_PW_CHANGED", {"hint_set": bool(hint)})
        except Exception:
            pass

        self.logger.info("Commissioning password updated (hash stored).")
        return VerifyResult(ok=True, reason="Updated")
    
    def ensure_commissioned(self) -> None:
        """
        Called by application startup (Orchestrator).
        1. Ensures password hash is initialized (so UI can unlock).
        2. Checks if device is strictly commissioned.
        3. Raises exception if not commissioned (caught by Orchestrator).
        """
        # Always ensure we have a password hash ready for the UI to use
        self.ensure_password_initialized()

        if not self.is_commissioned():
            self.logger.info("Startup check: Device is NOT commissioned. Waiting for UI lock.")
            raise RuntimeError("Device not commissioned")
