# viscologic/storage/csv_logger.py
# CSV Logger for ViscoLogic (thread-safe, start/stop, daily files)

from __future__ import annotations

import os
import csv
import time
import threading
import logging
from typing import Any, Dict, Optional, List


def now_ms() -> int:
    return int(time.time() * 1000)


def _date_str(ts: Optional[float] = None) -> str:
    t = time.localtime(ts or time.time())
    return time.strftime("%Y-%m-%d", t)


class CsvLogger:
    """
    Usage:
      logger = CsvLogger(csv_dir="logs/csv", logger=log)
      logger.start()
      logger.log_frame({...})
      logger.stop()

    Frame expected keys:
      timestamp_ms, viscosity_cp, temp_c, freq_hz, health_pct, status_word, alarm_word
    Additional fields will be appended into "extra_json".
    """

    DEFAULT_FIELDS: List[str] = [
        "timestamp_ms",
        "iso_time",
        "viscosity_cp",
        "temp_c",
        "freq_hz",
        "health_pct",
        "status_word",
        "alarm_word",
        "extra_json",
    ]

    def __init__(self, csv_dir: str, logger: Optional[logging.Logger] = None, flush_every_n: int = 10):
        self.csv_dir = csv_dir
        self.logger = logger or logging.getLogger("viscologic.csv_logger")
        self.flush_every_n = int(flush_every_n)

        self._lock = threading.RLock()
        self._enabled = False
        self._file = None
        self._writer: Optional[csv.DictWriter] = None
        self._current_date = ""
        self._write_count = 0

        os.makedirs(self.csv_dir, exist_ok=True)

    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def start(self) -> None:
        with self._lock:
            if self._enabled:
                return
            self._enabled = True
            self._open_for_today()
            self.logger.info("CSV logging started. dir=%s", self.csv_dir)

    def stop(self) -> None:
        with self._lock:
            if not self._enabled:
                return
            self._enabled = False
            self._close()
            self.logger.info("CSV logging stopped.")

    def _open_for_today(self) -> None:
        today = _date_str()
        if self._file and self._current_date == today and self._writer:
            return

        # close old
        self._close()

        self._current_date = today
        fname = f"viscologic_{today}.csv"
        path = os.path.join(self.csv_dir, fname)

        is_new = not os.path.exists(path)
        self._file = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.DEFAULT_FIELDS)

        if is_new:
            self._writer.writeheader()
            self._file.flush()

        self._write_count = 0

    def _close(self) -> None:
        try:
            if self._file:
                self._file.flush()
                self._file.close()
        finally:
            self._file = None
            self._writer = None
            self._current_date = ""
            self._write_count = 0

    def log_frame(self, frame: Dict[str, Any]) -> bool:
        """
        Returns True if written, False if logging disabled.
        """
        with self._lock:
            if not self._enabled:
                return False

            # rotate daily if day changed
            if _date_str() != self._current_date:
                self._open_for_today()

            if not self._writer or not self._file:
                # Should not happen, but keep safe
                self._open_for_today()
                if not self._writer or not self._file:
                    return False

            row = self._make_row(frame)
            try:
                self._writer.writerow(row)
                self._write_count += 1

                if self._write_count % self.flush_every_n == 0:
                    self._file.flush()

                return True
            except Exception:
                self.logger.error("CSV write failed", exc_info=True)
                return False

    def _make_row(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        ts_ms = int(frame.get("timestamp_ms", now_ms()))
        iso_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_ms / 1000.0))

        # locked columns
        row: Dict[str, Any] = {
            "timestamp_ms": ts_ms,
            "iso_time": iso_time,
            "viscosity_cp": float(frame.get("viscosity_cp", 0.0) or 0.0),
            "temp_c": float(frame.get("temp_c", 0.0) or 0.0),
            "freq_hz": float(frame.get("freq_hz", 0.0) or 0.0),
            "health_pct": int(frame.get("health_pct", 0) or 0),
            "status_word": int(frame.get("status_word", 0) or 0),
            "alarm_word": int(frame.get("alarm_word", 0) or 0),
        }

        # extra keys -> extra_json
        extras = {}
        for k, v in frame.items():
            if k in ("timestamp_ms", "viscosity_cp", "temp_c", "freq_hz", "health_pct", "status_word", "alarm_word"):
                continue
            extras[k] = v

        # store extra as compact string
        try:
            import json
            row["extra_json"] = json.dumps(extras, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            row["extra_json"] = str(extras)

        return row
