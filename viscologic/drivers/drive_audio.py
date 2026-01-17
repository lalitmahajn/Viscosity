# viscologic/drivers/drive_audio.py
# Audio Output Drive Driver (for testing with external scope/oscillator via Headphone Jack)
# Uses 'sounddevice' to generate continuous sine waves.

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None


@dataclass
class DriveStatus:
    enabled: bool
    freq_hz: float
    amplitude: float
    gpio_pin: int  # NA for audio
    backend: str


class AudioDriveDriver:
    """
    Generates a sine wave signal on the default system audio output.
    replaces DrivePWM for testing purposes.
    """

    def __init__(self, cfg: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.cfg = cfg or {}
        self.logger = logger or logging.getLogger("viscologic.drive.audio")

        self.rate = int(self.cfg.get("rate", 44100))
        self.output_device_index = self.cfg.get("output_device_index", None)
        self.gain = float(self.cfg.get("gain", 1.0))  # Master volume trim

        self._stream = None
        self._is_open = False

        # State
        self._enabled = False
        self._freq = 100.0
        self._amp = 0.0
        self._phase = 0.0

        # Lock for parameter updates
        self._lock = threading.Lock()

    # -----------------------
    # Diagnostics
    # -----------------------

    def probe(self) -> Tuple[bool, str]:
        if sd is None:
            return False, "sounddevice not installed"
        try:
            self._ensure_open()
            return True, f"Audio Drive OK (Rate={self.rate})"
        except Exception as e:
            return False, f"Audio Drive probe error: {e}"

    # -----------------------
    # Public API (Matches DrivePWM)
    # -----------------------

    def start(
        self,
        freq_hz: Optional[float] = None,
        amplitude: Optional[float] = None,
        soft_start: bool = True,
    ) -> None:
        self._ensure_open()
        if freq_hz is not None:
            self.set_frequency(freq_hz)
        if amplitude is not None:
            self.set_amplitude(amplitude)
        self._enabled = True

    def stop(self) -> None:
        self._enabled = False
        # We don't close the stream, just silence it (amplitude logic in callback)

    def close(self) -> None:
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._is_open = False

    def reinitialize(self) -> Tuple[bool, str]:
        self.close()
        try:
            self._ensure_open()
            return True, "Audio Drive reinitialized"
        except Exception as e:
            return False, f"Failed: {e}"

    def set_frequency(self, freq_hz: float) -> None:
        with self._lock:
            self._freq = float(freq_hz)

    def set_amplitude(self, amplitude: float) -> None:
        # amplitude 0.0 to 1.0
        val = max(0.0, min(1.0, float(amplitude)))
        with self._lock:
            self._amp = val
            self._enabled = val > 0.0

    def set_duty(self, duty: float) -> None:
        # Compatibility alias
        self.set_amplitude(duty)

    def get_duty(self) -> float:
        return self._amp

    def get_status(self) -> DriveStatus:
        return DriveStatus(
            enabled=self._enabled,
            freq_hz=self._freq,
            amplitude=self._amp,
            gpio_pin=0,
            backend="audio_sd",
        )

    # -----------------------
    # Internals
    # -----------------------

    def _ensure_open(self) -> None:
        if self._is_open:
            return

        if sd is None:
            raise RuntimeError("sounddevice not installed")

        try:
            self._stream = sd.OutputStream(
                samplerate=self.rate,
                channels=1,
                dtype="float32",
                callback=self._audio_callback,
                device=self.output_device_index,
            )
            self._stream.start()
            self._is_open = True
            self.logger.info("Audio Drive started (sounddevice)")
        except Exception as e:
            self.logger.error(f"Failed to open Audio Drive: {e}")
            raise e

    def _audio_callback(self, outdata, frames, time_info, status):
        """
        Fill the buffer with sine wave.
        Must be fast.
        """
        if status:
            pass

        with self._lock:
            freq = self._freq
            amp = self._amp if self._enabled else 0.0

        if amp <= 0.001:
            outdata.fill(0)
            return

        # Generate time steps
        # t = np.arange(frames) / self.rate
        # We need continuous phase tracking
        # phase_increment = 2 * pi * freq / rate

        phase_inc = 2 * np.pi * freq / self.rate
        phase_end = self._phase + (phase_inc * frames)

        # Create phase array: starts at self._phase, increments by phase_inc
        phases = np.linspace(self._phase, phase_end, frames, endpoint=False)

        # Sine wave
        # Output = amp * sin(phases)
        # Apply master gain
        sig = (amp * self.gain) * np.sin(phases)

        # Reshape for output (frames, channels)
        outdata[:] = sig.reshape(-1, 1)

        # Wrap phase to keep precision
        self._phase = phase_end % (2 * np.pi)
