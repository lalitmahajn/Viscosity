# viscologic/core/safety_manager.py
# Safety authority for ViscoLogic: current/temperature limits + fault latch

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional
import time
import logging


def now_ms() -> int:
    return int(time.time() * 1000)


# Alarm codes (match register_map bits conceptually, but Orchestrator will map)
ALM_OVERCURRENT = "OVERCURRENT"
ALM_OVERHEAT = "OVERHEAT"
ALM_SELF_CHECK_FAIL = "SELF_CHECK_FAIL"
ALM_ADC_FAULT = "ADC_FAULT"
ALM_TEMP_FAULT = "TEMP_FAULT"
ALM_SIGNAL_CLIP = "SIGNAL_CLIP"


@dataclass
class SafetyDecision:
    allow_drive: bool
    fault_latched: bool
    active_alarms: Dict[str, bool]
    reason: str = ""


class SafetyManager:
    """
    Safety principles:
      - Hard cap coil current at max_current_ma (default 150 mA)
      - Over-temp triggers fault latch
      - Over-current triggers immediate latch
      - Fault latch blocks drive until reset_alarms() is called AND conditions are normal
    """

    def __init__(self, config: Dict[str, Any]):
        self.logger = logging.getLogger("viscologic.safety")
        s = (config.get("safety", {}) or {})
        self.max_current_ma = int(s.get("max_current_ma", 150))
        self.air_cal_current_ma = int(s.get("air_cal_current_ma", 50))
        self.air_cal_max_sec = int(s.get("air_cal_max_sec", 15))
        self.soft_start_ramp_ms = int(s.get("soft_start_ramp_ms", 800))

        # Temperature limits (optional; safe defaults)
        self.max_temp_c = float(s.get("max_temp_c", 85.0))
        self.temp_fault_c = float(s.get("temp_fault_c", self.max_temp_c))

        self._fault_latched = False
        self._alarms: Dict[str, bool] = {}
        self._last_trip_ms = 0

        # Air calibration guard timer
        self._air_cal_started_ms: Optional[int] = None

    # -----------------------
    # Public helpers
    # -----------------------

    def fault_latched(self) -> bool:
        return bool(self._fault_latched)

    def alarms(self) -> Dict[str, bool]:
        return dict(self._alarms)

    def clear_alarm(self, key: str) -> None:
        if key in self._alarms:
            self._alarms[key] = False

    def set_alarm(self, key: str, value: bool = True) -> None:
        self._alarms[key] = bool(value)

    def reset_alarms(self) -> bool:
        """
        Reset latch only if conditions are healthy (caller should pass current conditions via evaluate()).
        Here we just clear latch; evaluate() may re-latch if still unsafe.
        """
        self._fault_latched = False
        self._acknowledged = False  # Reset acknowledgment on reset
        for k in list(self._alarms.keys()):
            self._alarms[k] = False
        return True

    def acknowledge_alarms(self) -> None:
        """Mark current alarms as acknowledged (stops buzzer, changes UI state)."""
        self._acknowledged = True

    def is_acknowledged(self) -> bool:
        """Check if alarms have been acknowledged by operator."""
        return getattr(self, "_acknowledged", False)

    # -----------------------
    # Air calibration guard
    # -----------------------

    def start_air_cal_guard(self) -> None:
        self._air_cal_started_ms = now_ms()

    def stop_air_cal_guard(self) -> None:
        self._air_cal_started_ms = None

    def air_cal_time_exceeded(self) -> bool:
        if self._air_cal_started_ms is None:
            return False
        return (now_ms() - self._air_cal_started_ms) > (self.air_cal_max_sec * 1000)

    # -----------------------
    # Current limiting
    # -----------------------

    def clamp_current_ma(self, requested_ma: int) -> int:
        """
        Always clamp to safe maximum.
        """
        req = int(requested_ma)
        if req < 0:
            req = 0
        if req > self.max_current_ma:
            req = self.max_current_ma
        return req

    def get_air_cal_current_ma(self) -> int:
        return self.clamp_current_ma(self.air_cal_current_ma)

    # -----------------------
    # Evaluation
    # -----------------------

    def evaluate(
        self,
        *,
        requested_current_ma: int,
        measured_current_ma: Optional[float] = None,
        temp_c: Optional[float] = None,
        adc_ok: bool = True,
        temp_ok: bool = True,
        signal_clip: bool = False,
        self_check_ok: bool = True,
        in_air_cal: bool = False,
    ) -> SafetyDecision:
        """
        Main safety evaluation. Orchestrator calls every tick.

        - requested_current_ma: desired coil current (software setpoint)
        - measured_current_ma: optional sensor reading (if available)
        - temp_c: optional temp reading
        - adc_ok/temp_ok: sensor health flags
        - signal_clip: pickup saturation
        - self_check_ok: global self-check result

        Returns SafetyDecision including allow_drive.
        """
        # Base alarms reset (do not clear latched alarms automatically)
        # Only update current conditions alarms:
        if not self_check_ok:
            self.set_alarm(ALM_SELF_CHECK_FAIL, True)

        if not adc_ok:
            self.set_alarm(ALM_ADC_FAULT, True)

        if not temp_ok:
            self.set_alarm(ALM_TEMP_FAULT, True)

        if signal_clip:
            self.set_alarm(ALM_SIGNAL_CLIP, True)

        # Overcurrent check
        req = self.clamp_current_ma(requested_current_ma)
        if requested_current_ma > self.max_current_ma:
            self.set_alarm(ALM_OVERCURRENT, True)
            self._latch_fault("requested_current_exceeds_limit")

        if measured_current_ma is not None:
            try:
                if float(measured_current_ma) > float(self.max_current_ma) * 1.05:
                    self.set_alarm(ALM_OVERCURRENT, True)
                    self._latch_fault("measured_overcurrent")
                    self._latch_fault("measured_overcurrent")
            except Exception as e:
                self.logger.warning("Error checking measured current: %s", e)

        # Overheat check
        if temp_c is not None:
            try:
                if float(temp_c) >= float(self.temp_fault_c):
                    self.set_alarm(ALM_OVERHEAT, True)
                    self._latch_fault("overheat")
                    self._latch_fault("overheat")
            except Exception as e:
                self.logger.warning("Error checking temp: %s", e)

        # Air calibration time guard
        if in_air_cal and self.air_cal_time_exceeded():
            self.set_alarm(ALM_OVERCURRENT, True)  # treat as safety stop condition
            self._latch_fault("air_cal_timeout")

        # Decide drive
        allow_drive = True
        reason = "ok"

        if self._fault_latched:
            allow_drive = False
            reason = "fault_latched"
        elif self._any_critical_alarm_active():
            # even without latch, if critical alarm active, block drive
            allow_drive = False
            reason = "critical_alarm"

        return SafetyDecision(
            allow_drive=allow_drive,
            fault_latched=self._fault_latched,
            active_alarms=self.alarms(),
            reason=reason,
        )

    def _any_critical_alarm_active(self) -> bool:
        # Treat these as critical
        critical = {
            ALM_OVERCURRENT,
            ALM_OVERHEAT,
            ALM_SELF_CHECK_FAIL,
            ALM_ADC_FAULT,
            ALM_TEMP_FAULT,
        }
        for k in critical:
            if self._alarms.get(k, False):
                return True
        return False

    def _latch_fault(self, why: str) -> None:
        if not self._fault_latched:
            self._fault_latched = True
            self._last_trip_ms = now_ms()

    # -----------------------
    # Reporting helpers
    # -----------------------

    def get_limits(self) -> Dict[str, Any]:
        return {
            "max_current_ma": self.max_current_ma,
            "air_cal_current_ma": self.air_cal_current_ma,
            "air_cal_max_sec": self.air_cal_max_sec,
            "max_temp_c": self.max_temp_c,
            "soft_start_ramp_ms": self.soft_start_ramp_ms,
        }
