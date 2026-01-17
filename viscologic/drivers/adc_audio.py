# viscologic/drivers/adc_audio.py
# Audio Input ADC Driver (for testing with external oscillator via Mic/Line-in)
# Uses 'sounddevice' library to avoid C++ build errors on Windows.

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None


class AudioADCDriver:
    """
    Captures audio from the default input device and treats it as an ADC signal.
    Useful for testing with an external oscillator connected to the PC's mic jack.

    Config example:
      drivers:6
        adc_type: "audio"
        audio:
          rate: 44100
          chunk: 1024
          input_device_index: null  # null = default
          gain: 1.0                 # Software gain multiplier;
    """

    def __init__(self, cfg: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.cfg = cfg or {}
        self.logger = logger or logging.getLogger("viscologic.adc.audio")

        # Parse Config
        self.rate = int(self.cfg.get("rate", 44100))
        self.chunk = int(self.cfg.get("chunk", 1024))
        self.device_index = self.cfg.get("input_device_index", None)  # None = default
        if self.device_index is not None:
            self.device_index = int(self.device_index)

        self.gain = float(self.cfg.get("gain", 1.0))

        self._stream = None
        self._latest_sample = 0.0
        self._lock = threading.Lock()
        self._is_open = False
        self._debug_counter = 0

    # -----------------------
    # Diagnostics
    # -----------------------

    def probe(self) -> Tuple[bool, str]:
        if sd is None:
            return False, "sounddevice not installed"

        try:
            self._ensure_open()
            return (
                True,
                f"Audio ADC OK (Rate={self.rate}, Device={self.device_index or 'Default'})",
            )
        except Exception as e:
            return False, f"Audio ADC probe error: {e}"

    # -----------------------
    # Open / Close
    # -----------------------

    def close(self) -> None:
        """Stop audio stream and close resources."""
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        self._is_open = False
        self.logger.info("Audio ADC closed")

    def reinitialize(self) -> Tuple[bool, str]:
        self.close()
        try:
            self._ensure_open()
            return True, "Audio ADC reinitialized"
        except Exception as e:
            return False, f"Failed to reinitialize: {e}"

    def _ensure_open(self) -> None:
        if self._is_open:
            return

        if sd is None:
            raise RuntimeError(
                "sounddevice library is missing. Install with 'pip install sounddevice'"
            )

        try:
            # Check devices if needed
            # devices = sd.query_devices()

            # Open stream with callback
            self._stream = sd.InputStream(
                samplerate=self.rate,
                blocksize=self.chunk,
                device=self.device_index,
                channels=1,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()

            self._is_open = True
            self.logger.info("Audio ADC driver started (sounddevice)")

        except Exception as e:
            self.logger.error(f"Failed to open Audio ADC: {e}")
            if self._stream:
                self._stream.close()
            raise e

    def _audio_callback(self, indata, frames, time_info, status):
        """
        Callback from sounddevice. indata is numpy array of shape (frames, channels)
        """
        if status:
            pass  # self.logger.warning(f"Audio status: {status}")

        if len(indata) > 0:
            # Take the last sample (or average of last N)
            # Orchestrator runs slower than audio, so we just want the 'current' voltage.
            # Using the very last sample is the most "real-time"
            val = float(indata[-1, 0]) * self.gain

            with self._lock:
                self._latest_sample = val

            # --- DEBUG: Print peak level every so often ---
            self._debug_counter += 1

            if (
                self._debug_counter % 40 == 0
            ):  # approx every 0.5-1s depending on block size
                peak = np.max(np.abs(indata))
                if peak < 0.001:
                    print(f"[DEBUG ADC] Audio Input is SILENT (Peak: {peak:.6f})")
                else:
                    print(
                        f"[DEBUG ADC] Audio Input active. Peak: {peak:.4f} (Gain={self.gain} -> {peak * self.gain:.4f})"
                    )
            # ----------------------------------------------

    # -----------------------
    # Reading
    # -----------------------

    def read_sample_volts(self) -> float:
        """
        Returns the latest audio sample as a voltage equivalent.
        Audio usually -1.0 to 1.0.
        """
        self._ensure_open()
        with self._lock:
            return float(self._latest_sample)

    def read(self) -> float:
        return self.read_sample_volts()

    def read_samples(
        self, n: Optional[int] = None, sleep_hint: bool = True
    ) -> List[float]:
        s = self.read_sample_volts()
        return [s] * (n or 1)
