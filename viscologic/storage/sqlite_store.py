# viscologic/storage/sqlite_store.py
# SQLite persistence layer for ViscoLogic
# Stores:
#   - device_state (commissioned flag, last selections)
#   - settings (key/value)
#   - calibration_profiles
#   - calibration_points
#   - events

from __future__ import annotations

import os
import json
import time
import sqlite3
import threading
import logging
from typing import Any, Dict, List, Optional, Tuple


def now_ms() -> int:
    return int(time.time() * 1000)


class SqliteStore:
    def __init__(self, db_path: str, logger: Optional[logging.Logger] = None):
        self.db_path = db_path
        self.logger = logger or logging.getLogger("viscologic.sqlite")
        self._lock = threading.RLock()
        
        # Internal state to support separate last_row_id() calls
        self._last_insert_id = 0

        # Ensure parent directory exists
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    # -----------------------------
    # Internal helpers
    # -----------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # Basic pragmas for reliability/performance
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_db(self) -> None:
        """Create tables if not exists."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );

                    CREATE TABLE IF NOT EXISTS device_state (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        commissioned INTEGER NOT NULL DEFAULT 0,
                        commissioned_at_ms INTEGER,
                        last_mode TEXT,
                        last_control_source TEXT,
                        remote_enable INTEGER DEFAULT 0,
                        last_profile_id INTEGER,
                        updated_at_ms INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at_ms INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS calibration_profiles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        created_at_ms INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS calibration_points (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        profile_id INTEGER NOT NULL,
                        known_cp REAL NOT NULL,
                        feature_json TEXT NOT NULL,
                        temp_c REAL,
                        created_at_ms INTEGER NOT NULL,
                        FOREIGN KEY(profile_id) REFERENCES calibration_profiles(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts_ms INTEGER NOT NULL,
                        type TEXT NOT NULL,
                        details_json TEXT
                    );
                    """
                )

                # Ensure single row device_state exists
                row = conn.execute("SELECT id FROM device_state WHERE id=1;").fetchone()
                if row is None:
                    conn.execute(
                        """
                        INSERT INTO device_state (id, commissioned, commissioned_at_ms, last_mode, last_control_source,
                                                 remote_enable, last_profile_id, updated_at_ms)
                        VALUES (1, 0, NULL, NULL, NULL, 0, NULL, ?);
                        """,
                        (now_ms(),),
                    )

                self.logger.info("SQLite DB initialized: %s", self.db_path)
            finally:
                conn.close()

    # -----------------------------
    # Meta
    # -----------------------------

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO meta(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
                    (key, value),
                )
            finally:
                conn.close()

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT value FROM meta WHERE key=?;", (key,)).fetchone()
                return row["value"] if row else default
            finally:
                conn.close()

    # -----------------------------
    # Device state (commissioning)
    # -----------------------------

    def get_device_state(self) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM device_state WHERE id=1;").fetchone()
                if not row:
                    return {"commissioned": 0, "updated_at_ms": now_ms()}
                return dict(row)
            finally:
                conn.close()

    def is_commissioned(self) -> bool:
        st = self.get_device_state()
        return bool(int(st.get("commissioned", 0)))

    def mark_commissioned(self) -> None:
        t = now_ms()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE device_state
                    SET commissioned=1,
                        commissioned_at_ms=?,
                        updated_at_ms=?
                    WHERE id=1;
                    """,
                    (t, t),
                )
            finally:
                conn.close()

    def reset_commissioning(self) -> None:
        """Engineer-only action will call this."""
        t = now_ms()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE device_state
                    SET commissioned=0,
                        commissioned_at_ms=NULL,
                        updated_at_ms=?
                    WHERE id=1;
                    """,
                    (t,),
                )
            finally:
                conn.close()

    def update_last_selections(
        self,
        mode: Optional[str] = None,
        control_source: Optional[str] = None,
        remote_enable: Optional[bool] = None,
        profile_id: Optional[int] = None,
    ) -> None:
        t = now_ms()
        fields = []
        params: List[Any] = []
        if mode is not None:
            fields.append("last_mode=?")
            params.append(mode)
        if control_source is not None:
            fields.append("last_control_source=?")
            params.append(control_source)
        if remote_enable is not None:
            fields.append("remote_enable=?")
            params.append(1 if remote_enable else 0)
        if profile_id is not None:
            fields.append("last_profile_id=?")
            params.append(profile_id)

        if not fields:
            return

        fields.append("updated_at_ms=?")
        params.append(t)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"UPDATE device_state SET {', '.join(fields)} WHERE id=1;",
                    tuple(params),
                )
            finally:
                conn.close()

    # -----------------------------
    # Key/Value Settings
    # -----------------------------

    def set_setting(self, key: str, value: Any) -> None:
        t = now_ms()
        v = json.dumps(value, ensure_ascii=False)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO settings(key,value,updated_at_ms)
                    VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        updated_at_ms=excluded.updated_at_ms;
                    """,
                    (key, v, t),
                )
            finally:
                conn.close()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT value FROM settings WHERE key=?;", (key,)).fetchone()
                if not row:
                    return default
                try:
                    return json.loads(row["value"])
                except Exception:
                    return row["value"]
            finally:
                conn.close()

    # -----------------------------
    # Calibration Profiles
    # -----------------------------

    def create_profile(self, name: str) -> int:
        """
        Creates a new profile in calibration_profiles table.
        If profile already exists, returns existing profile ID.
        """
        t = now_ms()
        with self._lock:
            conn = self._connect()
            try:
                # Check if profile already exists
                existing = conn.execute("SELECT id FROM calibration_profiles WHERE name=?;", (name,)).fetchone()
                if existing:
                    return int(existing["id"])
                
                # Create new profile
                conn.execute(
                    "INSERT INTO calibration_profiles(name, created_at_ms) VALUES(?, ?);",
                    (name, t),
                )
                pid = conn.execute("SELECT last_insert_rowid() AS id;").fetchone()["id"]
                return int(pid)
            except Exception as e:
                # If insert fails (e.g., duplicate), try to get existing
                try:
                    existing = conn.execute("SELECT id FROM calibration_profiles WHERE name=?;", (name,)).fetchone()
                    if existing:
                        return int(existing["id"])
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def get_profile_id(self, name: str) -> Optional[int]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT id FROM calibration_profiles WHERE name=?;", (name,)).fetchone()
                return int(row["id"]) if row else None
            finally:
                conn.close()

    def list_profiles(self) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT id, name, created_at_ms FROM calibration_profiles ORDER BY created_at_ms DESC;"
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def rename_profile(self, profile_id: int, new_name: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE calibration_profiles SET name=? WHERE id=?;",
                    (new_name, profile_id),
                )
            finally:
                conn.close()

    def delete_profile(self, profile_id: int) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM calibration_profiles WHERE id=?;", (profile_id,))
            finally:
                conn.close()

    # -----------------------------
    # Calibration Points (Legacy/Specific)
    # -----------------------------

    def add_calibration_point(
        self,
        profile_id: int,
        known_cp: float,
        feature: Dict[str, Any],
        temp_c: Optional[float] = None,
    ) -> int:
        t = now_ms()
        feature_json = json.dumps(feature, ensure_ascii=False)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO calibration_points(profile_id, known_cp, feature_json, temp_c, created_at_ms)
                    VALUES(?,?,?,?,?);
                    """,
                    (profile_id, float(known_cp), feature_json, temp_c, t),
                )
                rid = conn.execute("SELECT last_insert_rowid() AS id;").fetchone()["id"]
                return int(rid)
            finally:
                conn.close()

    def list_calibration_points(self, profile_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT id, profile_id, known_cp, feature_json, temp_c, created_at_ms
                    FROM calibration_points
                    WHERE profile_id=?
                    ORDER BY created_at_ms ASC;
                    """,
                    (profile_id,),
                ).fetchall()

                out: List[Dict[str, Any]] = []
                for r in rows:
                    d = dict(r)
                    try:
                        d["feature"] = json.loads(d.pop("feature_json"))
                    except Exception:
                        d["feature"] = {"raw": d.pop("feature_json")}
                    out.append(d)
                return out
            finally:
                conn.close()

    def delete_calibration_point(self, point_id: int) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM calibration_points WHERE id=?;", (point_id,))
            finally:
                conn.close()

    # -----------------------------
    # Events / Audit
    # -----------------------------

    def log_event(self, event_type: str, details: Optional[Dict[str, Any]] = None, ts_ms: Optional[int] = None) -> int:
        t = int(ts_ms or now_ms())
        details_json = json.dumps(details or {}, ensure_ascii=False)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO events(ts_ms, type, details_json) VALUES(?,?,?);",
                    (t, event_type, details_json),
                )
                rid = conn.execute("SELECT last_insert_rowid() AS id;").fetchone()["id"]
                return int(rid)
            finally:
                conn.close()

    def list_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT id, ts_ms, type, details_json FROM events ORDER BY ts_ms DESC LIMIT ?;",
                    (int(limit),),
                ).fetchall()

                out: List[Dict[str, Any]] = []
                for r in rows:
                    d = dict(r)
                    try:
                        d["details"] = json.loads(d.pop("details_json") or "{}")
                    except Exception:
                        d["details"] = {"raw": d.pop("details_json")}
                    out.append(d)
                return out
            finally:
                conn.close()

    # -----------------------------
    # Generic Helpers (For CalibrationStore)
    # -----------------------------

    def exec(self, sql: str, params: Tuple = ()) -> int:
        """
        Executes an INSERT/UPDATE statement and captures the last_row_id.
        Returns the ID for convenience.
        """
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(sql, params)
                # Save ID to instance variable so last_row_id() can retrieve it later if needed
                if cursor.lastrowid:
                    self._last_insert_id = cursor.lastrowid
                return self._last_insert_id
            finally:
                conn.close()

    def last_row_id(self) -> int:
        """
        Returns the ID of the last row inserted via exec().
        """
        with self._lock:
            return self._last_insert_id

    def query_one(self, sql: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        """Returns a single row as a dict, or None."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def query_all(self, sql: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """Returns all rows as a list of dicts."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()