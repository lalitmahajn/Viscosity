# viscologic/security/auth_engineer.py
# Engineer password authentication with secure PBKDF2 hashing

from __future__ import annotations

import time
import secrets
import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

from viscologic.storage.sqlite_store import SqliteStore

META_KEY_HASH = "engineer_password_hash"
META_KEY_HINT = "engineer_password_hint"
META_KEY_INIT = "engineer_password_inited"

PBKDF2_ITERATIONS_DEFAULT = 200_000

@dataclass
class AuthResult:
    ok: bool
    reason: str = ""
    session_token: Optional[str] = None

def now_ms() -> int:
    return int(time.time() * 1000)


def _pbkdf2_hash(password: str, *, iterations: int, salt: bytes) -> str:
    """Hash password using PBKDF2-SHA256."""
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def _pbkdf2_verify(password: str, stored: str) -> bool:
    """Verify password against PBKDF2 hash."""
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


def _is_hashed(stored: str) -> bool:
    """Check if stored value is a PBKDF2 hash (vs plain text)."""
    return stored.startswith("pbkdf2_sha256$")

class EngineerAuth:
    def __init__(self, store: SqliteStore, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.store = store
        self.config = config
        self.logger = logger or logging.getLogger("viscologic.auth")
        self.session_timeout_sec = 300 
        self._active_session: Optional[str] = None
        self._session_expiry_ms = 0
        
        # Hashing parameters
        sec_cfg = (config or {}).get("security", {}) or {}
        self.iterations = int(sec_cfg.get("pbkdf2_iterations", PBKDF2_ITERATIONS_DEFAULT))
        
        # Default password from config or fallback
        self.default_password = str(sec_cfg.get("engineer_password", "admin")).strip()

    def ensure_password_initialized(self) -> None:
        """Initialize password hash if not exists. Uses config password or default 'admin'."""
        inited = self.store.get_meta(META_KEY_INIT, default="0")
        existing_hash = self.store.get_meta(META_KEY_HASH, default=None)

        if inited == "1" and existing_hash:
            # If already initialized, check if it needs migration from plain text to hash
            if not _is_hashed(existing_hash):
                # Migrate plain text to hash
                self.logger.warning("Migrating engineer password from plain text to hash")
                salt = secrets.token_bytes(16)
                pw_hash = _pbkdf2_hash(existing_hash, iterations=self.iterations, salt=salt)
                self.store.set_meta(META_KEY_HASH, pw_hash)
            return

        # Initialize with hashed default password
        pw = self.default_password
        salt = secrets.token_bytes(16)
        pw_hash = _pbkdf2_hash(pw, iterations=self.iterations, salt=salt)
        
        self.store.set_meta(META_KEY_HASH, pw_hash)
        self.store.set_meta(META_KEY_INIT, "1")
        
        self.logger.info("Engineer password hash initialized (default password: %s)", pw)

    def login(self, password: str) -> AuthResult:
        """Verify password against stored hash. Supports migration from plain text."""
        stored = self.store.get_meta(META_KEY_HASH)
        
        if not stored:
            return AuthResult(ok=False, reason="Password not initialized")

        # Check if stored value is hashed or plain text (for migration)
        if _is_hashed(stored):
            # Verify against PBKDF2 hash
            if _pbkdf2_verify(password, stored):
                token = secrets.token_hex(8)
                self._active_session = token
                self._session_expiry_ms = now_ms() + (self.session_timeout_sec * 1000)
                return AuthResult(ok=True, session_token=token)
            else:
                return AuthResult(ok=False, reason="Password mismatch")
        else:
            # Legacy: plain text password (migrate on successful login)
            if password == stored:
                # Migrate to hash on successful login
                self.logger.info("Migrating engineer password from plain text to hash")
                salt = secrets.token_bytes(16)
                pw_hash = _pbkdf2_hash(password, iterations=self.iterations, salt=salt)
                self.store.set_meta(META_KEY_HASH, pw_hash)
                
                token = secrets.token_hex(8)
                self._active_session = token
                self._session_expiry_ms = now_ms() + (self.session_timeout_sec * 1000)
                return AuthResult(ok=True, session_token=token)
            else:
                return AuthResult(ok=False, reason="Password mismatch")

    def logout(self) -> None:
        self._active_session = None

    def is_session_valid(self, token: Optional[str]) -> bool:
        if not token or token != self._active_session: return False
        if now_ms() > self._session_expiry_ms: return False
        return True

    def refresh_session(self, token: Optional[str]) -> bool:
        if self.is_session_valid(token):
            self._session_expiry_ms = now_ms() + (self.session_timeout_sec * 1000)
            return True
        return False

    def change_password(self, session_token: str, new_password: str, hint: str = "") -> AuthResult:
        """Change password. Requires valid session token. New password is hashed."""
        if not self.is_session_valid(session_token):
            return AuthResult(ok=False, reason="Invalid or expired session")
        
        new_pw = new_password.strip()
        if not new_pw or len(new_pw) < 4:
            return AuthResult(ok=False, reason="Password too short (minimum 4 characters)")
        
        # Hash the new password
        salt = secrets.token_bytes(16)
        pw_hash = _pbkdf2_hash(new_pw, iterations=self.iterations, salt=salt)
        
        self.store.set_meta(META_KEY_HASH, pw_hash)
        
        if hint:
            self.store.set_meta(META_KEY_HINT, hint)
        
        self.logger.info("Engineer password changed successfully")
        return AuthResult(ok=True)