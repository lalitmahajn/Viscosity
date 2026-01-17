# viscologic/model/calibration_store.py
# Calibration persistence using SQLiteStore

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import time

from viscologic.storage.sqlite_store import SqliteStore


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class CalibrationPoint:
    id: int
    ts_ms: int
    mode: str              # "tabletop" | "inline"
    profile: str           # e.g., "default" | "ISO46"
    label: str             # "Air" | "Water" | "StdOil-100cP" etc.
    viscosity_cp: float
    temp_c: Optional[float]
    amp_v: float           # lock-in amplitude in volts (or chosen feature)
    phase_deg: float
    freq_hz: float
    confidence: int


@dataclass
class CalibrationActive:
    mode: str
    profile: str
    active_set_id: int
    updated_ms: int


class CalibrationStore:
    """
    Tables:
      sensor_calibration_points
      calibration_active
    """

    def __init__(self, db: SqliteStore):
        self.db = db
        self._init_schema()

    def _init_schema(self) -> None:
        self.db.exec(
            """
            CREATE TABLE IF NOT EXISTS sensor_calibration_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                mode TEXT NOT NULL,
                profile TEXT NOT NULL,
                set_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                viscosity_cp REAL NOT NULL,
                temp_c REAL,
                amp_v REAL NOT NULL,
                phase_deg REAL NOT NULL,
                freq_hz REAL NOT NULL,
                confidence INTEGER NOT NULL
            )
            """
        )
        self.db.exec(
            """
            CREATE TABLE IF NOT EXISTS calibration_active (
                mode TEXT NOT NULL,
                profile TEXT NOT NULL,
                active_set_id INTEGER NOT NULL,
                updated_ms INTEGER NOT NULL,
                PRIMARY KEY (mode, profile)
            )
            """
        )

    # -----------------------------
    # Sets management
    # -----------------------------

    def create_new_set(self, mode: str, profile: str) -> int:
        """
        Creates a new set_id as (max(set_id)+1) for mode/profile.
        """
        mode = str(mode)
        profile = str(profile)

        row = self.db.query_one(
            "SELECT COALESCE(MAX(set_id), 0) AS m FROM sensor_calibration_points WHERE mode=? AND profile=?",
            (mode, profile),
        )
        next_id = int((row or {}).get("m", 0)) + 1
        return next_id

    def set_active(self, mode: str, profile: str, set_id: int) -> None:
        mode = str(mode)
        profile = str(profile)
        self.db.exec(
            """
            INSERT INTO calibration_active(mode, profile, active_set_id, updated_ms)
            VALUES(?,?,?,?)
            ON CONFLICT(mode, profile) DO UPDATE SET
              active_set_id=excluded.active_set_id,
              updated_ms=excluded.updated_ms
            """,
            (mode, profile, int(set_id), now_ms()),
        )

    def get_active_set_id(self, mode: str, profile: str) -> Optional[int]:
        row = self.db.query_one(
            "SELECT active_set_id FROM calibration_active WHERE mode=? AND profile=?",
            (str(mode), str(profile)),
        )
        if not row:
            return None
        return int(row["active_set_id"])

    # -----------------------------
    # Points
    # -----------------------------

    def add_point(
        self,
        *,
        mode: str,
        profile: str,
        set_id: int,
        label: str,
        viscosity_cp: float,
        amp_v: float,
        phase_deg: float,
        freq_hz: float,
        confidence: int,
        temp_c: Optional[float] = None,
        ts_ms: Optional[int] = None,
    ) -> int:
        """
        Adds a calibration point to a specific set_id.
        """
        ts = int(ts_ms or now_ms())
        self.db.exec(
            """
            INSERT INTO sensor_calibration_points(
              ts_ms, mode, profile, set_id, label,
              viscosity_cp, temp_c, amp_v, phase_deg, freq_hz, confidence
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ts,
                str(mode),
                str(profile),
                int(set_id),
                str(label),
                float(viscosity_cp),
                None if temp_c is None else float(temp_c),
                float(amp_v),
                float(phase_deg),
                float(freq_hz),
                int(confidence),
            ),
        )
        rid = self.db.last_row_id()
        return int(rid)

    def list_points(self, mode: str, profile: str, set_id: int) -> List[CalibrationPoint]:
        rows = self.db.query_all(
            """
            SELECT * FROM sensor_calibration_points
            WHERE mode=? AND profile=? AND set_id=?
            ORDER BY viscosity_cp ASC, ts_ms ASC
            """,
            (str(mode), str(profile), int(set_id)),
        )
        out: List[CalibrationPoint] = []
        for r in rows:
            out.append(
                CalibrationPoint(
                    id=int(r["id"]),
                    ts_ms=int(r["ts_ms"]),
                    mode=str(r["mode"]),
                    profile=str(r["profile"]),
                    label=str(r["label"]),
                    viscosity_cp=float(r["viscosity_cp"]),
                    temp_c=None if r["temp_c"] is None else float(r["temp_c"]),
                    amp_v=float(r["amp_v"]),
                    phase_deg=float(r["phase_deg"]),
                    freq_hz=float(r["freq_hz"]),
                    confidence=int(r["confidence"]),
                )
            )
        return out

    def get_points_by_set_id(self, set_id: int) -> List[CalibrationPoint]:
        """
        Retrieve calibration points by set_id (for duck-typed compatibility).
        Returns all points for the given set_id.
        """
        rows = self.db.query_all(
            """
            SELECT * FROM sensor_calibration_points
            WHERE set_id=?
            ORDER BY viscosity_cp ASC, ts_ms ASC
            """,
            (int(set_id),),
        )
        out: List[CalibrationPoint] = []
        for r in rows:
            out.append(
                CalibrationPoint(
                    id=int(r["id"]),
                    ts_ms=int(r["ts_ms"]),
                    mode=str(r["mode"]),
                    profile=str(r["profile"]),
                    label=str(r["label"]),
                    viscosity_cp=float(r["viscosity_cp"]),
                    temp_c=None if r["temp_c"] is None else float(r["temp_c"]),
                    amp_v=float(r["amp_v"]),
                    phase_deg=float(r["phase_deg"]),
                    freq_hz=float(r["freq_hz"]),
                    confidence=int(r["confidence"]),
                )
            )
        return out

    def get_active_points(self, mode: str, profile: str) -> List[CalibrationPoint]:
        sid = self.get_active_set_id(mode, profile)
        if sid is None:
            return []
        return self.list_points(mode, profile, sid)

    # -----------------------------
    # Convenience: ensure active exists
    # -----------------------------

    def ensure_active_set(self, mode: str, profile: str) -> int:
        """
        Ensures an active set exists for mode/profile.
        Also ensures the profile exists in calibration_profiles table.
        """
        # First, ensure profile exists in calibration_profiles table
        profile_id = self.db.get_profile_id(profile)
        if profile_id is None:
            # Profile doesn't exist, create it
            try:
                profile_id = self.db.create_profile(profile)
            except Exception:
                # If create_profile fails (e.g., profile already exists from another thread),
                # try to get it again
                profile_id = self.db.get_profile_id(profile)
        
        # Now ensure active set exists
        sid = self.get_active_set_id(mode, profile)
        if sid is not None:
            return sid
        new_sid = self.create_new_set(mode, profile)
        self.set_active(mode, profile, new_sid)
        return new_sid
