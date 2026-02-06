# viscologic/core/orchestrator.py
"""
System Orchestrator (single place glue)

Responsibilities:
- Load config, create all subsystems
- Main tick loop (read ADC/temp, drive update, DSP lock-in + sweep, compute viscosity)
- Safety + diagnostics update
- UI snapshot state
- Modbus: read control commands, publish live values/status to registers
- Logging: CSV + SQLite (best-effort, non-fatal)
"""

from __future__ import annotations

import os
import time
import logging
import json
import threading
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple

from viscologic.core.state_machine import SystemStateMachine, SystemState
from viscologic.core.safety_manager import SafetyManager
from viscologic.core.diagnostics import Diagnostics

from viscologic.security.commissioning_manager import CommissioningManager

from viscologic.drivers.adc_ads1115 import ADS1115Driver as ADS1115ADC
from viscologic.drivers.drive_pwm import DrivePWM
from viscologic.drivers.temp_max31865 import MAX31865Driver as MAX31865Temp

from viscologic.dsp.lockin_iq import LockInIQ
from viscologic.dsp.sweep_tracker import SweepTracker
from viscologic.dsp.health_score import HealthScorer

from viscologic.model.calibration_store import CalibrationStore
from viscologic.model.calibration_lut import CalibrationLUT
from viscologic.model.viscosity_compute import ViscosityCompute
from viscologic.model.temp_compensation import TempCompensation

from viscologic.protocols.register_map import RegisterBank
from viscologic.protocols.modbus_server import ModbusServer

from viscologic.storage.sqlite_store import SqliteStore
from viscologic.storage.csv_logger import CsvLogger
from viscologic.storage.retention import RetentionManager


@dataclass
class RuntimeSnapshot:
    ts: float = 0.0
    state: str = "IDLE"

    mode: str = "tabletop"
    control_source: str = "mixed"

    freq_hz: float = 0.0
    duty: float = 0.0

    adc_raw: float = 0.0
    magnitude: float = 0.0
    phase_deg: float = 0.0

    viscosity_cp: float = 0.0
    temp_c: float = 0.0

    confidence: float = 0.0
    health_ok: bool = True

    locked: bool = False
    fault: bool = False
    alarm_active: bool = False
    alarms: Dict[str, bool] = None  # Added for UI
    last_fault_reason: str = ""

    logging: bool = False
    
    remote_enabled: bool = True
    last_cmd_source: str = "local"

    active_profile: str = "Default"


class Orchestrator:
    def __init__(
        self, 
        config: Dict[str, Any] | Any, 
        bus: Any, 
        logger: Optional[logging.Logger] = None
    ) -> None:
        
        # 1. Use injected dependencies
        self.config = config
        self.bus = bus
        self.logger = logger or logging.getLogger("viscologic.orchestrator")

        # --- Initialize SQLite FIRST ---
        db_path = "data/viscologic.db"
        val = self._cfg_get("storage.sqlite.path")
        if val: 
            db_path = str(val)

        self.sqlite = SqliteStore(db_path, logger=self.logger)
        # Initialize database schema
        try:
            self.sqlite.init_db()
        except Exception:
            self.logger.warning("SQLite init_db failed (may already be initialized)", exc_info=True)

        # 2. Subsystems
        self.sm = SystemStateMachine()
        self.safety = SafetyManager(self.config)
        self.diag = Diagnostics(self.config, self.logger)
        self.commissioning = CommissioningManager(self.sqlite, self.config, self.logger)

        self.regmap = RegisterBank()

        # --- CsvLogger ---
        csv_path = str(self._cfg_get("storage.csv_logger.folder", "logs"))
        self.csv = CsvLogger(
            csv_dir=csv_path,
            logger=self.logger
        )

        # --- Retention Init ---
        self.retention = RetentionManager(logger=self.logger)
        self._ret_db_days = int(self._cfg_get("storage.retention.db_days", 90))
        self._ret_csv_days = int(self._cfg_get("storage.csv_logger.retention_days", 30))

        # ---------------------------------------------------------
        # 4. Drivers
        # ---------------------------------------------------------
        
        # --- ADC Config ---
        # --- ADC Config ---
        adc_type = str(self._cfg_get("drivers.adc_type", "ads1115")).lower()
        
        if adc_type == "audio":
            from viscologic.drivers.adc_audio import AudioADCDriver
            audio_cfg = {
                "rate": int(self._cfg_get("drivers.audio.rate", 44100)),
                "chunk": int(self._cfg_get("drivers.audio.chunk", 1024)),
                "input_device_index": self._cfg_get("drivers.audio.input_device_index"),
                "gain": float(self._cfg_get("drivers.audio.gain", 1.0)),
            }
            self.adc = AudioADCDriver(cfg=audio_cfg, logger=self.logger)
        else:
            adc_cfg = {
                "i2c_bus": int(self._cfg_get("hardware.i2c_bus", 1)),
                "address": int(self._cfg_get("drivers.adc_ads1115.i2c_addr", 0x48)),
                "gain": int(self._cfg_get("drivers.adc_ads1115.gain", 1)),
                "data_rate": int(self._cfg_get("drivers.adc_ads1115.sample_rate_sps", 860)),
                "differential": "A0_A1",
                "vref": float(self._cfg_get("drivers.adc_ads1115.vref", 3.3)),
            }
            self.adc = ADS1115ADC(cfg=adc_cfg, logger=self.logger)

        # --- Drive Config ---
        # --- Drive Config ---
        drive_type = str(self._cfg_get("drivers.drive_type", "pwm")).lower()
        
        if drive_type == "audio":
            from viscologic.drivers.drive_audio import AudioDriveDriver
            audio_drv_cfg = {
                "rate": int(self._cfg_get("drivers.audio.rate", 44100)),
                "output_device_index": self._cfg_get("drivers.audio.output_device_index"),
                "gain": float(self._cfg_get("drivers.audio.output_gain", 1.0)),
            }
            self.drive = AudioDriveDriver(cfg=audio_drv_cfg, logger=self.logger)
        else:
            drive_cfg = {
                "gpio_pin": int(self._cfg_get("hardware.gpio.pwm_pin", 18)),
                "backend": str(self._cfg_get("drivers.drive_pwm.backend", "pigpio")),
                "pwm_range": int(self._cfg_get("drivers.drive_pwm.pwm_range", 1000000)),
                "default_freq_hz": int(self._cfg_get("drivers.drive_pwm.pwm_freq_hz", 20000)),
                "duty_min": float(self._cfg_get("drivers.drive_pwm.duty_min", 0.02)),
                "duty_max": float(self._cfg_get("drivers.drive_pwm.duty_max", 0.85)),
            }
            self.drive = DrivePWM(cfg=drive_cfg, logger=self.logger)

        # --- Temp Config ---
        temp_cfg = {
            "cs_pin": self._cfg_get("drivers.temp_max31865.spi_cs", 0),
            "rtd_nominal": float(self._cfg_get("drivers.temp_max31865.rtd_nominal", 100.0)),
            "ref_resistor": float(self._cfg_get("drivers.temp_max31865.ref_resistor", 430.0)),
            "wires": int(self._cfg_get("drivers.temp_max31865.wires", 3)),
            "filter_hz": int(self._cfg_get("drivers.temp_max31865.filter_hz", 50)),
            "required": True
        }
        self.temp = MAX31865Temp(cfg=temp_cfg, logger=self.logger)

        # 5. DSP / Model
        self._fs_hz = float(self._cfg_get("app.sample_rate_hz", 200))
        self._target_freq_hz = float(self._cfg_get("dsp.target_freq_hz", 180.0))

        self.lockin = LockInIQ(
            fs_hz=self._fs_hz,
            ref_freq_hz=self._target_freq_hz,
            tau_s=float(self._cfg_get("dsp.lockin_tau_s", 0.2)),
        )

        # --- Sweep Config ---
        sweep_span = float(self._cfg_get("dsp.sweep_span_hz", 5.0))
        sweep_step = float(self._cfg_get("dsp.sweep_step_hz", 0.1))
        
        sweep_cfg = {
            "f_start": self._target_freq_hz - (sweep_span / 2.0),
            "f_stop": self._target_freq_hz + (sweep_span / 2.0),
            "f_step": sweep_step,
            "refine_step": sweep_step / 5.0, 
            "dwell_ms": int(self._cfg_get("dsp.sweep_dwell_ms", 60)),
        }
        
        self.sweep = SweepTracker(cfg=sweep_cfg)

        self.health = HealthScorer(self.config)
        self.cal_store = CalibrationStore(self.sqlite)
        
        # Initialize CalibrationLUT
        lut_cfg = self._cfg_get("model.calibration_lut", {}) or {}
        self.lut = CalibrationLUT(cfg=lut_cfg)
        
        temp_comp_cfg = {
            "temp_comp": {
                "enabled": bool(self._cfg_get("model.temp_compensation.enabled", True)),
                "ref_temp_c": float(self._cfg_get("model.temp_compensation.reference_temp_c", 25.0)),
            }
        }
        
        self.temp_comp = TempCompensation(cfg=temp_comp_cfg)
        
        # Initialize ViscosityCompute with all dependencies
        visc_cfg = self._cfg_get("model.viscosity_compute", {}) or {}
        self.visc_compute = ViscosityCompute(
            calibration_store=self.cal_store,
            calibration_lut=self.lut,
            temp_comp=self.temp_comp,
            cfg=visc_cfg
        )

        # --- Modbus Init ---
        self.modbus = ModbusServer(self.config, self.bus, self.logger)

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._snapshot = RuntimeSnapshot()
        self._snapshot_lock = threading.Lock()

        self._last_control_word: int = 0
        self._last_cmd_source: str = "local"

        self._runtime_state_path = "data/runtime_state.json"
        self._ensure_folders()

        self._wire_bus()

        # Apply config mode to SM
        self.sm.set_mode(str(self._cfg_get("app.mode", "tabletop")))
        self.sm.set_comm_loss_action(str(self._cfg_get("protocols.comm_loss_action", "safe_stop")))

    # ------------------------
    # Config Helper
    # ------------------------
    def _cfg_get(self, key: str, default: Any = None) -> Any:
        # 1. If it's a real ConfigManager with a .get(key) method, use it
        if hasattr(self.config, "get") and callable(self.config.get):
            try:
                val = self.config.get(key)
                if val is not None:
                    return val
            except Exception:
                pass

        # 2. If it's a dictionary (or fallback), traverse dots manually
        if isinstance(self.config, dict):
            parts = key.split(".")
            curr = self.config
            try:
                for p in parts:
                    if isinstance(curr, dict):
                        curr = curr.get(p)
                    else:
                        return default
                return curr if curr is not None else default
            except Exception:
                return default
        
        return default

    # ------------------------
    # Public control
    # ------------------------
    def start(self) -> None:
        """Start modbus + start orchestrator loop in background thread."""
        self._stop.clear()

        # Ensure commissioning lock is satisfied
        try:
            if hasattr(self.commissioning, "ensure_commissioned"):
                self.commissioning.ensure_commissioned()
                self.logger.info("SM Init State: %s", self.sm.state)

        except Exception:
            pass

        # Start modbus server (best effort)
        try:
            if bool(self._cfg_get("protocols.modbus_server.enabled", True)):
                if hasattr(self.modbus, "start"):
                    self.modbus.start()
        except Exception:
            pass

        # Start CSV logger (best effort)
        # Start CSV logger (best effort)
        try:
            # Only auto-start if explicitly configured
            if bool(self._cfg_get("storage.csv_logger.enabled", True)):
                if bool(self._cfg_get("storage.csv_logger.auto_start", False)):
                    if hasattr(self.csv, "start"):
                        self.csv.start()
        except Exception:
            pass

        # Auto-resume (inline mode only, commissioned only)
        self._apply_auto_resume_policy()

        self._thread = threading.Thread(target=self._run_loop, name="ViscoLogic-Orchestrator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop orchestrator loop + stop drivers safely."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        # safe stop drive
        try:
            if hasattr(self.drive, "set_duty"):
                self.drive.set_duty(0.0)
        except Exception:
            pass

        try:
            if hasattr(self.drive, "stop"):
                self.drive.stop()
        except Exception:
            pass

        # stop modbus
        try:
            if hasattr(self.modbus, "stop"):
                self.modbus.stop()
        except Exception:
            pass

        # stop CSV logger
        try:
            if hasattr(self.csv, "stop"):
                self.csv.stop()
        except Exception:
            pass

        self._persist_runtime_state(running=False)

    def get_snapshot(self) -> Dict[str, Any]:
        with self._snapshot_lock:
            return asdict(self._snapshot)

    # UI calls
    def ui_start(self) -> None:
        self._last_cmd_source = "local"
        self.sm.handle_event("START", {"source": "local"})

    def ui_stop(self) -> None:
        self._last_cmd_source = "local"
        self.sm.handle_event("STOP", {"source": "local"})

    def ui_ack_alarm(self) -> None:
        self._last_cmd_source = "local"
        self.sm.handle_event("ALARM_ACK", {"source": "local"})

    def ui_reset_alarm(self) -> None:
        self._last_cmd_source = "local"
        self.sm.handle_event("ALARM_RESET", {"source": "local"})

    def ui_set_mode(self, mode: str) -> None:
        mode = "inline" if mode == "inline" else "tabletop"
        if hasattr(self.config, "set") and callable(getattr(self.config, "set", None)):
            self.config.set("app.mode", mode)  # type: ignore
        elif isinstance(self.config, dict):
            try: self.config["app"]["mode"] = mode 
            except: pass
        self.sm.set_mode(mode)

    def ui_set_control_source(self, src: str) -> None:
        src = src if src in ("local", "remote", "mixed") else "mixed"
        if hasattr(self.config, "set") and callable(getattr(self.config, "set", None)):
            self.config.set("app.control_source", src)  # type: ignore
        elif isinstance(self.config, dict):
            try: self.config["app"]["control_source"] = src
            except: pass

    # ------------------------
    # Internals
    # ------------------------
    def _ensure_folders(self) -> None:
        os.makedirs("data", exist_ok=True)
        os.makedirs(str(self._cfg_get("storage.csv_logger.folder", "logs")), exist_ok=True)

    def _wire_bus(self) -> None:
        """
        FIXED: Connects to 'ui.command' to handle Start/Stop from the UI.
        Also listens for settings updates from Engineer Screen.
        """
        try:
            if hasattr(self.bus, "subscribe"):
                # Handle generic commands from UI (OperatorScreen)
                self.bus.subscribe("ui.command", self._handle_ui_command)
                # Handle settings updates from Engineer Screen
                self.bus.subscribe("settings.updated", self._handle_settings_updated)
                # Keep legacy specific subscriptions just in case
                self.bus.subscribe("ui/start", lambda payload=None: self.ui_start())
                self.bus.subscribe("ui/stop", lambda payload=None: self.ui_stop())
                self.bus.subscribe("ui/alarm_ack", lambda payload=None: self.ui_ack_alarm())
                self.bus.subscribe("ui/alarm_reset", lambda payload=None: self.ui_reset_alarm())
        except Exception:
            pass

    def _handle_ui_command(self, payload: Dict[str, Any]) -> None:
        """Dispatcher for UI commands from OperatorScreen"""
        if not isinstance(payload, dict): return
        
        cmd = str(payload.get("cmd", "")).upper()
        self._last_cmd_source = payload.get("source", "local")
        
        if cmd == "START":
            self.sm.handle_event("START", {"source": self._last_cmd_source})
        elif cmd == "STOP":
            self.sm.handle_event("STOP", {"source": self._last_cmd_source})
        elif cmd == "ALARM_ACK":
            # Mark alarms as acknowledged (silences buzzer, UI state change)
            if hasattr(self.safety, "acknowledge_alarms"):
                self.safety.acknowledge_alarms()
            self.sm.handle_event("ALARM_ACK", {"source": self._last_cmd_source})
        elif cmd == "ALARM_RESET":
            # FIXED: Must reset safety latch too!
            if hasattr(self.safety, "reset_alarms"):
                self.safety.reset_alarms()
            self.sm.handle_event("ALARM_RESET", {"source": self._last_cmd_source})
        elif cmd == "LOG_START":
            if hasattr(self.csv, "start"):
                self.csv.start()
        elif cmd == "LOG_STOP":
            if hasattr(self.csv, "stop"):
                self.csv.stop()
        elif cmd == "EXPORT":
            import threading
            threading.Thread(target=self._run_export, daemon=True).start()
        elif cmd == "SET_MODE":
            self.ui_set_mode(payload.get("mode", "tabletop"))
    
    def _run_export(self) -> None:
        """
        Background task to run export.
        """
        try:
            self.logger.info("Starting log export...")
            from viscologic.storage.exporter import perform_export
            log_dir = self._cfg_get("storage.csv_logger.folder", "logs")
            
            # Use publish("ui.notify") which MainWindowApp listens to
            msg = perform_export(log_dir)
            self.bus.publish("ui.notify", {"msg": msg, "type": "info"})
            self.logger.info("Export complete: %s", msg)
        except Exception as e:
            err_msg = f"Export failed: {str(e)}"
            self.logger.error(err_msg, exc_info=True)
            self.bus.publish("ui.notify", {"msg": err_msg, "type": "error"})

    def _handle_settings_updated(self, payload: Dict[str, Any]) -> None:
        """
        Handle settings updates from Engineer Screen.
        Applies settings to config and updates relevant subsystems.
        """
        if not isinstance(payload, dict):
            return
        
        try:
            # Update config dict if it's a dict
            if isinstance(self.config, dict):
                # Apply mode
                if "mode" in payload:
                    mode = str(payload["mode"]).lower()
                    if mode in ("tabletop", "inline"):
                        self.config.setdefault("app", {})["mode"] = mode
                        self.sm.set_mode(mode)
                
                # Apply control source
                if "control_source" in payload:
                    src = str(payload["control_source"]).lower()
                    if src in ("local", "remote", "mixed"):
                        self.config.setdefault("app", {})["control_source"] = src
                        self.ui_set_control_source(src)
                
                # Apply remote enable
                if "remote_enable" in payload:
                    self.config.setdefault("protocols", {})["remote_enable"] = bool(payload["remote_enable"])
                
                # Apply comm loss action
                if "comm_loss_action" in payload:
                    action = str(payload["comm_loss_action"]).lower()
                    if action in ("safe_stop", "hold_last", "pause"):
                        self.config.setdefault("protocols", {})["comm_loss_action"] = action
                        self.sm.set_comm_loss_action(action)
                
                # Apply inline auto resume
                if "inline_auto_resume" in payload:
                    self.config.setdefault("app", {})["inline_auto_resume"] = bool(payload["inline_auto_resume"])
                
                # Apply safety limits
                if "max_current_ma" in payload:
                    val = float(payload["max_current_ma"])
                    if 1 <= val <= 500:
                        self.config.setdefault("safety", {})["max_current_ma"] = val
                        # Update safety manager if it has a method to update limits
                        if hasattr(self.safety, "update_limits"):
                            self.safety.update_limits(max_current_ma=val)
                
                if "max_temp_c" in payload:
                    val = float(payload["max_temp_c"])
                    if 1 <= val <= 200:
                        self.config.setdefault("safety", {})["max_temp_c"] = val
                        if hasattr(self.safety, "update_limits"):
                            self.safety.update_limits(max_temp_c=val)
                
                # Apply DSP settings
                if "target_freq_hz" in payload:
                    val = float(payload["target_freq_hz"])
                    if 1 <= val <= 1000:
                        self.config.setdefault("dsp", {})["target_freq_hz"] = val
                
                if "sweep_span_hz" in payload:
                    val = float(payload["sweep_span_hz"])
                    if 0 < val <= 200:
                        self.config.setdefault("dsp", {})["sweep_span_hz"] = val
                
                if "sweep_step_hz" in payload:
                    val = float(payload["sweep_step_hz"])
                    if 0 < val <= 10:
                        self.config.setdefault("dsp", {})["sweep_step_hz"] = val
                
                if "lockin_tau_s" in payload:
                    val = float(payload["lockin_tau_s"])
                    if 0 < val <= 10:
                        self.config.setdefault("dsp", {})["lockin_tau_s"] = val
            
            # Also try ConfigManager set method if available
            if hasattr(self.config, "set") and callable(getattr(self.config, "set", None)):
                for key, value in payload.items():
                    try:
                        if key in ("mode", "control_source", "inline_auto_resume"):
                            self.config.set(f"app.{key}", value)  # type: ignore
                        elif key == "remote_enable":
                            self.config.set("protocols.remote_enable", value)  # type: ignore
                        elif key == "comm_loss_action":
                            self.config.set("protocols.comm_loss_action", value)  # type: ignore
                        elif key == "max_current_ma":
                            self.config.set("safety.max_current_ma", value)  # type: ignore
                        elif key == "max_temp_c":
                            self.config.set("safety.max_temp_c", value)  # type: ignore
                        elif key in ("target_freq_hz", "sweep_span_hz", "sweep_step_hz", "lockin_tau_s"):
                            self.config.set(f"dsp.{key}", value)  # type: ignore
                    except Exception:
                        pass
            
            self.logger.info("Settings updated from Engineer Screen")
        except Exception as e:
            self.logger.error(f"Failed to apply settings update: {e}")

    def _apply_auto_resume_policy(self) -> None:
        mode = str(self._cfg_get("app.mode", "tabletop"))
        if mode != "inline":
            return
        if not bool(self._cfg_get("app.inline_auto_resume", True)):
            return

        # Only if commissioned (best-effort)
        commissioned = False
        try:
            if hasattr(self.commissioning, "is_commissioned"):
                commissioned = bool(self.commissioning.is_commissioned())
        except Exception:
            commissioned = False
        if not commissioned:
            return

        # If last run was running, then auto start
        try:
            st = self._load_runtime_state()
            if st.get("running", False):
                self._last_cmd_source = "auto"
                self.sm.handle_event("START", {"source": "auto"})
        except Exception:
            pass

    def _load_runtime_state(self) -> Dict[str, Any]:
        if not os.path.exists(self._runtime_state_path):
            return {}
        with open(self._runtime_state_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _persist_runtime_state(self, running: bool) -> None:
        try:
            payload = {"running": bool(running), "ts": time.time()}
            with open(self._runtime_state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            pass

    def _run_loop(self) -> None:
        self.logger.info("Orchestrator thread running")

        tick_hz = float(self._cfg_get("app.sample_rate_hz", 200))
        tick_hz = max(10.0, min(2000.0, tick_hz))
        dt = 1.0 / tick_hz

        self._persist_runtime_state(running=(self.sm.state != SystemState.IDLE))

        next_t = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            if now < next_t:
                time.sleep(max(0.0, next_t - now))
                continue
            next_t += dt

            try:
                self._tick(dt)
            except Exception as e:
                self.logger.error("Tick error: %s", e, exc_info=True)
                try:
                    self.sm.handle_event("FAULT", {"reason": f"orchestrator_exception:{type(e).__name__}"})
                except Exception:
                    pass

    def _tick(self, dt: float) -> None:
        ts = time.time()

        mode = str(self._cfg_get("app.mode", "tabletop"))
        control_source = str(self._cfg_get("app.control_source", "mixed"))
        remote_enabled = bool(self._cfg_get("protocols.remote_enable", True))

        # 1) Read remote PLC commands (Modbus)
        if remote_enabled and control_source in ("remote", "mixed"):
            self._poll_modbus_commands()

        # 2) Read temperature
        temp_c, temp_fault = self._read_temperature()

        # 3) Read ADC (pickup)
        adc_val = self._read_adc()

        # 4) State machine tick (so transitions progress)
        self.sm.tick({"dt": dt, "ts": ts})

        # 5) Drive / sweep / lock-in
        freq_hz, duty = self._compute_drive_setpoints()

        # Apply drive
        self._apply_drive(freq_hz=freq_hz, duty=duty)

        # DSP updates
        lock_state = self.lockin.update(adc_val)
        mag = float(lock_state.get("magnitude", 0.0))
        ph = float(lock_state.get("phase_deg", 0.0))

        # Sweep handling when in SWEEPING
        if self.sm.state == SystemState.SWEEPING:
            try:
                self.sweep.submit_point(freq_hz=freq_hz, magnitude=mag)
                if self.sweep.is_complete():
                    best = self.sweep.best_freq_hz()
                    if best is not None:
                        self.lockin.set_ref_freq(float(best))
                        self.sm.handle_event("SWEEP_DONE", {"best_freq_hz": float(best)})
            except Exception:
                pass

        locked = bool(self._infer_locked())
        fault = bool(temp_fault) or bool(self._infer_fault())

        # 6) Safety check (best-effort)
        fault_reason = ""
        try:
            ok, reason = self._check_safety(temp_c=temp_c, duty=duty)
            if not ok:
                fault = True
                fault_reason = reason or "safety_trip"
        except Exception:
            pass

        if fault:
            self.sm.handle_event("FAULT", {"reason": fault_reason or "fault"})
        elif self.sm.state == SystemState.LOCKING:
            # Check if DSP is valid/ready
            if lock_state.get("locked"):
                self.sm.handle_event("LOCK_OK", {"mag": mag})
        elif locked:
            # Already locked/running, verify we haven't lost lock (optional logic could go here)
            pass

        # 7) Compute confidence / viscosity
        confidence = float(self._compute_confidence(mag=mag, phase_deg=ph, adc_val=adc_val, locked=locked))
        viscosity_cp = float(self._compute_viscosity(mag=mag, temp_c=temp_c))

        # 8) Diagnostics update
        try:
            self.diag.update(
                {
                    "ts": ts,
                    "state": str(self.sm.state.name),
                    "mode": mode,
                    "freq_hz": freq_hz,
                    "duty": duty,
                    "adc_raw": adc_val,
                    "magnitude": mag,
                    "phase_deg": ph,
                    "viscosity_cp": viscosity_cp,
                    "temp_c": temp_c,
                    "confidence": confidence,
                    "locked": locked,
                    "fault": fault,
                }
            )
        except Exception:
            pass

        # 9) Publish to Modbus registers
        try:
            self._publish_modbus(
                viscosity_cp=viscosity_cp,
                temp_c=temp_c,
                freq_hz=freq_hz,
                mag=mag,
                confidence=confidence,
                locked=locked,
                fault=fault,
                remote_enabled=remote_enabled,
            )
        except Exception:
            pass

        # 10) Logging (best-effort)
        self._log(ts, mode, viscosity_cp, temp_c, freq_hz, duty, mag, ph, confidence, locked, fault)

        # 11) Snapshot for UI
        with self._snapshot_lock:
            self._snapshot = RuntimeSnapshot(
                ts=ts,
                state=str(self.sm.state.name),
                mode=mode,
                control_source=control_source,
                freq_hz=float(freq_hz),
                duty=float(duty),
                adc_raw=float(adc_val),
                magnitude=float(mag),
                phase_deg=float(ph),
                viscosity_cp=float(viscosity_cp),
                temp_c=float(temp_c),
                confidence=float(confidence),
                health_ok=bool(confidence >= float(self._cfg_get("health.min_confidence_ok", 60.0))),
                locked=bool(locked),
                fault=bool(self.sm.state == SystemState.FAULT or fault),
                alarm_active=bool(self.sm.state == SystemState.FAULT),
                alarms=self.safety.alarms() if hasattr(self.safety, "alarms") else {},
                last_fault_reason=str(fault_reason),
                remote_enabled=bool(remote_enabled),
                last_cmd_source=str(self._last_cmd_source),
                active_profile=str(self._cfg_get("calibration.active_profile", "Default")),
            )
        # print(
        # "[DEBUG FAULT]",
        # "state=", self._snapshot.state,
        # "fault=", self._snapshot.fault,
        # "temp=", self._snapshot.temp_c,
        # "duty=", self._snapshot.duty,
        # "reason=", self._snapshot.last_fault_reason)

        # Publish frame on bus (best-effort)
        try:
            snap = asdict(self._snapshot)
            snap["confidence_pct"] = int(confidence)
            snap["health_score"] = int(100 if snap.get("health_ok") else confidence)
            snap["running"] = self.sm.state in (SystemState.SWEEPING, SystemState.LOCKING, SystemState.RUNNING)
            snap["fault_latched"] = self.safety.fault_latched() if hasattr(self.safety, "fault_latched") else False
            snap["alarm_acknowledged"] = self.safety.is_acknowledged() if hasattr(self.safety, "is_acknowledged") else False
            snap["logging"] = self.csv.is_enabled() if hasattr(self.csv, "is_enabled") else False

            # print("[DEBUG ORCH FRAME]",
            #     "temp=", snap.get("temp_c"),
            #     "visc=", snap.get("viscosity_cp"),
            #     "freq=", snap.get("freq_hz"))


            # Try specific method first
            if hasattr(self.bus, "publish_frame"):
                self.bus.publish_frame(snap)
            # Fallback to general publish
            elif hasattr(self.bus, "publish"):
                self.bus.publish("frame", snap)
                self.bus.publish("ui.frame", snap)
        except Exception:
            pass

        # Persist running state for auto-resume
        self._persist_runtime_state(running=(self.sm.state != SystemState.IDLE))

        # Retention maintenance occasionally
        self._maybe_run_retention(ts)

    # ------------------------
    # Low-level helpers
    # ------------------------
    def _poll_modbus_commands(self) -> None:
        addr = self.regmap.layout().get("CONTROL_WORD", None)
        if addr is None: return

        cw = None
        try:
            if hasattr(self.modbus, "get_holding_register"):
                cw = int(self.modbus.get_holding_register(addr))
            elif hasattr(self.modbus, "read_holding_register"):
                cw = int(self.modbus.read_holding_register(addr))
        except Exception:
            cw = None

        if cw is None: return

        decoded = self.regmap.decode_control_word(int(cw))
        prev = int(self._last_control_word)
        prev_dec = self.regmap.decode_control_word(prev)

        edge_start = bool(decoded.get("start")) and not bool(prev_dec.get("start"))
        edge_stop = bool(decoded.get("stop")) and not bool(prev_dec.get("stop"))
        edge_ack = bool(decoded.get("ack")) and not bool(prev_dec.get("ack"))
        edge_reset = bool(decoded.get("reset")) and not bool(prev_dec.get("reset"))

        remote_start_edge = bool(self._cfg_get("plc.remote_start_edge", True))
        remote_stop_edge = bool(self._cfg_get("plc.remote_stop_edge", True))

        if decoded.get("start") and (edge_start or not remote_start_edge):
            self._last_cmd_source = "remote"
            self.sm.handle_event("START", {"source": "remote"})
        if decoded.get("stop") and (edge_stop or not remote_stop_edge):
            self._last_cmd_source = "remote"
            self.sm.handle_event("STOP", {"source": "remote"})
        if decoded.get("ack") and (edge_ack or True):
            self._last_cmd_source = "remote"
            self.sm.handle_event("ALARM_ACK", {"source": "remote"})
        if decoded.get("reset") and (edge_reset or True):
            self._last_cmd_source = "remote"
            self.sm.handle_event("ALARM_RESET", {"source": "remote"})

        self._last_control_word = int(cw)

    def _read_temperature(self) -> Tuple[float, bool]:
        temp_c = 0.0
        fault = False
        try:
            if hasattr(self.temp, "read_temp_c"):
                temp_c = float(self.temp.read_temp_c())
            elif hasattr(self.temp, "read"):
                # fallback for older driver interface
                out = self.temp.read()
                if isinstance(out, dict):
                    temp_c = float(out.get("temp_c", 0.0))
                    fault = bool(out.get("fault", False))
                else:
                    temp_c = float(out)
        except Exception:
            fault = True
        return temp_c, fault

    # def _read_adc(self) -> float:
    #     try:
    #         if hasattr(self.adc, "read_sample_volts"):
    #             return float(self.adc.read_sample_volts())
    #         if hasattr(self.adc, "read"):
    #             return float(self.adc.read())
    #     except Exception:
    #         return 0.0
    #     return 0.0
    def _read_adc(self) -> float:
        try:
            if hasattr(self.adc, "read_sample_volts"):
                return float(self.adc.read_sample_volts())
            if hasattr(self.adc, "read"):
                return float(self.adc.read())
        except Exception:
            pass
        
        # Fallback/Mock: random noise if driver fails (for desktop testing)
        if os.environ.get("MOCK_MODE", "1") == "1":
            import random
            return 0.5 + random.uniform(-0.01, 0.01)
            
        return 0.0

    def _compute_drive_setpoints(self) -> Tuple[float, float]:
        # Default: fixed freq, duty per state
        freq = float(getattr(self.lockin, "ref_freq_hz", self._target_freq_hz))

        # If sweeping, set freq from sweep tracker
        if self.sm.state == SystemState.SWEEPING:
            try:
                if hasattr(self.sweep, "get_current_freq"):
                    freq = float(self.sweep.get_current_freq())
                elif hasattr(self.sweep, "current_freq"):
                    freq = float(self.sweep.current_freq)
            except Exception:
                pass

        # Duty policy
        start_duty = float(self._cfg_get("drivers.drive_pwm.start_duty", 0.15))
        duty = start_duty

        if self.sm.state in (SystemState.IDLE, SystemState.STOPPING, SystemState.FAULT):
            duty = 0.0
        elif self.sm.state in (SystemState.SWEEPING, SystemState.LOCKING, SystemState.RUNNING):
            duty = float(self.drive.get_duty() if hasattr(self.drive, "get_duty") else start_duty)

        # Clamp by safety max drive duty
        max_drive = float(self._cfg_get("safety.max_drive_duty", 0.85))
        duty = max(0.0, min(float(duty), float(max_drive)))

        return freq, duty

    def _apply_drive(self, freq_hz: float, duty: float) -> None:
        try:
            if hasattr(self.drive, "set_frequency"):
                self.drive.set_frequency(float(freq_hz))
        except Exception:
            pass

        try:
            if hasattr(self.drive, "set_duty"):
                self.drive.set_duty(float(duty))
            elif hasattr(self.drive, "set_amplitude"):
                self.drive.set_amplitude(float(duty))
        except Exception:
            pass

    def _infer_locked(self) -> bool:
        try:
            if hasattr(self.sm, "is_locked"):
                return bool(self.sm.is_locked())
        except Exception:
            pass
        return self.sm.state == SystemState.RUNNING

    def _infer_fault(self) -> bool:
        return self.sm.state == SystemState.FAULT

    def _check_safety(self, temp_c: float, duty: float) -> Tuple[bool, str]:
        try:
            if hasattr(self.safety, "evaluate"):
                # SafetyManager.evaluate returns SafetyDecision.
                # We pass 0 for requested current as we use duty cycle control here.
                decision = self.safety.evaluate(
                    requested_current_ma=0,
                    temp_c=temp_c,
                    adc_ok=True,
                    temp_ok=(temp_c is not None)
                )
                return bool(decision.allow_drive), str(decision.reason)
        except Exception:
            pass

        # Minimal local checks
        if temp_c >= float(self._cfg_get("safety.max_temp_c", 80.0)):
            return False, "overtemp"
        if duty > float(self._cfg_get("safety.max_drive_duty", 0.85)):
            return False, "overduty"
        return True, ""

    def _compute_confidence(self, mag: float, phase_deg: float, adc_val: float, locked: bool) -> float:
        try:
            if hasattr(self.health, "compute"):
                # Prepare inputs for HealthScorer
                frame_input = {
                    "confidence_pct": int(100 if mag > 0.001 else 0),
                    "locked": bool(locked),
                    "adc_ok": True,
                    "temp_ok": True,
                    "fault_latched": bool(self.sm.state == SystemState.FAULT),
                    "alarms": {}
                }
                
                result = self.health.compute(frame_input)
                if hasattr(result, "score"):
                    return float(result.score)
                elif isinstance(result, (int, float)):
                    return float(result)

        except Exception:
            pass

        # fallback simple score
        base = 80.0 if locked else 40.0
        if mag <= 0.0001:
            base -= 30.0
        return max(0.0, min(100.0, base))

    def _compute_viscosity(self, mag: float, temp_c: float) -> float:
        # --- DEV MOCK: show fake viscosity for UI sanity ---
        try:
            # DEV MOCK: Default to enabled ("1") for desktop testing if no sensors
            if os.environ.get("MOCK_MODE", "1") == "1":
                # Generate fake viscosity based on mag (assuming mag is simulated)
                # If mag is 0 (no ADC), generate a sine wave for visual feedback
                if mag < 0.0001:
                    return float(abs(math.sin(time.time()) * 100.0) + 50.0)
                return max(0.0, 1000.0 * mag)
        except Exception:
            pass


        mode = str(self._cfg_get("app.mode", "tabletop"))
        profile_name = str(self._cfg_get("calibration.active_profile", "Default"))

        profile_id = None
        try:
            if hasattr(self.cal_store, "get_active_set_id"):
                profile_id = self.cal_store.get_active_set_id(mode, profile_name)
        except Exception:
            pass

        try:
            if hasattr(self.visc_compute, "compute"):
                res = self.visc_compute.compute(
                    feature_or_frame=float(mag),
                    temp_c=float(temp_c),
                    profile_id=profile_id,
                    profile_name=profile_name
                )
                if res.ok:
                    return float(res.viscosity_cp_display)
        except Exception:
            pass

        return 0.0

    def _publish_modbus(
        self,
        viscosity_cp: float,
        temp_c: float,
        freq_hz: float,
        mag: float,
        confidence: float,
        locked: bool,
        fault: bool,
        remote_enabled: bool,
    ) -> None:
        layout = self.regmap.layout()

        status_word = self.regmap.encode_status_word(
            {
                "running": self.sm.state in (SystemState.SWEEPING, SystemState.LOCKING, SystemState.RUNNING),
                "locked": bool(locked),
                "fault": bool(fault),
                "alarm_active": bool(fault),
                "remote_enabled": bool(remote_enabled),
            }
        )

        def wr(name: str, value: int) -> None:
            addr = layout.get(name)
            if addr is None: return
            if hasattr(self.modbus, "set_holding_register"):
                self.modbus.set_holding_register(addr, int(value))
            elif hasattr(self.modbus, "write_holding_register"):
                self.modbus.write_holding_register(addr, int(value))

        def wr_f32(prefix: str, val: float) -> None:
            hi_name = f"{prefix}_F32_HI"
            lo_name = f"{prefix}_F32_LO"
            hi, lo = self.regmap.f32_to_u16pair(float(val))
            wr(hi_name, hi)
            wr(lo_name, lo)

        wr("STATUS_WORD", int(status_word))
        wr_f32("VISCOSITY", float(viscosity_cp))
        wr_f32("TEMP_C", float(temp_c))
        wr_f32("FREQ_HZ", float(freq_hz))
        wr_f32("MAG", float(mag))
        wr_f32("CONFIDENCE", float(confidence))

    def _log(
        self,
        ts: float,
        mode: str,
        viscosity_cp: float,
        temp_c: float,
        freq_hz: float,
        duty: float,
        mag: float,
        ph: float,
        confidence: float,
        locked: bool,
        fault: bool,
    ) -> None:
        # Build status word from state
        status_word = 0
        if self.sm.state in (SystemState.SWEEPING, SystemState.LOCKING, SystemState.RUNNING):
            status_word |= (1 << 2)  # STATUS_SWEEPING
        if locked:
            status_word |= (1 << 4)  # STATUS_LOCKED
        if fault or self.sm.state == SystemState.FAULT:
            status_word |= (1 << 6)  # STATUS_FAULT_LATCHED
        if self.sm.state == SystemState.PAUSED:
            status_word |= (1 << 5)  # STATUS_PAUSED
        
        # Build alarm word from fault state
        alarm_word = 0
        if fault:
            alarm_word |= (1 << 5)  # ALARM_LOST_LOCK (or other appropriate alarm)
        
        # Convert timestamp to milliseconds
        timestamp_ms = int(ts * 1000)
        
        # Build frame for CSV logger (matches expected format)
        frame = {
            "timestamp_ms": timestamp_ms,
            "viscosity_cp": float(viscosity_cp),
            "temp_c": float(temp_c),
            "freq_hz": float(freq_hz),
            "health_pct": int(confidence),
            "status_word": status_word,
            "alarm_word": alarm_word,
            # Extra fields stored in extra_json
            "mode": mode,
            "state": str(self.sm.state.name),
            "duty": float(duty),
            "magnitude": float(mag),
            "phase_deg": float(ph),
            "confidence": float(confidence),
            "locked": int(bool(locked)),
            "fault": int(bool(fault)),
        }

        # CSV logging
        try:
            if bool(self._cfg_get("storage.csv_logger.enabled", True)):
                if hasattr(self.csv, "log_frame"):
                    self.csv.log_frame(frame)
        except Exception:
            pass

        # SQLite event logging (optional - log as event)
        try:
            if bool(self._cfg_get("storage.sqlite.enabled", True)):
                if hasattr(self.sqlite, "log_event"):
                    # Log measurement as event (optional, to avoid too many events)
                    # Only log significant state changes or periodic samples
                    self.sqlite.log_event("measurement", {
                        "timestamp_ms": timestamp_ms,
                        "viscosity_cp": viscosity_cp,
                        "temp_c": temp_c,
                        "freq_hz": freq_hz,
                        "mode": mode,
                        "state": str(self.sm.state.name),
                    })
        except Exception:
            pass

    def _maybe_run_retention(self, ts: float) -> None:
        try:
            last = getattr(self, "_ret_last_ts", 0.0)
            if ts - float(last) < 600.0:  # Run every 10 minutes
                return
            setattr(self, "_ret_last_ts", float(ts))
            
            # Cleanup CSV files
            csv_dir = str(self._cfg_get("storage.csv_logger.folder", "logs"))
            if csv_dir and os.path.isdir(csv_dir):
                try:
                    report = self.retention.cleanup_folder(
                        csv_dir,
                        self._ret_csv_days,
                        allowed_ext=[".csv"]
                    )
                    if report.deleted_files > 0:
                        self.logger.info("Retention: deleted %d CSV files from %s", report.deleted_files, csv_dir)
                except Exception:
                    pass
            
            # Note: Database retention would require custom logic
            # (e.g., DELETE FROM events WHERE ts_ms < cutoff)
            # Not implemented in RetentionManager as it's file-based
        except Exception:
            pass

