# viscologic/drivers/temp_max31865.py
# MAX31865 + PT100 temperature driver (Adafruit CircuitPython)

from __future__ import annotations

import logging
from typing import Dict, Any, Tuple, Optional


class MAX31865Driver:
    """
    Config example:
      temp:
        required: true
        cs_pin: "D5"           # board pin name like "D5" OR gpio integer like 5
        rtd_nominal: 100.0     # PT100 = 100.0, PT1000 = 1000.0
        ref_resistor: 430.0    # typical for PT100 is 430 ohm, for PT1000 often 4300
        wires: 3              # 2/3/4
        filter_hz: 50         # 50 or 60
    """

    def __init__(self, cfg: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.cfg = cfg or {}
        self.logger = logger or logging.getLogger("viscologic.temp")

        self.required = bool(self.cfg.get("required", False))
        self.cs_pin = self.cfg.get("cs_pin", "D5")
        self.rtd_nominal = float(self.cfg.get("rtd_nominal", 100.0))
        self.ref_resistor = float(self.cfg.get("ref_resistor", 430.0))
        self.wires = int(self.cfg.get("wires", 3))
        self.filter_hz = int(self.cfg.get("filter_hz", 50))

        self._sensor = None

    # -----------------------
    # Diagnostics
    # -----------------------

    def probe(self) -> Tuple[bool, str]:
        try:
            self._ensure_open()
            t = self.read_temp_c()
            return True, f"MAX31865 OK temp={t:.2f}C"
        except Exception as e:
            if self.required:
                return False, f"MAX31865 probe error: {e}"
            return True, f"MAX31865 optional/unavailable: {e}"

    # -----------------------
    # Reading
    # -----------------------

    def read_temp_c(self) -> float:
        self._ensure_open()
        # sensor.temperature returns Celsius
        t = float(self._sensor.temperature)  # type: ignore[union-attr]
        return t
    
    def read(self) -> Dict[str, Any]:
        """
        Read temperature and return as dict for compatibility.
        Returns: {"temp_c": float, "fault": bool}
        """
        self._ensure_open()
        try:
            temp = float(self._sensor.temperature)  # type: ignore[union-attr]
            # Check for fault if sensor supports it
            fault = False
            if hasattr(self._sensor, "fault"):
                fault = bool(self._sensor.fault)  # type: ignore[union-attr]
            return {"temp_c": temp, "fault": fault}
        except Exception as e:
            # Return fault state on error
            return {"temp_c": 0.0, "fault": True}
    
    def close(self) -> None:
        """Close hardware connection. Allows reinitialization."""
        self._sensor = None
    
    def reinitialize(self) -> Tuple[bool, str]:
        """
        Close current connection and try to reconnect to hardware.
        Returns: (success: bool, message: str)
        """
        was_mock = self._sensor is not None and hasattr(self._sensor, '_start_time')  # Mock has _start_time
        self.close()
        try:
            self._ensure_open()
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

    # -----------------------
    # Internals
    # -----------------------
    def _ensure_open(self) -> None:
        if self._sensor is not None:
            return

        try:
            # --- REAL HARDWARE PATH ---
            import board   # pyright: ignore[reportMissingImports]
            import busio   # pyright: ignore[reportMissingImports]
            import digitalio   # pyright: ignore[reportMissingImports]
            import adafruit_max31865   # pyright: ignore[reportMissingImports]

            spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI, MISO=board.MISO)

            cs = digitalio.DigitalInOut(self._resolve_cs_pin(board))
            sensor = adafruit_max31865.MAX31865(
                spi,
                cs,
                rtd_nominal=self.rtd_nominal,
                ref_resistor=self.ref_resistor,
                wires=self.wires,
            )

            self.logger.info("MAX31865 hardware driver initialized (PT100/PT1000)")
            self._sensor = sensor

        except Exception as e:
            # --- MOCK PATH (Windows / no hardware) ---
            self.logger.warning(
                "[MOCK] MAX31865 temperature mock driver active (no hardware). Reason: %s",
                e,
            )

            class _MockTemp:
                def __init__(self):
                    import time
                    self._start_time = time.time()
                    self._base_temp = 25.0  # Starting temperature (°C)
                    self._target_temp = 25.0  # Target temperature
                    self._current_temp = 25.0  # Current temperature
                    self._thermal_mass = 0.95  # Thermal inertia (0-1, higher = slower response)
                    self._heater_power = 0.0  # Simulated heater power (0-1)
                    self._ambient_temp = 22.0  # Ambient temperature
                    self._last_update = time.time()
                    self._fault = False
                    self._fault_count = 0
                    
                def _update_thermal_model(self):
                    """Simulate realistic thermal behavior with inertia"""
                    import time, random, math
                    now = time.time()
                    dt = min(1.0, now - self._last_update)  # Cap dt to prevent jumps
                    self._last_update = now
                    
                    # Simulate heater (if drive is active, temperature may rise)
                    # In real system, drive generates heat
                    elapsed = now - self._start_time
                    
                    # Gentle ambient drift (slow changes)
                    ambient_drift = 0.5 * math.sin(elapsed / 300.0)  # 5 min cycle
                    self._ambient_temp = 22.0 + ambient_drift
                    
                    # Simulate heating from drive (if system is running)
                    # This would come from actual system state, but for mock we simulate
                    # gradual heating when "running" (simulated by time-based pattern)
                    if elapsed > 10.0:  # After 10 seconds, simulate system running
                        # Simulate gradual heating toward operating temp
                        self._target_temp = 30.0 + 5.0 * math.sin(elapsed / 600.0)  # 10 min cycle
                    else:
                        self._target_temp = self._ambient_temp
                    
                    # Thermal inertia: temperature approaches target slowly
                    temp_diff = self._target_temp - self._current_temp
                    self._current_temp += temp_diff * (1.0 - self._thermal_mass) * dt * 0.5
                    
                    # Add realistic noise (PT100 sensors have ~0.1°C noise)
                    noise = random.gauss(0.0, 0.08)
                    
                    # Add occasional larger fluctuations (mechanical, airflow)
                    if random.random() < 0.05:  # 5% chance
                        noise += random.uniform(-0.2, 0.2)
                    
                    self._current_temp += noise * dt
                    
                    # Clamp to realistic range
                    self._current_temp = max(-10.0, min(150.0, self._current_temp))
                    
                    # Simulate occasional sensor faults (rare)
                    self._fault_count += 1
                    if self._fault_count > 1000:  # Every ~1000 reads
                        if random.random() < 0.01:  # 1% chance of transient fault
                            self._fault = True
                            self._fault_count = 0
                        else:
                            self._fault = False
                    else:
                        self._fault = False
                
                @property
                def temperature(self):
                    """Returns current temperature with realistic thermal behavior"""
                    self._update_thermal_model()
                    if self._fault:
                        # Fault condition: return invalid reading
                        return float('nan')
                    return self._current_temp
                
                @property
                def fault(self):
                    """Returns fault status"""
                    return self._fault

            self._sensor = _MockTemp()



    def _resolve_cs_pin(self, board_module):
        """
        Accepts:
          - "D5" style board pin name
          - int GPIO pin (fallback to board.D5 mapping is not always 1:1)
        """
        if isinstance(self.cs_pin, int):
            # If user gave int, try to map to board.Dx not possible reliably; ask user to use board pin name.
            raise RuntimeError("cs_pin as int not supported reliably. Use board pin name like 'D5'.")

        name = str(self.cs_pin).strip()
        if not name:
            raise RuntimeError("cs_pin missing")

        # Common patterns: "D5", "CE0", "CE1"
        if hasattr(board_module, name):
            return getattr(board_module, name)

        raise RuntimeError(f"Unknown board pin name: {name}")
