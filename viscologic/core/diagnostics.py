# viscologic/core/diagnostics.py
# Diagnostics and Self-check routines for ViscoLogic

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class CheckItem:
    name: str
    ok: bool
    details: str = ""
    ts_ms: int = field(default_factory=now_ms)


@dataclass
class DiagnosticsReport:
    overall_ok: bool
    items: Dict[str, CheckItem]
    ts_ms: int = field(default_factory=now_ms)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_ok": self.overall_ok,
            "ts_ms": self.ts_ms,
            "items": {
                k: {"name": v.name, "ok": v.ok, "details": v.details, "ts_ms": v.ts_ms}
                for k, v in self.items.items()
            },
        }


class Diagnostics:
    """
    Designed to be "soft" and not crash the app.
    Orchestrator will call:
      - run_startup_checks()
      - run_runtime_checks(frame)
    """

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.config = config or {}
        self.logger = logger or logging.getLogger("viscologic.diagnostics")

    # -----------------------
    # Startup checks
    # -----------------------

    def run_startup_checks(self) -> DiagnosticsReport:
        items: Dict[str, CheckItem] = {}

        # Storage writable
        items["storage_writable"] = self._check_storage_writable()

        # ADC probe (soft)
        items["adc_present"] = self._check_adc_present_soft()

        # Temp sensor probe (soft)
        items["temp_present"] = self._check_temp_present_soft()

        # Modbus config check
        items["modbus_config"] = self._check_modbus_config()

        overall_ok = all(i.ok for i in items.values())
        rep = DiagnosticsReport(overall_ok=overall_ok, items=items)

        self.logger.info("Startup diagnostics: overall_ok=%s", overall_ok)
        for k, it in items.items():
            self.logger.info("  - %s: ok=%s %s", k, it.ok, it.details)

        return rep

    # -----------------------
    # Runtime checks (lightweight)
    # -----------------------

    def run_runtime_checks(self, frame: Dict[str, Any]) -> DiagnosticsReport:
        items: Dict[str, CheckItem] = {}

        # Signal clip info if present
        clip = bool(frame.get("signal_clip", False))
        items["signal_clip"] = CheckItem(
            name="signal_clip",
            ok=not clip,
            details="OK" if not clip else "Pickup signal clipping detected",
        )

        # Temperature range check (if temp is available)
        temp_c = frame.get("temp_c", None)
        max_temp = float((self.config.get("safety", {}) or {}).get("max_temp_c", 85.0))
        if temp_c is None:
            items["temp_range"] = CheckItem(name="temp_range", ok=True, details="Temp not available")
        else:
            try:
                t = float(temp_c)
                ok = t <= max_temp
                items["temp_range"] = CheckItem(
                    name="temp_range",
                    ok=ok,
                    details=f"{t:.2f}C <= {max_temp:.2f}C" if ok else f"Overtemp {t:.2f}C > {max_temp:.2f}C",
                )
            except Exception:
                items["temp_range"] = CheckItem(name="temp_range", ok=False, details="Temp parse error")

        overall_ok = all(i.ok for i in items.values())
        return DiagnosticsReport(overall_ok=overall_ok, items=items)

    # -----------------------
    # Individual checks
    # -----------------------

    def _check_storage_writable(self) -> CheckItem:
        base = (self.config.get("paths", {}) or {}).get("data_dir", "data")
        try:
            os.makedirs(base, exist_ok=True)
            test_path = os.path.join(base, ".write_test")
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(str(time.time()))
            os.remove(test_path)
            return CheckItem(name="storage_writable", ok=True, details=f"Writable: {base}")
        except Exception as e:
            return CheckItem(name="storage_writable", ok=False, details=f"Not writable: {base} ({e})")

    def _check_adc_present_soft(self) -> CheckItem:
        """
        Soft check: tries to import adc driver and call probe() if available.
        Does not require real I2C in dev environment.
        """
        try:
            # Local import to avoid hard dependency during unit tests
            from viscologic.drivers.adc_ads1115 import ADS1115Driver  # type: ignore

            adc_cfg = (self.config.get("adc", {}) or {})
            driver = ADS1115Driver(adc_cfg)
            ok, details = driver.probe()
            return CheckItem(name="adc_present", ok=ok, details=details)
        except Exception as e:
            return CheckItem(name="adc_present", ok=False, details=f"ADC probe failed: {e}")

    def _check_temp_present_soft(self) -> CheckItem:
        try:
            from viscologic.drivers.temp_max31865 import MAX31865Driver  # type: ignore

            tcfg = (self.config.get("temp", {}) or {})
            driver = MAX31865Driver(tcfg)
            ok, details = driver.probe()
            return CheckItem(name="temp_present", ok=ok, details=details)
        except Exception as e:
            # Temp is optional in some builds; treat as warn via config
            required = bool((self.config.get("temp", {}) or {}).get("required", False))
            if required:
                return CheckItem(name="temp_present", ok=False, details=f"Temp probe failed: {e}")
            return CheckItem(name="temp_present", ok=True, details=f"Temp optional/not available: {e}")

    def _check_modbus_config(self) -> CheckItem:
        mb = (self.config.get("modbus", {}) or {})
        enabled = bool(mb.get("enabled", True))
        if not enabled:
            return CheckItem(name="modbus_config", ok=True, details="Modbus disabled by config")
        host = mb.get("host", "0.0.0.0")
        port = mb.get("port", 5020)
        try:
            port_i = int(port)
            ok = 1 <= port_i <= 65535
            return CheckItem(name="modbus_config", ok=ok, details=f"host={host} port={port_i}")
        except Exception as e:
            return CheckItem(name="modbus_config", ok=False, details=f"Invalid port: {port} ({e})")
