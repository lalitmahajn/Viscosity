# viscologic/drivers/drive_pwm.py
# Drive output controller (frequency + amplitude) using pigpio PWM

from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class DriveStatus:
    enabled: bool
    freq_hz: float
    amplitude: float  # 0..1
    gpio_pin: int
    backend: str


class DrivePWM:
    """
    Controls PWM output. Your analog drive chain will convert PWM -> coil drive.
    We keep it simple: PWM freq = target freq, duty = amplitude.

    Config example:
      drive:
        gpio_pin: 18
        backend: "pigpio"
        pwm_range: 1000000     # higher range => finer amplitude control (but depends on pigpio)
        default_freq_hz: 180.0
        default_amplitude: 0.3
        soft_start_ramp_ms: 800
    """

    def __init__(self, cfg: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.cfg = cfg or {}
        self.logger = logger or logging.getLogger("viscologic.drive")

        self.gpio_pin = int(self.cfg.get("gpio_pin", 18))
        self.backend = str(self.cfg.get("backend", "pigpio")).lower()
        self.pwm_range = int(self.cfg.get("pwm_range", 1000000))

        self.default_freq_hz = float(self.cfg.get("default_freq_hz", 180.0))
        self.default_amplitude = float(self.cfg.get("default_amplitude", 0.2))
        self.soft_start_ramp_ms = int(self.cfg.get("soft_start_ramp_ms", 800))

        self._pi = None
        self._enabled = False
        self._freq_hz = self.default_freq_hz
        self._amp = 0.0

    # -----------------------
    # Diagnostics
    # -----------------------

    def probe(self) -> Tuple[bool, str]:
        try:
            self._ensure_open()
            return True, f"DrivePWM OK pin={self.gpio_pin} backend={self.backend}"
        except Exception as e:
            return False, f"DrivePWM probe error: {e}"

    # -----------------------
    # Public API
    # -----------------------

    def start(self, freq_hz: Optional[float] = None, amplitude: Optional[float] = None, soft_start: bool = True) -> None:
        self._ensure_open()
        f = float(freq_hz if freq_hz is not None else self._freq_hz)
        a = float(amplitude if amplitude is not None else self.default_amplitude)
        a = self._clamp01(a)

        self.set_frequency(f)
        if soft_start:
            self._soft_start_to(a, ramp_ms=self.soft_start_ramp_ms)
        else:
            self.set_amplitude(a)

        self._enabled = True

    def stop(self) -> None:
        try:
            if self._pi is not None:
                self._pi.set_PWM_dutycycle(self.gpio_pin, 0)
        except Exception:
            pass
        self._amp = 0.0
        self._enabled = False
    
    def close(self) -> None:
        """Close hardware connection. Allows reinitialization."""
        try:
            if self._pi is not None:
                # Check if it's real pigpio (has 'connected' attribute) vs mock
                if hasattr(self._pi, 'connected') and hasattr(self._pi, 'stop'):
                    # Real pigpio connection
                    self._pi.stop()  # type: ignore[union-attr]
        except Exception:
            pass
        self._pi = None
    
    def reinitialize(self) -> Tuple[bool, str]:
        """
        Close current connection and try to reconnect to hardware.
        Returns: (success: bool, message: str)
        """
        was_mock = self._pi is not None and hasattr(self._pi, 'logger')  # Mock has logger attribute
        was_enabled = self._enabled
        self.close()
        try:
            self._ensure_open()
            if was_enabled:
                # Restore previous state
                self.start(freq_hz=self._freq_hz, amplitude=self._amp, soft_start=False)
            if was_mock:
                return True, "Successfully switched from mock to real hardware"
            else:
                return True, "Hardware reinitialized"
        except Exception as e:
            # Will fall back to mock
            if was_mock:
                return False, f"Still using mock (hardware unavailable: {e})"
            else:
                return False, f"Fell back to mock (hardware unavailable: {e})"

    def set_frequency(self, freq_hz: float) -> None:
        self._ensure_open()
        f = float(freq_hz)
        if f < 1.0:
            f = 1.0
        if f > 2000.0:
            f = 2000.0

        # pigpio sets hardware PWM on specific pins; fallback to software PWM if needed.
        self._pi.set_PWM_frequency(self.gpio_pin, int(round(f)))  # type: ignore[union-attr]
        self._freq_hz = f

    def set_amplitude(self, amplitude: float) -> None:
        self._ensure_open()
        a = self._clamp01(float(amplitude))
        duty = int(round(a * self.pwm_range))
        duty = max(0, min(self.pwm_range, duty))

        self._pi.set_PWM_range(self.gpio_pin, self.pwm_range)  # type: ignore[union-attr]
        # pigpio dutycycle uses 0..range for set_PWM_dutycycle only if range is set.
        self._pi.set_PWM_dutycycle(self.gpio_pin, duty)  # type: ignore[union-attr]

        self._amp = a
        self._enabled = (a > 0.0)
    
    def set_duty(self, duty: float) -> None:
        """
        Set duty cycle (0.0 to 1.0). Alias for set_amplitude() for compatibility.
        """
        self.set_amplitude(duty)
    
    def get_duty(self) -> float:
        """
        Get current duty cycle (0.0 to 1.0). Returns current amplitude value.
        """
        return float(self._amp)

    def get_status(self) -> DriveStatus:
        return DriveStatus(
            enabled=self._enabled,
            freq_hz=float(self._freq_hz),
            amplitude=float(self._amp),
            gpio_pin=int(self.gpio_pin),
            backend=self.backend,
        )

    # -----------------------
    # Internals
    # -----------------------

    def _ensure_open(self) -> None:
        if self._pi is not None:
            return

        if self.backend != "pigpio":
            raise RuntimeError("Only pigpio backend supported in this build")

        try:
            # --- REAL HARDWARE PATH ---
            import pigpio  # type: ignore

            pi = pigpio.pi()
            if not pi.connected:
                raise RuntimeError("pigpio not connected. Start pigpiod service.")

            pi.set_mode(self.gpio_pin, pigpio.OUTPUT)
            pi.set_PWM_range(self.gpio_pin, self.pwm_range)
            pi.set_PWM_dutycycle(self.gpio_pin, 0)

            self.logger.info(
                "DrivePWM hardware driver initialized (pigpio) pin=%s",
                self.gpio_pin,
            )

            self._pi = pi

        except Exception as e:
            # --- MOCK PATH (Windows / no pigpio) ---
            self.logger.warning(
                "[MOCK] DrivePWM mock driver active (no hardware). Reason: %s",
                e,
            )

            class _MockPi:
                def __init__(self, logger, drive_instance):
                    self.logger = logger
                    self.drive_instance = drive_instance  # Reference to DrivePWM for state tracking
                    self.freq = 0
                    self.range = 1000
                    self.duty = 0
                    self._last_update_time = time.time()
                    self._freq_ramp_active = False
                    self._target_freq = 0.0
                    self._freq_ramp_rate = 10.0  # Hz per second for frequency changes

                def set_mode(self, pin, mode):
                    self.logger.debug(f"[MOCK] set_mode(pin={pin}, mode={mode})")

                def set_PWM_range(self, pin, rng):
                    self.range = rng
                    self.logger.debug(f"[MOCK] set_PWM_range(pin={pin}, range={rng})")

                def set_PWM_frequency(self, pin, freq):
                    """Simulate realistic frequency change with ramp"""
                    target = int(round(freq))
                    if abs(target - self.freq) > 1.0:
                        # Frequency change > 1 Hz: ramp it
                        self._target_freq = float(target)
                        self._freq_ramp_active = True
                        self._last_update_time = time.time()
                    else:
                        # Small change: instant
                        self.freq = target
                        self._freq_ramp_active = False
                    self._update_freq_ramp()
                    self.logger.debug(f"[MOCK] set_PWM_frequency(pin={pin}, freq={self.freq} Hz)")

                def set_PWM_dutycycle(self, pin, duty):
                    """Simulate realistic duty cycle with tracking"""
                    self.duty = duty
                    # Update drive instance state
                    if self.drive_instance:
                        self.drive_instance._amp = float(duty) / float(self.range) if self.range > 0 else 0.0
                        self.drive_instance._freq_hz = float(self.freq)
                    self.logger.debug(f"[MOCK] set_PWM_dutycycle(pin={pin}, duty={duty}/{self.range} = {self.duty/self.range if self.range > 0 else 0.0:.3f})")
                
                def _update_freq_ramp(self):
                    """Update frequency ramp if active"""
                    if not self._freq_ramp_active:
                        return
                    now = time.time()
                    dt = now - self._last_update_time
                    if dt > 0:
                        max_change = self._freq_ramp_rate * dt
                        diff = self._target_freq - self.freq
                        if abs(diff) <= max_change:
                            self.freq = int(round(self._target_freq))
                            self._freq_ramp_active = False
                        else:
                            self.freq += int(round(max_change if diff > 0 else -max_change))
                        self._last_update_time = now
                        # Update drive instance
                        if self.drive_instance:
                            self.drive_instance._freq_hz = float(self.freq)

            self._pi = _MockPi(self.logger, self)


    def _soft_start_to(self, target_amp: float, ramp_ms: int) -> None:
        target = self._clamp01(target_amp)
        start = float(self._amp)
        if ramp_ms <= 0:
            self.set_amplitude(target)
            return

        steps = max(5, int(ramp_ms / 50))
        for i in range(1, steps + 1):
            a = start + (target - start) * (i / steps)
            self.set_amplitude(a)
            time.sleep(ramp_ms / steps / 1000.0)

    def _clamp01(self, v: float) -> float:
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v
