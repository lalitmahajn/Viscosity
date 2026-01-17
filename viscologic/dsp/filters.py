# viscologic/dsp/filters.py
# Basic DSP filters: moving average, median, EMA, outlier rejection
#
# NOTE: This module is currently NOT used in the production codebase.
# It was originally intended for block-based lock-in amplifier processing
# (outlier rejection, RMS noise estimation). The current streaming lock-in
# implementation (lockin_iq.py) processes samples one at a time with built-in
# IIR filtering, so these filters are not needed.
#
# This module is kept available for:
#   - Future enhancements (temperature smoothing, optional block mode)
#   - Debugging and analysis tools
#   - Potential block-based processing mode
#
# See FILTERS_ANALYSIS.md for detailed investigation.

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
import math


def moving_average(x: List[float], window: int) -> List[float]:
    if window <= 1 or len(x) == 0:
        return list(x)
    w = int(window)
    out: List[float] = []
    s = 0.0
    q: List[float] = []
    for v in x:
        q.append(float(v))
        s += float(v)
        if len(q) > w:
            s -= q.pop(0)
        out.append(s / len(q))
    return out


def median(values: List[float]) -> float:
    if not values:
        return 0.0
    a = sorted(float(v) for v in values)
    n = len(a)
    m = n // 2
    if n % 2 == 1:
        return a[m]
    return 0.5 * (a[m - 1] + a[m])


def median_filter(x: List[float], window: int) -> List[float]:
    if window <= 1 or len(x) == 0:
        return list(x)
    w = int(window)
    if w % 2 == 0:
        w += 1
    r = w // 2
    out: List[float] = []
    for i in range(len(x)):
        lo = max(0, i - r)
        hi = min(len(x), i + r + 1)
        out.append(median(x[lo:hi]))
    return out


@dataclass
class EMAFilter:
    alpha: float = 0.2
    _y: Optional[float] = None

    def reset(self) -> None:
        self._y = None

    def update(self, x: float) -> float:
        a = float(self.alpha)
        if a <= 0.0:
            a = 0.01
        if a >= 1.0:
            a = 0.99
        xv = float(x)
        if self._y is None:
            self._y = xv
        else:
            self._y = a * xv + (1.0 - a) * self._y
        return float(self._y)


def mad(values: List[float]) -> float:
    """
    Median absolute deviation (robust). Returns MAD.
    """
    if not values:
        return 0.0
    m = median(values)
    dev = [abs(float(v) - m) for v in values]
    return median(dev)


def reject_outliers_mad(values: List[float], k: float = 3.5) -> List[float]:
    """
    Remove outliers using MAD rule:
      keep v where |v - median| <= k * 1.4826 * MAD
    """
    if not values:
        return []
    m = median(values)
    d = mad(values)
    if d <= 1e-12:
        return list(values)

    scale = 1.4826 * d
    thr = float(k) * scale
    out = []
    for v in values:
        if abs(float(v) - m) <= thr:
            out.append(float(v))
    return out


def clip(values: List[float], lo: float, hi: float) -> List[float]:
    out: List[float] = []
    for v in values:
        fv = float(v)
        if fv < lo:
            fv = lo
        if fv > hi:
            fv = hi
        out.append(fv)
    return out


def rms(values: List[float]) -> float:
    if not values:
        return 0.0
    s2 = 0.0
    for v in values:
        s2 += float(v) * float(v)
    return math.sqrt(s2 / len(values))
