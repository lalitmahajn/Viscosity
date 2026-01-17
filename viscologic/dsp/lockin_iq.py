# viscologic/dsp/lockin_iq.py
# Real-time Digital Lock-in Amplifier (Streaming)
# Mixes input with reference sin/cos and applies IIR Low Pass Filter.

from __future__ import annotations

import math
from typing import Dict, Any, Optional

class LockInIQ:
    """
    Streaming Lock-In Amplifier.
    Usage:
        lockin = LockInIQ(fs_hz=200, ref_freq_hz=180, tau_s=0.2)
        result = lockin.update(current_sample_volts)
    """

    def __init__(self, fs_hz: float, ref_freq_hz: float, tau_s: float = 0.2):
        self.fs = float(fs_hz)
        self.f_ref = float(ref_freq_hz)
        self.tau = float(tau_s)
        
        # Calculate time step and filter alpha
        self.dt = 1.0 / self.fs if self.fs > 0 else 0.005
        self.alpha = 1.0
        self._recalc_filter()
        
        # State
        self.phase_acc = 0.0
        self.i_lpf = 0.0
        self.q_lpf = 0.0
        
        # Public state exposed to Orchestrator
        self.state: Dict[str, Any] = {
            "magnitude": 0.0,
            "phase_deg": 0.0,
            "i": 0.0,
            "q": 0.0,
            "locked": False
        }

    def _recalc_filter(self) -> None:
        """
        Calculate IIR alpha for 1st order Low Pass Filter.
        alpha ~= dt / (tau + dt)
        """
        if self.tau <= 0:
            self.alpha = 1.0
        else:
            self.alpha = self.dt / (self.tau + self.dt)

    def set_ref_freq(self, freq_hz: float) -> None:
        """Called by SweepTracker to update frequency on the fly."""
        self.f_ref = float(freq_hz)

    def update(self, val: float) -> Dict[str, Any]:
        """
        Process a single sample.
        Returns dictionary with keys: magnitude, phase_deg, i, q
        """
        # 1. Update Reference Phase
        # d_phi = 2 * pi * f * dt
        d_phi = 2.0 * math.pi * self.f_ref * self.dt
        self.phase_acc += d_phi
        
        # Wrap phase to keep precision
        if self.phase_acc >= 2.0 * math.pi:
            self.phase_acc -= 2.0 * math.pi
            
        # 2. Generate Reference Signals
        ref_i = math.cos(self.phase_acc)
        ref_q = math.sin(self.phase_acc)
        
        # 3. Mixing (Demodulation)
        # Multiply by 2.0 to recover true amplitude (since avg(sin^2)=0.5)
        raw_i = val * ref_i * 2.0
        raw_q = val * ref_q * 2.0
        
        # 4. Low Pass Filter (Integration)
        self.i_lpf = (1.0 - self.alpha) * self.i_lpf + self.alpha * raw_i
        self.q_lpf = (1.0 - self.alpha) * self.q_lpf + self.alpha * raw_q
        
        # 5. Calculate Magnitude & Phase
        mag = math.sqrt(self.i_lpf**2 + self.q_lpf**2)
        phase = math.degrees(math.atan2(self.q_lpf, self.i_lpf))
        if phase < 0:
            phase += 360.0
        
        # Update state
        self.state = {
            "magnitude": mag,
            "phase_deg": phase,
            "i": self.i_lpf,
            "q": self.q_lpf,
            "locked": True # In streaming mode, we are always "processing"
        }
        return self.state














#==========PREVIOUS CODE==========

# # viscologic/dsp/lockin_iq.py
# # Digital lock-in demodulation (I/Q) using block integration

# from __future__ import annotations

# import math
# from dataclasses import dataclass
# from typing import List, Optional, Dict, Any

# from viscologic.dsp.filters import reject_outliers_mad, rms


# @dataclass
# class LockInResult:
#     amplitude: float          # in same units as input (volts)
#     phase_deg: float          # 0..360
#     i: float
#     q: float
#     dc: float
#     noise_rms: float
#     snr_db: float
#     confidence_pct: int


# class LockInIQ:
#     """
#     Lock-in processing over a block of samples.

#     Inputs:
#       - samples: list of floats (volts)
#       - fs: sample rate estimate (Hz)
#       - f_ref: reference frequency (Hz)

#     Method:
#       - remove DC
#       - multiply by sin/cos refs
#       - integrate (average)
#       - I,Q -> amplitude, phase
#       - estimate noise as RMS of residual after projecting back
#     """

#     def __init__(self, cfg: Optional[Dict[str, Any]] = None):
#         self.cfg = cfg or {}
#         self.outlier_k = float(self.cfg.get("outlier_k", 3.5))
#         self.min_conf_snr_db = float(self.cfg.get("min_conf_snr_db", 6.0))
#         self.max_conf_snr_db = float(self.cfg.get("max_conf_snr_db", 30.0))

#     def process_block(self, samples: List[float], fs: float, f_ref: float) -> LockInResult:
#         if not samples:
#             return LockInResult(
#                 amplitude=0.0, phase_deg=0.0, i=0.0, q=0.0, dc=0.0,
#                 noise_rms=0.0, snr_db=-120.0, confidence_pct=0
#             )

#         x0 = [float(v) for v in samples]
#         # outlier reject (optional)
#         x = reject_outliers_mad(x0, k=self.outlier_k) if len(x0) >= 9 else x0
#         if not x:
#             x = x0

#         # DC removal
#         dc = sum(x) / len(x)
#         x = [v - dc for v in x]

#         # Reference multiply and integrate
#         w = 2.0 * math.pi * float(f_ref)
#         inv_n = 1.0 / len(x)

#         i_acc = 0.0
#         q_acc = 0.0

#         # Use sample index time
#         for n, v in enumerate(x):
#             t = n / float(fs) if fs > 0 else 0.0
#             s = math.sin(w * t)
#             c = math.cos(w * t)
#             # Multiply then average
#             i_acc += v * c
#             q_acc += v * s

#         i = i_acc * inv_n * 2.0
#         q = q_acc * inv_n * 2.0

#         # amplitude and phase
#         amp = math.sqrt(i * i + q * q)
#         phase = math.degrees(math.atan2(q, i))
#         if phase < 0:
#             phase += 360.0

#         # Noise estimate: reconstruct fundamental and compute residual RMS
#         # x_hat = i*cos(wt)/2 + q*sin(wt)/2  (but we scaled i,q already with *2)
#         # So reconstruction becomes: v_hat = 0.5*i*cos + 0.5*q*sin
#         resid = []
#         for n, v in enumerate(x):
#             t = n / float(fs) if fs > 0 else 0.0
#             s = math.sin(w * t)
#             c = math.cos(w * t)
#             v_hat = 0.5 * i * c + 0.5 * q * s
#             resid.append(v - v_hat)

#         noise = rms(resid)
#         # SNR dB (avoid log(0))
#         snr = 20.0 * math.log10((amp + 1e-12) / (noise + 1e-12))

#         conf = self._snr_to_confidence(snr)

#         return LockInResult(
#             amplitude=float(amp),
#             phase_deg=float(phase),
#             i=float(i),
#             q=float(q),
#             dc=float(dc),
#             noise_rms=float(noise),
#             snr_db=float(snr),
#             confidence_pct=int(conf),
#         )

#     def _snr_to_confidence(self, snr_db: float) -> int:
#         """
#         Map SNR dB to 0..100 confidence.
#         """
#         mn = self.min_conf_snr_db
#         mx = self.max_conf_snr_db
#         x = float(snr_db)
#         if x <= mn:
#             return 0
#         if x >= mx:
#             return 100
#         return int(round((x - mn) * 100.0 / (mx - mn)))
