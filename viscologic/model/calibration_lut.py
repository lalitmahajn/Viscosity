# viscologic/model/calibration_lut.py
# Calibration LUT builder: feature -> viscosity mapping

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
import math

from viscologic.model.calibration_store import CalibrationPoint


@dataclass
class LutModel:
    mode: str
    profile: str
    feature: str              # "amp_v" | "phase_deg"
    points: List[Tuple[float, float]]  # (feature_value, viscosity_cp) sorted by feature
    method: str               # "linear" | "poly"
    poly_coeff: Optional[List[float]] = None  # highest degree first


class CalibrationLUT:
    """
    Build and evaluate mapping from measured feature to viscosity.
    Default method:
      - Piecewise linear interpolation on (amp_v -> cp)
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = cfg or {}
        self.default_feature = str(self.cfg.get("feature", "amp_v"))  # amp_v or phase_deg
        self.method = str(self.cfg.get("method", "linear")).lower()   # linear/poly
        self.max_poly_degree = int(self.cfg.get("max_poly_degree", 2))

    def build(self, mode: str, profile: str, cal_points: List[CalibrationPoint]) -> LutModel:
        feature = self.default_feature
        pts = self._extract_points(cal_points, feature=feature)

        # ensure monotonic sort by feature value
        pts.sort(key=lambda t: t[0])

        method = self.method
        poly = None
        if method == "poly":
            poly = self._poly_fit(pts)
            if poly is None:
                method = "linear"

        return LutModel(
            mode=str(mode),
            profile=str(profile),
            feature=feature,
            points=pts,
            method=method,
            poly_coeff=poly,
        )

    def evaluate(self, model: LutModel, feature_value: float) -> float:
        x = float(feature_value)
        if not model.points:
            return 0.0

        if model.method == "poly" and model.poly_coeff:
            return float(self._poly_eval(model.poly_coeff, x))

        return float(self._linear_interp(model.points, x))

    # -----------------------
    # Internals
    # -----------------------

    def _extract_points(self, cal_points: List[CalibrationPoint], feature: str) -> List[Tuple[float, float]]:
        out: List[Tuple[float, float]] = []
        for p in cal_points:
            if feature == "phase_deg":
                fv = float(p.phase_deg)
            else:
                fv = float(p.amp_v)
            out.append((fv, float(p.viscosity_cp)))

        # Remove duplicates by averaging same feature (rare)
        out.sort(key=lambda t: t[0])
        merged: List[Tuple[float, float]] = []
        i = 0
        while i < len(out):
            x = out[i][0]
            vs = [out[i][1]]
            j = i + 1
            while j < len(out) and abs(out[j][0] - x) < 1e-12:
                vs.append(out[j][1])
                j += 1
            merged.append((x, sum(vs) / len(vs)))
            i = j
        return merged

    def _linear_interp(self, pts: List[Tuple[float, float]], x: float) -> float:
        # clamp outside range
        if x <= pts[0][0]:
            return pts[0][1]
        if x >= pts[-1][0]:
            return pts[-1][1]

        # find interval
        for i in range(1, len(pts)):
            x0, y0 = pts[i - 1]
            x1, y1 = pts[i]
            if x <= x1:
                if abs(x1 - x0) < 1e-12:
                    return y0
                t = (x - x0) / (x1 - x0)
                return y0 + t * (y1 - y0)
        return pts[-1][1]

    def _poly_fit(self, pts: List[Tuple[float, float]]) -> Optional[List[float]]:
        """
        Fit polynomial y = f(x) using least squares.
        Kept minimal (no numpy dependency).
        Only if len(pts) >= 3.
        Degree capped by max_poly_degree and points-1.
        """
        n = len(pts)
        if n < 3:
            return None

        deg = min(self.max_poly_degree, n - 1)
        if deg < 1:
            return None

        # Build normal equations for Vandermonde
        # Solve using Gaussian elimination (small deg only).
        m = deg + 1

        # A^T A and A^T y
        ata = [[0.0 for _ in range(m)] for _ in range(m)]
        aty = [0.0 for _ in range(m)]

        for x, y in pts:
            # vector [x^deg, ..., x^0]
            vx = [x ** p for p in range(deg, -1, -1)]
            for i in range(m):
                aty[i] += vx[i] * y
                for j in range(m):
                    ata[i][j] += vx[i] * vx[j]

        coeff = self._solve_linear(ata, aty)
        return coeff

    def _poly_eval(self, coeff: List[float], x: float) -> float:
        y = 0.0
        for c in coeff:
            y = y * x + float(c)
        return y

    def _solve_linear(self, A: List[List[float]], b: List[float]) -> Optional[List[float]]:
        """
        Gaussian elimination with partial pivoting.
        """
        n = len(b)
        # augment
        M = [row[:] + [b[i]] for i, row in enumerate(A)]

        for col in range(n):
            # pivot
            pivot = col
            for r in range(col + 1, n):
                if abs(M[r][col]) > abs(M[pivot][col]):
                    pivot = r
            if abs(M[pivot][col]) < 1e-12:
                return None
            if pivot != col:
                M[col], M[pivot] = M[pivot], M[col]

            # normalize
            div = M[col][col]
            for c in range(col, n + 1):
                M[col][c] /= div

            # eliminate
            for r in range(n):
                if r == col:
                    continue
                factor = M[r][col]
                for c in range(col, n + 1):
                    M[r][c] -= factor * M[col][c]

        return [M[i][n] for i in range(n)]
