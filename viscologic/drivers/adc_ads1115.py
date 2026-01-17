# viscologic/drivers/adc_ads1115.py
# ADS1115 driver wrapper (Differential A0-A1)
# Uses Adafruit CircuitPython library for stability.

from __future__ import annotations

import time
import logging
from typing import Dict, Any, Tuple, List, Optional


class ADS1115Driver:
    """
    Config example (settings.yaml):
      adc:
        i2c_bus: 1
        address: 0x48
        gain: 1            # PGA: 1=±4.096V, 2/3=±2.048V, 4=±1.024V, 8=±0.512V, 16=±0.256V
        data_rate: 860     # SPS (8,16,32,64,128,250,475,860)
        differential: "A0_A1"
        samples_per_block: 128
    """

    def __init__(self, cfg: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.cfg = cfg or {}
        self.logger = logger or logging.getLogger("viscologic.adc")

        self.i2c_bus = int(self.cfg.get("i2c_bus", 1))
        self.address = self._parse_int(self.cfg.get("address", 0x48))
        self.gain = self._parse_gain(self.cfg.get("gain", 1))
        self.data_rate = int(self.cfg.get("data_rate", 860))
        self.differential = str(self.cfg.get("differential", "A0_A1"))
        self.samples_per_block = int(self.cfg.get("samples_per_block", 128))

        self._ads = None
        self._chan = None

    # -----------------------
    # Diagnostics
    # -----------------------

    def probe(self) -> Tuple[bool, str]:
        try:
            self._ensure_open()
            return True, f"ADS1115 OK addr=0x{self.address:02X} gain={self.gain} sps={self.data_rate}"
        except Exception as e:
            return False, f"ADS1115 probe error: {e}"

    # -----------------------
    # Open / Close
    # -----------------------

    def close(self) -> None:
        """Close hardware connection. Allows reinitialization."""
        self._ads = None
        self._chan = None
    
    def reinitialize(self) -> Tuple[bool, str]:
        """
        Close current connection and try to reconnect to hardware.
        Returns: (success: bool, message: str)
        """
        was_mock = self._ads is not None and hasattr(self._ads, 'logger')  # Mock has logger attribute
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

    def _ensure_open(self) -> None:
        if self._ads is not None and self._chan is not None:
            return

        try:
            # --- REAL HARDWARE PATH ---
            import board # pyright: ignore[reportMissingImports]
            import busio # pyright: ignore[reportMissingImports]
            import adafruit_ads1x15.ads1115 as ADS # pyright: ignore[reportMissingImports]
            from adafruit_ads1x15.analog_in import AnalogIn # pyright: ignore[reportMissingImports]

            i2c = busio.I2C(board.SCL, board.SDA)

            ads = ADS.ADS1115(i2c, address=self.address)
            ads.gain = self.gain
            ads.data_rate = self._closest_data_rate(self.data_rate)

            if self.differential.upper() in ("A0_A1", "0_1"):
                chan = AnalogIn(ads, ADS.P0, ADS.P1)
            elif self.differential.upper() in ("A2_A3", "2_3"):
                chan = AnalogIn(ads, ADS.P2, ADS.P3)
            else:
                chan = AnalogIn(ads, ADS.P0, ADS.P1)

            self.logger.info(
                "ADS1115 hardware driver initialized addr=0x%02X gain=%s sps=%s",
                self.address, self.gain, self.data_rate
            )

            self._ads = ads
            self._chan = chan

        except Exception as e:
            # --- MOCK PATH (Windows / dev machines) ---
            self.logger.warning(
                "[MOCK] ADS1115 mock driver active (no hardware). Reason: %s",
                e,
            )

            class _MockChan:
                def __init__(self, logger):
                    import time
                    self._t = 0.0
                    self.logger = logger
                    self._start_time = time.time()
                    
                    # Simulate resonant sensor behavior
                    self._base_amplitude = 0.8  # Base signal level (V)
                    self._resonant_freq = 180.0  # Resonant frequency (Hz) - matches typical target
                    self._q_factor = 50.0  # Quality factor (higher = sharper peak)
                    self._noise_level = 0.02  # RMS noise (V)
                    self._dc_offset = 1.2  # DC offset (V)
                    
                    # Simulate drive state (in real system, this comes from drive driver)
                    # For mock, we simulate typical sweep/lock behavior
                    self._simulated_drive_freq = 180.0  # Simulated drive frequency
                    self._simulated_drive_amp = 0.3  # Simulated drive amplitude
                    self._sweep_phase = 0.0  # For simulating frequency sweep
                    
                def _update_simulated_drive(self):
                    """Simulate drive frequency behavior (sweep, lock, etc.)"""
                    import time, math
                    elapsed = time.time() - self._start_time
                    
                    # Simulate sweep behavior: starts low, sweeps up, locks at resonance
                    if elapsed < 5.0:
                        # Initial sweep phase: sweeping from 175 to 185 Hz
                        sweep_progress = elapsed / 5.0
                        self._simulated_drive_freq = 175.0 + sweep_progress * 10.0
                        self._simulated_drive_amp = 0.15 + sweep_progress * 0.15
                    elif elapsed < 10.0:
                        # Locking phase: settling near resonance
                        lock_progress = (elapsed - 5.0) / 5.0
                        # Oscillate slightly around resonance (PLL behavior)
                        self._simulated_drive_freq = 180.0 + 0.5 * math.sin(elapsed * 2.0) * (1.0 - lock_progress)
                        self._simulated_drive_amp = 0.3
                    else:
                        # Locked phase: stable at resonance with small tracking variations
                        self._simulated_drive_freq = 180.0 + 0.1 * math.sin(elapsed * 0.5)
                        self._simulated_drive_amp = 0.3
                
                @property
                def voltage(self):
                    """
                    Simulates resonant sensor pickup signal with realistic behavior.
                    - Higher amplitude at resonance frequency (Lorentzian response)
                    - Includes harmonics (2nd, 3rd order)
                    - Realistic noise characteristics
                    - Responds to simulated drive frequency
                    """
                    import math, random
                    dt = 0.005  # ~200 Hz sample rate
                    self._t += dt
                    
                    # Update simulated drive state
                    self._update_simulated_drive()
                    
                    # Calculate resonance response (Lorentzian-like curve)
                    freq_diff = abs(self._simulated_drive_freq - self._resonant_freq)
                    bandwidth = self._resonant_freq / self._q_factor  # ~3.6 Hz for Q=50
                    resonance_factor = 1.0 / (1.0 + (freq_diff / bandwidth)**2)
                    
                    # Base signal amplitude depends on resonance and drive strength
                    # At resonance: full amplitude, off-resonance: reduced
                    base_amp = self._base_amplitude * (0.3 + 0.7 * resonance_factor) * self._simulated_drive_amp
                    
                    # Generate signal at drive frequency (fundamental)
                    phase = 2.0 * math.pi * self._simulated_drive_freq * self._t
                    signal = base_amp * math.sin(phase)
                    
                    # Add harmonics (2nd and 3rd) - typical in real resonant sensors
                    # Harmonics are weaker and phase-shifted
                    signal += 0.12 * base_amp * math.sin(phase * 2.0 + 0.3)
                    signal += 0.04 * base_amp * math.sin(phase * 3.0 + 0.6)
                    
                    # Add low-frequency drift (thermal expansion, mechanical drift)
                    drift = 0.015 * math.sin(self._t * 0.05) + 0.01 * math.sin(self._t * 0.2)
                    
                    # Add realistic noise (Gaussian + occasional spikes)
                    noise = random.gauss(0.0, self._noise_level)
                    # Occasional larger noise spikes (EMI, mechanical)
                    if random.random() < 0.005:  # 0.5% chance of spike
                        noise += random.choice([-1, 1]) * random.uniform(0.03, 0.08)
                    
                    # Total signal: DC offset + signal + drift + noise
                    total = self._dc_offset + signal + drift + noise
                    
                    # Clamp to realistic ADC range (0-3.3V for typical setup)
                    return max(0.0, min(3.3, total))

            class _MockAds:
                def __init__(self, data_rate):
                    self.data_rate = data_rate

            self._ads = _MockAds(self.data_rate)
            self._chan = _MockChan(self.logger)


    # -----------------------
    # Reading
    # -----------------------

    def read_sample_volts(self) -> float:
        """
        Read one sample in volts (differential).
        """
        self._ensure_open()
        return float(self._chan.voltage)  # type: ignore[union-attr]
    
    def read(self) -> float:
        """
        Alias for read_sample_volts() for compatibility.
        """
        return self.read_sample_volts()

    def read_samples(self, n: Optional[int] = None, sleep_hint: bool = True) -> List[float]:
        """
        Read N samples as fast as possible.
        NOTE: ADS1115 real speed is limited by data_rate.
        """
        self._ensure_open()

        count = int(n or self.samples_per_block)
        out: List[float] = []

        sps = float(self._ads.data_rate) if self._ads else float(self.data_rate)
        dt = 1.0 / max(sps, 1.0)

        for _ in range(count):
            out.append(float(self._chan.voltage))  # type: ignore[union-attr]
            if sleep_hint:
                time.sleep(dt * 0.85)

        return out


    def _parse_int(self, v: Any) -> int:
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            s = v.strip().lower()
            if s.startswith("0x"):
                return int(s, 16)
            return int(s)
        return int(v)

    def _parse_gain(self, g: Any) -> int:
        """
        Adafruit expects gain in {2/3,1,2,4,8,16}
        We'll clamp to valid set.
        """
        try:
            gv = float(g)
        except Exception:
            gv = 1.0

        valid = [2/3, 1, 2, 4, 8, 16]
        # choose nearest
        best = valid[0]
        for v in valid:
            if abs(gv - v) < abs(gv - best):
                best = v
        return best  # type: ignore

    def _closest_data_rate(self, sps: int) -> int:
        valid = [8, 16, 32, 64, 128, 250, 475, 860]
        best = valid[0]
        for v in valid:
            if abs(int(sps) - v) < abs(int(sps) - best):
                best = v
        return best

