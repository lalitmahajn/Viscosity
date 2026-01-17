# viscologic/model/viscosity_compute.py
# Convert DSP "feature" -> viscosity (cP) using calibration LUT (safe interpolation),
# then optional temperature compensation (normalization).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union


Number = Union[int, float]


@dataclass
class ViscosityComputeResult:
    ok: bool
    feature_value: float
    viscosity_cp_raw: float           # before temp compensation
    viscosity_cp_ref: float           # normalized/reference (if enabled)
    viscosity_cp_display: float       # what UI/PLC should show
    temp_c: Optional[float]
    profile_id: Optional[int]
    profile_name: str
    note: str = ""
    out_of_range: bool = False


class ViscosityCompute:
    """
    Design goals:
      - Accept "feature" as float OR a frame dict (magnitude/feature_value/raw_adc_mv).
      - Prefer CalibrationLUT if available, else fallback to points interpolation from store.
      - Apply TempCompensation (optional) and choose display mode (raw/ref).
      - Never crash on missing calibration; return ok=False with note.
    """

    def __init__(
        self,
        calibration_store: Optional[Any] = None,
        calibration_lut: Optional[Any] = None,
        temp_comp: Optional[Any] = None,
        cfg: Optional[Dict[str, Any]] = None,
    ):
        self.store = calibration_store
        self.lut = calibration_lut
        self.temp_comp = temp_comp
        self.cfg = cfg or {}

        mc = (self.cfg.get("model", {}) or {})
        # which scalar feature to use from frames
        self.feature_key = str(mc.get("feature_key", "magnitude_clean")).strip()
        # if true, clamp outside range to nearest edge (recommended)
        self.clamp_out_of_range = bool(mc.get("clamp_out_of_range", True))
        # display mode: "raw" (as-measured) or "ref" (normalized)
        self.display_mode = str(mc.get("display_mode", "raw")).lower().strip()

    # -----------------------
    # Public API
    # -----------------------

    def compute(
        self,
        feature_or_frame: Union[Number, Dict[str, Any]],
        temp_c: Optional[float] = None,
        profile_id: Optional[int] = None,
        profile_name: str = "",
    ) -> ViscosityComputeResult:
        feature_val = self._extract_feature(feature_or_frame)
        if feature_val is None:
            return ViscosityComputeResult(
                ok=False,
                feature_value=0.0,
                viscosity_cp_raw=0.0,
                viscosity_cp_ref=0.0,
                viscosity_cp_display=0.0,
                temp_c=temp_c,
                profile_id=profile_id,
                profile_name=profile_name,
                note="feature_missing",
            )

        # if temp is inside frame, prefer it when caller didn't pass
        if temp_c is None and isinstance(feature_or_frame, dict):
            t = feature_or_frame.get("temp_c")
            if isinstance(t, (int, float)):
                temp_c = float(t)

        # choose active profile if not passed
        if profile_id is None:
            profile_id = self._get_active_profile_id()

        # compute raw viscosity using LUT/points
        cp_raw, out_of_range, note = self._cp_from_feature(profile_id, float(feature_val))

        if cp_raw is None:
            return ViscosityComputeResult(
                ok=False,
                feature_value=float(feature_val),
                viscosity_cp_raw=0.0,
                viscosity_cp_ref=0.0,
                viscosity_cp_display=0.0,
                temp_c=temp_c,
                profile_id=profile_id,
                profile_name=profile_name or self._get_profile_name(profile_id),
                note=note or "calibration_not_ready",
            )

        # temp compensation (optional)
        cp_ref = float(cp_raw)
        if self.temp_comp is not None:
            try:
                # profile string passed so you can keep per-fluid constants
                prof = profile_name or self._get_profile_name(profile_id) or f"profile_{profile_id}"
                tc_res = self.temp_comp.apply(cp_raw, temp_c, profile=prof)
                cp_ref = float(getattr(tc_res, "viscosity_cp_ref", cp_raw))
            except Exception:
                # never fail compute due to temp compensation
                cp_ref = float(cp_raw)
                note = (note + ";temp_comp_failed").strip(";")

        # choose display output
        if self.display_mode == "ref":
            cp_disp = cp_ref
        else:
            cp_disp = float(cp_raw)

        return ViscosityComputeResult(
            ok=True,
            feature_value=float(feature_val),
            viscosity_cp_raw=float(cp_raw),
            viscosity_cp_ref=float(cp_ref),
            viscosity_cp_display=float(cp_disp),
            temp_c=temp_c,
            profile_id=profile_id,
            profile_name=profile_name or self._get_profile_name(profile_id),
            note=note or "ok",
            out_of_range=out_of_range,
        )

    def compute_from_frame(self, frame: Dict[str, Any], profile_id: Optional[int] = None) -> ViscosityComputeResult:
        return self.compute(frame, temp_c=frame.get("temp_c"), profile_id=profile_id)

    def is_calibrated(self, profile_id: Optional[int] = None, min_points: int = 2) -> bool:
        pid = profile_id if profile_id is not None else self._get_active_profile_id()
        pts = self._get_points_for_profile(pid)
        return len(pts) >= int(min_points)

    # -----------------------
    # Internal helpers
    # -----------------------

    def _extract_feature(self, feature_or_frame: Union[Number, Dict[str, Any]]) -> Optional[float]:
        if isinstance(feature_or_frame, (int, float)):
            return float(feature_or_frame)

        if not isinstance(feature_or_frame, dict):
            return None

        # direct pass-through keys
        for k in ["feature_value", "feature", self.feature_key, "magnitude_clean", "magnitude", "mag"]:
            v = feature_or_frame.get(k)
            if isinstance(v, (int, float)):
                return float(v)

        # last resort: raw_adc_mv magnitude (absolute)
        v = feature_or_frame.get("raw_adc_mv")
        if isinstance(v, (int, float)):
            return abs(float(v))

        return None

    def _get_active_profile_id(self) -> Optional[int]:
        # store may implement get_active_profile_id() or get_device_state() style
        if self.store is None:
            return None
        for attr in ["get_active_profile_id", "active_profile_id", "get_selected_profile_id"]:
            fn = getattr(self.store, attr, None)
            if callable(fn):
                try:
                    return fn()
                except Exception:
                    continue
        # common pattern: device_state dict
        fn = getattr(self.store, "get_device_state", None)
        if callable(fn):
            try:
                st = fn()
                pid = st.get("last_profile_id") or st.get("profile_id")
                if isinstance(pid, int):
                    return pid
            except Exception:
                pass
        return None

    def _get_profile_name(self, profile_id: Optional[int]) -> str:
        if profile_id is None or self.store is None:
            return ""
        fn = getattr(self.store, "get_profile_name", None)
        if callable(fn):
            try:
                name = fn(profile_id)
                return str(name or "")
            except Exception:
                return ""
        # fallback: try get_profile(profile_id)
        fn2 = getattr(self.store, "get_profile", None)
        if callable(fn2):
            try:
                p = fn2(profile_id)
                if isinstance(p, dict) and p.get("name"):
                    return str(p["name"])
            except Exception:
                pass
        return ""

    def _cp_from_feature(self, profile_id: Optional[int], feature: float) -> Tuple[Optional[float], bool, str]:
        """
        Returns: (cp_raw or None, out_of_range, note)
        """
        if profile_id is None:
            return None, False, "profile_not_selected"

        # 1) Prefer LUT object if it has a known method
        if self.lut is not None:
            for method in ["predict_cp", "cp_from_feature", "evaluate", "interpolate", "lookup"]:
                fn = getattr(self.lut, method, None)
                if callable(fn):
                    try:
                        out = fn(profile_id, feature)
                        # support both scalar and tuple returns
                        if isinstance(out, (int, float)):
                            return float(out), False, "ok"
                        if isinstance(out, tuple) and len(out) >= 1 and isinstance(out[0], (int, float)):
                            # (cp, out_of_range?, note?)
                            oor = bool(out[1]) if len(out) >= 2 else False
                            note = str(out[2]) if len(out) >= 3 else "ok"
                            return float(out[0]), oor, note
                    except Exception:
                        continue

        # 2) Fallback: interpolate from stored calibration points
        pts = self._get_points_for_profile(profile_id)
        if len(pts) < 2:
            return None, False, "not_enough_calibration_points"

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

        x_min, x_max = xs[0], xs[-1]
        out_of_range = feature < x_min or feature > x_max

        if out_of_range and not self.clamp_out_of_range:
            return None, True, "feature_out_of_range"

        # clamp if needed
        x = min(max(feature, x_min), x_max) if self.clamp_out_of_range else feature
        cp = self._linear_interp(xs, ys, x)

        note = "ok"
        if out_of_range:
            note = "clamped_out_of_range" if self.clamp_out_of_range else "out_of_range"

        return float(cp), out_of_range, note

    def _get_points_for_profile(self, profile_id: int) -> List[Tuple[float, float]]:
        """
        Returns sorted list of (feature_value, known_cp)
        Supports several store APIs (duck-typed).
        """
        if self.store is None:
            return []

        # common: store.get_points(profile_id) -> list[dict]
        # Also support get_points_by_set_id for CalibrationStore compatibility
        for method in ["get_points", "get_points_by_set_id", "list_points", "get_calibration_points"]:
            fn = getattr(self.store, method, None)
            if callable(fn):
                try:
                    rows = fn(profile_id)
                    pts = self._normalize_points(rows)
                    pts.sort(key=lambda t: t[0])
                    return pts
                except Exception:
                    continue

        # fallback: store may expose points in-memory
        rows = getattr(self.store, "points", None)
        if rows:
            try:
                pts = self._normalize_points(rows)
                pts = [p for p in pts if p]
                pts.sort(key=lambda t: t[0])
                return pts
            except Exception:
                pass

        return []

    def _normalize_points(self, rows: Any) -> List[Tuple[float, float]]:
        pts: List[Tuple[float, float]] = []
        if not rows:
            return pts

        for r in rows:
            if isinstance(r, (list, tuple)) and len(r) >= 2:
                x, y = r[0], r[1]
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    pts.append((float(x), float(y)))
                continue
            if isinstance(r, dict):
                # try common keys
                x = r.get("feature") or r.get("measured_feature") or r.get("feature_value")
                y = r.get("known_cp") or r.get("viscosity_cp") or r.get("cp")
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    pts.append((float(x), float(y)))
                continue
        return pts

    def _linear_interp(self, xs: List[float], ys: List[float], x: float) -> float:
        """
        Piecewise linear interpolation over sorted xs.
        """
        n = len(xs)
        if n == 0:
            return 0.0
        if n == 1:
            return float(ys[0])

        if x <= xs[0]:
            return float(ys[0])
        if x >= xs[-1]:
            return float(ys[-1])

        # find interval
        lo = 0
        hi = n - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= x:
                lo = mid
            else:
                hi = mid

        x0, x1 = xs[lo], xs[hi]
        y0, y1 = ys[lo], ys[hi]
        if x1 == x0:
            return float(y0)
        t = (x - x0) / (x1 - x0)
        return float(y0 + t * (y1 - y0))
