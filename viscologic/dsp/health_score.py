# viscologic/dsp/health_score.py
# Health scoring (0..100) combining signal + lock + sensors + safety

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class HealthScore:
    score: int          # 0..100
    signal: int         # 0..100
    lock: int           # 0..100
    sensors: int        # 0..100
    safety: int         # 0..100 (penalty applied)
    reason: str = ""


class HealthScorer:
    """
    Inputs expected in frame:
      - confidence_pct (0..100) from lock-in
      - locked (bool)
      - adc_ok (bool)
      - temp_ok (bool)
      - fault_latched (bool)
      - alarms (dict[str,bool])
    """

    def __init__(self, cfg: Dict[str, Any] | None = None):
        self.cfg = cfg or {}
        # weights must sum ~1.0
        self.w_signal = float(self.cfg.get("w_signal", 0.40))
        self.w_lock = float(self.cfg.get("w_lock", 0.25))
        self.w_sensors = float(self.cfg.get("w_sensors", 0.20))
        self.w_safety = float(self.cfg.get("w_safety", 0.15))

        # penalties
        self.pen_fault = int(self.cfg.get("pen_fault", 60))
        self.pen_alarm = int(self.cfg.get("pen_alarm", 10))

    def compute(self, frame: Dict[str, Any]) -> HealthScore:
        conf = int(frame.get("confidence_pct", 0))
        conf = max(0, min(100, conf))

        locked = bool(frame.get("locked", False))
        adc_ok = bool(frame.get("adc_ok", True))
        temp_ok = bool(frame.get("temp_ok", True))

        fault = bool(frame.get("fault_latched", False))
        alarms = frame.get("alarms", {}) or {}

        # sub scores
        signal = conf
        lock = 100 if locked else max(0, conf - 20)
        sensors = 100
        if not adc_ok:
            sensors -= 50
        if not temp_ok:
            sensors -= 30
        sensors = max(0, min(100, sensors))

        safety = 100
        if fault:
            safety -= self.pen_fault
        # per active alarm penalty
        active_alarm_count = 0
        try:
            for k, v in alarms.items():
                if bool(v):
                    active_alarm_count += 1
        except Exception:
            active_alarm_count = 1

        safety -= active_alarm_count * self.pen_alarm
        safety = max(0, min(100, safety))

        # weighted total
        total = (
            self.w_signal * signal +
            self.w_lock * lock +
            self.w_sensors * sensors +
            self.w_safety * safety
        )
        score = int(round(total))
        score = max(0, min(100, score))

        reason = "ok"
        if fault:
            reason = "fault"
        elif active_alarm_count > 0:
            reason = "alarms"
        elif not locked:
            reason = "not_locked"
        elif conf < 50:
            reason = "low_signal"

        return HealthScore(
            score=score,
            signal=signal,
            lock=lock,
            sensors=sensors,
            safety=safety,
            reason=reason,
        )
