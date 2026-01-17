# viscologic/model/temp_compensation.py
# Temperature compensation engine (ASTM D341 style approximation)

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional
import math


@dataclass
class TempCompResult:
    viscosity_cp_raw: float
    viscosity_cp_ref: float
    temp_c: Optional[float]
    ref_temp_c: float
    profile: str
    method: str
    note: str = ""


class TempCompensation:
    """
    We support two modes:
      1) "none" -> return raw viscosity
      2) "astm_d341_approx" -> uses profile constants (A,B) on log-log scale

    ASTM D341 common form (for kinematic viscosity, but we use same shape):
      log10( log10(v + C) ) = A - B * log10(T)
    We'll use C = 0.7 as typical (approx), and store A,B per profile.

    This is an approximation until you provide real oil chart constants.
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = cfg or {}
        tc = (self.cfg.get("temp_comp", {}) or {})
        self.enabled = bool(tc.get("enabled", True))
        self.method = str(tc.get("method", "astm_d341_approx")).lower()
        self.ref_temp_c = float(tc.get("ref_temp_c", 25.0))

        # profile constants: {profile: {A:.., B:.., C:..}}
        self.profiles = (tc.get("profiles", {}) or {})
        # defaults for unknown profiles
        self.default_C = float(tc.get("default_C", 0.7))

    def apply(self, viscosity_cp: float, temp_c: Optional[float], profile: str = "default") -> TempCompResult:
        raw = float(viscosity_cp)
        p = str(profile or "default")

        if (not self.enabled) or temp_c is None:
            return TempCompResult(
                viscosity_cp_raw=raw,
                viscosity_cp_ref=raw,
                temp_c=temp_c,
                ref_temp_c=self.ref_temp_c,
                profile=p,
                method="none",
                note="temp_comp_disabled_or_no_temp",
            )

        if self.method != "astm_d341_approx":
            return TempCompResult(
                viscosity_cp_raw=raw,
                viscosity_cp_ref=raw,
                temp_c=temp_c,
                ref_temp_c=self.ref_temp_c,
                profile=p,
                method="none",
                note="unknown_method",
            )

        const = self.profiles.get(p) or self.profiles.get(p.upper()) or self.profiles.get("default")
        if not const:
            # safe default: no compensation
            return TempCompResult(
                viscosity_cp_raw=raw,
                viscosity_cp_ref=raw,
                temp_c=temp_c,
                ref_temp_c=self.ref_temp_c,
                profile=p,
                method="none",
                note="profile_not_found",
            )

        try:
            A = float(const.get("A"))
            B = float(const.get("B"))
            C = float(const.get("C", self.default_C))
        except Exception:
            return TempCompResult(
                viscosity_cp_raw=raw,
                viscosity_cp_ref=raw,
                temp_c=temp_c,
                ref_temp_c=self.ref_temp_c,
                profile=p,
                method="none",
                note="invalid_profile_constants",
            )

        # Convert Celsius to Kelvin for D341-like temperature axis
        T1 = float(temp_c) + 273.15
        Tref = float(self.ref_temp_c) + 273.15

        v_ref = self._convert_v_to_temp(raw, T1, Tref, A, B, C)

        return TempCompResult(
            viscosity_cp_raw=raw,
            viscosity_cp_ref=float(v_ref),
            temp_c=float(temp_c),
            ref_temp_c=self.ref_temp_c,
            profile=p,
            method="astm_d341_approx",
            note="ok",
        )

    def _convert_v_to_temp(self, v: float, T_from: float, T_to: float, A: float, B: float, C: float) -> float:
        """
        Using:
          Y = log10(log10(v + C)) = A - B*log10(T)
        We compute Y_from from v, infer A - B*log10(T_from) consistency,
        then compute v_to from Y_to at T_to.
        """
        v = max(1e-9, float(v))
        T_from = max(1.0, float(T_from))
        T_to = max(1.0, float(T_to))

        # compute Y_from
        Y_from = math.log10(max(1e-12, math.log10(v + C)))
        # In theory Y_from == A - B*log10(T_from)
        # We'll instead compute delta using model constants
        Y_to = A - B * math.log10(T_to)

        # Reconstruct viscosity at T_to from Y_to
        inner = 10 ** Y_to
        v_to = (10 ** inner) - C
        if v_to < 0:
            v_to = 0.0
        return float(v_to)
