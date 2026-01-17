# viscologic/tests/test_lockin.py
# Basic functional tests for dsp/lockin_iq.py

import unittest
import math
import random

from viscologic.dsp.lockin_iq import LockInIQ


class TestLockInIQ(unittest.TestCase):
    def test_detects_sine_magnitude(self):
        fs = 1000.0
        f0 = 180.0
        amp = 0.05  # 50 mV equivalent units
        li = LockInIQ(fs_hz=fs, ref_freq_hz=f0, tau_s=0.2)

        # feed 2 seconds of data
        n = int(fs * 2.0)
        for i in range(n):
            t = i / fs
            x = amp * math.sin(2.0 * math.pi * f0 * t)
            out = li.update(x)
            self.assertIsInstance(out, dict)

        mag = float(li.state.get("magnitude", 0.0))
        # lock-in magnitude may not be exactly equal to amp due to scaling,
        # but should be proportional and non-zero.
        self.assertGreater(mag, 0.001)

    def test_rejects_off_frequency(self):
        fs = 1000.0
        f0 = 180.0
        amp = 0.05
        li = LockInIQ(fs_hz=fs, ref_freq_hz=f0, tau_s=0.2)

        # input sine at a far frequency
        fin = 300.0
        n = int(fs * 2.0)
        for i in range(n):
            t = i / fs
            x = amp * math.sin(2.0 * math.pi * fin * t)
            li.update(x)

        mag = float(li.state.get("magnitude", 0.0))
        # should be much lower than on-frequency case
        self.assertLess(mag, 0.02)

    def test_noise_stability(self):
        fs = 1000.0
        f0 = 180.0
        li = LockInIQ(fs_hz=fs, ref_freq_hz=f0, tau_s=0.2)

        n = int(fs * 2.0)
        for _ in range(n):
            x = random.uniform(-0.01, 0.01)
            li.update(x)

        mag = float(li.state.get("magnitude", 0.0))
        # noise-only magnitude should stay small
        self.assertLess(mag, 0.05)


if __name__ == "__main__":
    unittest.main()
