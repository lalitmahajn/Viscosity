# viscologic/app.py
# Predictron ViscoLogic - Main Entrypoint (Auto-start friendly, safe shutdown)
# NOTE: This file intentionally supports "safe fallbacks" until all modules are added.

from __future__ import annotations

import os
import sys
import time
import json
import signal
import logging
import traceback
from dataclasses import dataclass
from typing import Optional, Any, Dict

# -----------------------------
# Helpers
# -----------------------------

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _now_ms() -> int:
    return int(time.time() * 1000)

def _safe_import(module_path: str, attr: str | None = None):
    """
    Safe import so app can run even before all files are pasted.
    Once you paste the real modules, imports will automatically use them.
    """
    try:
        mod = __import__(module_path, fromlist=[attr] if attr else [])
        return getattr(mod, attr) if attr else mod
    except Exception:
        # --- DEBUG: Print the error so we can see it ---
        print(f"\n[DEBUG] !!! Failed to import {module_path} !!!")
        import traceback
        traceback.print_exc()
        print("-" * 60 + "\n")
        # -----------------------------------------------
        return None

def _setup_logging(log_dir: str, level: str = "INFO") -> logging.Logger:
    _ensure_dir(log_dir)

    logger = logging.getLogger("viscologic")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File
    fh_path = os.path.join(log_dir, "viscologic.log")
    fh = logging.FileHandler(fh_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.info("Logging initialized. log_file=%s", fh_path)
    return logger

# -----------------------------
# Default Config (fallback)
# -----------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "app": {
        "name": "Predictron ViscoLogic",
        "version": "vFinal",
        "ui_enabled": True,
        "tick_ms": 100,  # main loop tick for fallback
    },
    "mode": {
        "default_mode": "tabletop",  # tabletop | inline
        "default_control_source": "local",  # local | remote | mixed
        "remote_enable": False,
        "auto_resume_inline": True,
        "comm_loss_action": "pause",  # pause | keep_running
    },
    "safety": {
        "max_current_ma": 150,
        "air_cal_current_ma": 50,
        "air_cal_max_sec": 15,
        "soft_start_ramp_ms": 800,
    },
    "sweep": {
        "f_min": 150.0,
        "f_max": 200.0,
        "coarse_step": 1.0,
        "fine_step": 0.1,
    },
    "logging": {
        "csv_enabled": True,
        "csv_dir": "logs/csv",
        "retention_days": 30,
    },
    "modbus": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 5020,  # use 5020 for dev; 502 requires root on Linux
        "unit_id": 1,
        "mapping_version": 1,
    },
    "storage": {
        "sqlite_path": "data/viscologic.db",
    },
    "security": {
        "commissioning_required_on_first_run": True,
    }
}

# -----------------------------
# Minimal fallback components
# (real components will replace these when files are pasted)
# -----------------------------

class _FallbackEventBus:
    def __init__(self):
        self.latest_frame = {
            "timestamp_ms": _now_ms(),
            "viscosity_cp": 0.0,
            "temp_c": 25.0,
            "freq_hz": 0.0,
            "health_pct": 0,
            "status_word": 0,
            "alarm_word": 0,
        }
        self._stop = False

    def publish_frame(self, frame: Dict[str, Any]) -> None:
        self.latest_frame = frame

    def stop(self) -> None:
        self._stop = True

class _FallbackOrchestrator:
    def __init__(self, config: Dict[str, Any], bus: Any, logger: logging.Logger):
        self.config = config
        self.bus = bus
        self.logger = logger
        self._running = False

    def start(self) -> None:
        self._running = True
        self.logger.info("Orchestrator started (fallback).")

    def stop(self) -> None:
        self._running = False
        self.logger.info("Orchestrator stopped (fallback).")

    def tick(self) -> None:
        # Generates dummy data so UI/PLC can show something.
        if not self._running:
            return
        t = _now_ms()
        frame = {
            "timestamp_ms": t,
            "viscosity_cp": 0.0,
            "temp_c": 25.0,
            "freq_hz": 180.0,
            "health_pct": 10,
            "status_word": 0,
            "alarm_word": 0,
        }
        self.bus.publish_frame(frame)

class _FallbackModbusServer:
    def __init__(self, config: Dict[str, Any], bus: Any, logger: logging.Logger):
        self.config = config
        self.bus = bus
        self.logger = logger
        self._running = False

    def start(self) -> None:
        # Real modbus will be implemented later in protocols/modbus_server.py
        self._running = True
        self.logger.info("Modbus server started (fallback: no actual TCP listening).")

    def stop(self) -> None:
        self._running = False
        self.logger.info("Modbus server stopped (fallback).")

class _FallbackUI:
    def __init__(self, config: Dict[str, Any], bus: Any, logger: logging.Logger):
        self.config = config
        self.bus = bus
        self.logger = logger

    def run(self) -> int:
        # Console UI fallback (PyQt will come later)
        global _SHUTDOWN
        self.logger.info("UI started (fallback console mode). Press Ctrl+C to exit.")
        try:
            while not _SHUTDOWN:
                f = getattr(self.bus, "latest_frame", {})
                sys.stdout.write(
                    f"\rVisc={f.get('viscosity_cp',0):8.2f} cP | "
                    f"T={f.get('temp_c',0):6.2f} C | "
                    f"F={f.get('freq_hz',0):7.2f} Hz | "
                    f"Health={f.get('health_pct',0):3d}%"
                )
                sys.stdout.flush()
                time.sleep(0.5)
            return 0
        except KeyboardInterrupt:
            return 0

# -----------------------------
# App Context
# -----------------------------

@dataclass
class AppContext:
    config: Dict[str, Any]
    logger: logging.Logger
    bus: Any
    orchestrator: Any
    modbus: Any
    ui: Any

# -----------------------------
# Config load (will be replaced later by core/config_manager.py)
# -----------------------------

def load_config(logger: logging.Logger) -> Dict[str, Any]:
    """
    Priority:
      1) config/settings.yaml via future config_manager
      2) fallback DEFAULT_CONFIG
    """
    ConfigManager = _safe_import("viscologic.core.config_manager", "ConfigManager")
    if ConfigManager is not None:
        try:
            mgr = ConfigManager()
            cfg = mgr.load()
            logger.info("Config loaded via ConfigManager.")
            return cfg
        except Exception as e:
            logger.error("ConfigManager failed, using DEFAULT_CONFIG. err=%s", e)

    # fallback
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    logger.warning("Using DEFAULT_CONFIG (fallback). Paste core/config_manager.py to enable YAML/schema.")
    return cfg

# -----------------------------
# Build components
# -----------------------------

def build_context() -> AppContext:
    # Paths
    base_dir = os.getcwd()
    data_dir = os.path.join(base_dir, "data")
    log_dir = os.path.join(base_dir, "logs")
    _ensure_dir(data_dir)
    _ensure_dir(log_dir)

    logger = _setup_logging(log_dir=log_dir, level=os.environ.get("VISC_LOG_LEVEL", "INFO"))

    cfg = load_config(logger)

    # EventBus
    EventBus = _safe_import("viscologic.core.event_bus", "EventBus")
    bus = EventBus(logger=logger) if EventBus is not None else _FallbackEventBus()

    # Storage init (optional, later)
    SqliteStore = _safe_import("viscologic.storage.sqlite_store", "SqliteStore")
    if SqliteStore is not None:
        try:
            store = SqliteStore(cfg["storage"]["sqlite_path"], logger=logger)
            store.init_db()
            logger.info("SQLite store ready: %s", cfg["storage"]["sqlite_path"])
        except Exception as e:
            logger.error("SQLite init failed (continuing). err=%s", e)

    # Orchestrator
    Orchestrator = _safe_import("viscologic.core.orchestrator", "Orchestrator")
    orchestrator = Orchestrator(config=cfg, bus=bus, logger=logger) if Orchestrator is not None else _FallbackOrchestrator(cfg, bus, logger)

    # Modbus
    ModbusServer = _safe_import("viscologic.protocols.modbus_server", "ModbusServer")
    if cfg.get("modbus", {}).get("enabled", True):
        modbus = ModbusServer(config=cfg, bus=bus, logger=logger) if ModbusServer is not None else _FallbackModbusServer(cfg, bus, logger)
    else:
        modbus = _FallbackModbusServer(cfg, bus, logger)  # does nothing

    # UI
    ui_enabled = cfg.get("app", {}).get("ui_enabled", True)
    if ui_enabled:
        # Try PyQt UI later, else fallback console UI
        MainWindowApp = _safe_import("viscologic.ui.main_window", "MainWindowApp")
        if MainWindowApp is not None:
            try:
                ui = MainWindowApp(config=cfg, bus=bus, logger=logger)
            except Exception as e:
                logger.error("MainWindowApp initialization failed: %s", e)
                import traceback
                traceback.print_exc()
                ui = _FallbackUI(cfg, bus, logger)
        else:
            ui = _FallbackUI(cfg, bus, logger)
    else:
        ui = None

    return AppContext(
        config=cfg,
        logger=logger,
        bus=bus,
        orchestrator=orchestrator,
        modbus=modbus,
        ui=ui
    )

# -----------------------------
# Graceful shutdown
# -----------------------------

_SHUTDOWN = False

def _handle_signal(sig, frame):
    global _SHUTDOWN
    _SHUTDOWN = True

def safe_shutdown(ctx: AppContext) -> None:
    ctx.logger.info("Shutting down safely...")
    try:
        # Stop modbus first (no new commands)
        if ctx.modbus:
            ctx.modbus.stop()
    except Exception:
        ctx.logger.error("Error stopping modbus:\n%s", traceback.format_exc())

    try:
        # Stop orchestrator (must turn drive OFF internally in real implementation)
        if ctx.orchestrator:
            ctx.orchestrator.stop()
    except Exception:
        ctx.logger.error("Error stopping orchestrator:\n%s", traceback.format_exc())

    try:
        if ctx.bus and hasattr(ctx.bus, "stop"):
            ctx.bus.stop()
    except Exception:
        ctx.logger.error("Error stopping bus:\n%s", traceback.format_exc())

    ctx.logger.info("Shutdown complete.")

# -----------------------------
# Main
# -----------------------------

def main() -> int:
    global _SHUTDOWN

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    ctx = build_context()
    log = ctx.logger

    try:
        log.info("Starting %s (%s)", ctx.config["app"]["name"], ctx.config["app"]["version"])

        # Start core services
        ctx.orchestrator.start()
        if ctx.modbus:
            ctx.modbus.start()

        # If UI exists, run UI loop (blocking)
        if ctx.ui is not None:
            rc = ctx.ui.run()
            _SHUTDOWN = True
            return int(rc or 0)

        # No UI: run headless loop
        tick_ms = int(ctx.config.get("app", {}).get("tick_ms", 100))
        log.info("Running headless loop. tick_ms=%d", tick_ms)
        while not _SHUTDOWN:
            # Orchestrator tick for fallback; real orchestrator may be threaded
            if hasattr(ctx.orchestrator, "tick"):
                ctx.orchestrator.tick()
            time.sleep(max(0.01, tick_ms / 1000.0))

        return 0

    except Exception:
        log.error("Fatal error:\n%s", traceback.format_exc())
        return 2
    finally:
        safe_shutdown(ctx)

if __name__ == "__main__":
    raise SystemExit(main())
