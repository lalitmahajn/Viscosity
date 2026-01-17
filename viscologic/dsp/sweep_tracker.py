# viscologic/dsp/sweep_tracker.py
# Resonance sweep + tracking (centroid peak + phase-locked nudging)

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import math
import time


@dataclass
class SweepPoint:
    f_hz: float
    amp: float
    phase_deg: float
    conf: int


@dataclass
class SweepResult:
    best_freq_hz: float
    best_amp: float
    best_phase_deg: float
    locked: bool
    lock_quality: int  # 0..100
    reason: str = ""


class SweepTracker:
    """
    Strategy:
      - Sweep around a band to find the best amplitude peak (lock-in amplitude)
      - Refine peak using centroid with 3 points (left, peak, right)
      - Runtime: keep phase near 90° using small frequency nudge (soft PLL)
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = cfg or {}

        self.f_start = float(self.cfg.get("f_start", 150.0))
        self.f_stop = float(self.cfg.get("f_stop", 200.0))
        self.f_step = float(self.cfg.get("f_step", 1.0))

        self.refine_step = float(self.cfg.get("refine_step", 0.2))  # small step around peak
        self.refine_points = int(self.cfg.get("refine_points", 5))  # odd recommended

        # Locking thresholds
        self.min_conf_for_lock = int(self.cfg.get("min_conf_for_lock", 60))
        self.phase_target_deg = float(self.cfg.get("phase_target_deg", 90.0))
        self.phase_tolerance_deg = float(self.cfg.get("phase_tolerance_deg", 8.0))

        # PLL nudging
        self.nudge_gain = float(self.cfg.get("nudge_gain", 0.05))  # Hz per degree error scaled
        self.max_nudge_hz = float(self.cfg.get("max_nudge_hz", 0.3))

        # internal state
        self._last_best_freq = float(self.cfg.get("default_freq_hz", 180.0))
        self._locked = False
        
        # Sweep execution state
        self._sweep_points: List[SweepPoint] = []
        self._current_sweep_index = 0
        self._sweep_frequencies_list: List[float] = []
        self._dwell_ms = int(self.cfg.get("dwell_ms", 60))
        self._dwell_start_time: Optional[float] = None
        self._sweep_complete = False
        self._current_freq = self.f_start

    # -----------------------------
    # Sweep planning
    # -----------------------------

    def sweep_frequencies(self) -> List[float]:
        f = self.f_start
        out = []
        while f <= self.f_stop + 1e-9:
            out.append(round(f, 4))
            f += self.f_step
        return out

    def refine_frequencies_around(self, f0: float) -> List[float]:
        n = max(3, int(self.refine_points))
        if n % 2 == 0:
            n += 1
        r = n // 2
        out = []
        for i in range(-r, r + 1):
            out.append(round(float(f0) + i * self.refine_step, 4))
        return out

    # -----------------------------
    # Peak selection
    # -----------------------------

    def choose_peak(self, points: List[SweepPoint]) -> Optional[SweepPoint]:
        if not points:
            return None
        # prefer higher confidence then higher amplitude
        best = points[0]
        for p in points[1:]:
            if p.conf > best.conf:
                best = p
            elif p.conf == best.conf and p.amp > best.amp:
                best = p
        return best

    def centroid_3pt(self, left: SweepPoint, mid: SweepPoint, right: SweepPoint) -> float:
        """
        3-point centroid for peak frequency estimation:
          f_centroid = (fL*aL + fM*aM + fR*aR) / (aL+aM+aR)
        """
        denom = (left.amp + mid.amp + right.amp)
        if denom <= 1e-12:
            return mid.f_hz
        return (left.f_hz * left.amp + mid.f_hz * mid.amp + right.f_hz * right.amp) / denom

    def refine_peak_centroid(self, refined_points: List[SweepPoint]) -> float:
        """
        Find max amplitude point then centroid using neighbors if available.
        """
        if not refined_points:
            return self._last_best_freq

        # sort by frequency
        pts = sorted(refined_points, key=lambda p: p.f_hz)

        # find max amplitude index
        idx = 0
        for i in range(1, len(pts)):
            if pts[i].amp > pts[idx].amp:
                idx = i

        if idx <= 0 or idx >= len(pts) - 1:
            return pts[idx].f_hz

        return self.centroid_3pt(pts[idx - 1], pts[idx], pts[idx + 1])

    # -----------------------------
    # Lock logic
    # -----------------------------

    def evaluate_lock(self, amp: float, phase_deg: float, conf: int) -> tuple[bool, int, str]:
        """
        Lock criteria:
          - confidence >= min_conf_for_lock
          - phase near target within tolerance
        """
        if conf < self.min_conf_for_lock:
            return False, min(50, conf), "low_conf"

        # phase error wrap
        err = self._phase_error_deg(phase_deg, self.phase_target_deg)
        if abs(err) > self.phase_tolerance_deg:
            # not fully locked but close -> medium quality
            q = int(max(0, 90 - abs(err) * 5))
            return False, q, "phase_off"

        # lock
        q = int(min(100, conf))
        return True, q, "locked"

    def track_frequency(self, current_freq: float, phase_deg: float) -> float:
        """
        Soft PLL: nudge frequency based on phase error toward target.
        If phase < target => shift frequency upward/downward depending on system response.
        We assume typical resonance: phase increases with frequency around resonance.
        """
        err = self._phase_error_deg(phase_deg, self.phase_target_deg)
        # nudge opposite to error to reduce it
        nudge = -self.nudge_gain * err
        nudge = max(-self.max_nudge_hz, min(self.max_nudge_hz, nudge))
        return float(current_freq) + float(nudge)

    # -----------------------------
    # High-level helpers for orchestrator
    # -----------------------------

    def update_best(self, best_freq: float, locked: bool) -> None:
        self._last_best_freq = float(best_freq)
        self._locked = bool(locked)

    def get_last_best(self) -> float:
        return float(self._last_best_freq)

    def is_locked(self) -> bool:
        return bool(self._locked)
    
    # -----------------------------
    # Sweep execution (called by orchestrator)
    # -----------------------------
    
    def submit_point(self, freq_hz: float, magnitude: float, phase_deg: float = 0.0, conf: int = 0) -> None:
        """
        Submit a data point during sweep.
        Called by orchestrator during SWEEPING state.
        """
        point = SweepPoint(
            f_hz=float(freq_hz),
            amp=float(magnitude),
            phase_deg=float(phase_deg),
            conf=int(conf)
        )
        self._sweep_points.append(point)
    
    def is_complete(self) -> bool:
        """
        Check if sweep is complete.
        Returns True when all frequencies have been swept.
        """
        if self._sweep_complete:
            return True
        
        # Initialize sweep frequencies if not done
        if not self._sweep_frequencies_list:
            self._sweep_frequencies_list = self.sweep_frequencies()
            self._current_sweep_index = 0
            if self._sweep_frequencies_list:
                self._current_freq = self._sweep_frequencies_list[0]
                self._dwell_start_time = time.time()
        
        # Check if we've completed all frequencies
        if self._current_sweep_index >= len(self._sweep_frequencies_list):
            self._sweep_complete = True
            return True
        
        return False
    
    def best_freq_hz(self) -> Optional[float]:
        """
        Get the best frequency found during sweep (highest amplitude).
        Returns None if no points collected yet.
        """
        if not self._sweep_points:
            return None
        
        # Find point with highest amplitude
        best = self._sweep_points[0]
        for p in self._sweep_points[1:]:
            if p.amp > best.amp:
                best = p
        
        return best.f_hz
    
    def get_current_freq(self) -> float:
        """
        Get the current frequency being swept.
        Used by orchestrator to set drive frequency during sweep.
        """
        # If sweep not started, return start frequency
        if not self._sweep_frequencies_list:
            return self.f_start
        
        # Check if we need to advance to next frequency (dwell time elapsed)
        if self._dwell_start_time is not None:
            elapsed_ms = (time.time() - self._dwell_start_time) * 1000.0
            if elapsed_ms >= self._dwell_ms and self._current_sweep_index < len(self._sweep_frequencies_list):
                # Advance to next frequency
                self._current_sweep_index += 1
                if self._current_sweep_index < len(self._sweep_frequencies_list):
                    self._current_freq = self._sweep_frequencies_list[self._current_sweep_index]
                    self._dwell_start_time = time.time()
                else:
                    # Sweep complete
                    self._sweep_complete = True
        
        return self._current_freq
    
    def reset_sweep(self) -> None:
        """Reset sweep state for a new sweep."""
        self._sweep_points.clear()
        self._current_sweep_index = 0
        self._sweep_frequencies_list.clear()
        self._dwell_start_time = None
        self._sweep_complete = False
        self._current_freq = self.f_start

    # -----------------------------
    # Utils
    # -----------------------------

    def _phase_error_deg(self, phase: float, target: float) -> float:
        """
        shortest signed error phase-target in degrees, in [-180..180]
        """
        p = float(phase) % 360.0
        t = float(target) % 360.0
        e = p - t
        while e > 180.0:
            e -= 360.0
        while e < -180.0:
            e += 360.0
        return e
