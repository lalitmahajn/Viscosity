# viscologic/tests/test_sweep.py
# Tests for dsp/sweep_tracker.py

import unittest
import math

from viscologic.dsp.sweep_tracker import SweepTracker


class TestSweepTracker(unittest.TestCase):
    def test_sweep_finds_peak(self):
        # create a fake "response curve" peaking at f_peak
        f_peak = 178.95

        def response_mag(f):
            # gaussian peak
            sigma = 0.6
            return math.exp(-0.5 * ((f - f_peak) / sigma) ** 2)

        st = SweepTracker(
            start_hz=175.0,
            stop_hz=185.0,
            step_hz=0.1,
            dwell_ms=10,
        )

        # feed sweep points as if measured magnitude returned from lock-in
        while not st.is_complete():
            f = st.current_freq_hz()
            mag = response_mag(f)
            st.submit_point(freq_hz=f, magnitude=mag)

        best = st.best_freq_hz()
        self.assertIsNotNone(best)
        self.assertAlmostEqual(best, f_peak, places=1)

    def test_tracker_handles_flat(self):
        st = SweepTracker(start_hz=175.0, stop_hz=185.0, step_hz=0.5, dwell_ms=10)

        while not st.is_complete():
            f = st.current_freq_hz()
            st.submit_point(freq_hz=f, magnitude=1.0)  # flat
        best = st.best_freq_hz()
        self.assertIsNotNone(best)
        # should pick some valid within sweep bounds
        self.assertGreaterEqual(best, 175.0)
        self.assertLessEqual(best, 185.0)

    def test_reset(self):
        st = SweepTracker(start_hz=175.0, stop_hz=176.0, step_hz=0.5, dwell_ms=10)
        while not st.is_complete():
            f = st.current_freq_hz()
            st.submit_point(freq_hz=f, magnitude=0.1)
        self.assertTrue(st.is_complete())

        st.reset()
        self.assertFalse(st.is_complete())
        self.assertIsNone(st.best_freq_hz())


if __name__ == "__main__":
    unittest.main()
