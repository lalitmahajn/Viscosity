# viscologic/core/config_manager.py
# ConfigManager: loads config/settings.yaml + validates with config/schema.json (best-effort)
# Safe defaults + merge + basic guards (even if jsonschema not installed)

from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, Optional

# -----------------------------
# Default Config (kept in sync with app.py fallback)
# -----------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "app": {
        "name": "Predictron ViscoLogic",
        "version": "vFinal",
        "ui_enabled": True,
        "tick_ms": 100,
    },
    "mode": {
        "default_mode": "tabletop",         # tabletop | inline
        "default_control_source": "local",  # local | remote | mixed
        "remote_enable": False,
        "auto_resume_inline": True,
        "comm_loss_action": "pause",        # pause | keep_running
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
        "port": 5020,         # 502 requires root, 5020 safe default for dev
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


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merges override into base (override wins)."""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_yaml(path: str) -> Dict[str, Any]:
    """
    Loads YAML using PyYAML if available.
    If not installed, raises ImportError so caller can handle.
    """
    import yaml  # type: ignore
    txt = _read_text(path)
    data = yaml.safe_load(txt) or {}
    if not isinstance(data, dict):
        raise ValueError("settings.yaml must be a mapping (dict) at root.")
    return data


def _load_json(path: str) -> Dict[str, Any]:
    txt = _read_text(path)
    data = json.loads(txt or "{}")
    if not isinstance(data, dict):
        raise ValueError("schema.json must be a JSON object.")
    return data


class ConfigManager:
    """
    Loads configuration from config/settings.yaml and validates with config/schema.json.
    Env overrides:
      - VISC_CONFIG_PATH: full path to settings.yaml
      - VISC_SCHEMA_PATH: full path to schema.json
    """

    def __init__(self, base_dir: Optional[str] = None, logger: Optional[logging.Logger] = None):
        self.base_dir = base_dir or os.getcwd()
        self.logger = logger or logging.getLogger("viscologic.config")

        self.config_dir = os.path.join(self.base_dir, "viscologic", "config")
        self.default_settings_path = os.path.join(self.config_dir, "settings.yaml")
        #print(self.default_settings_path)
        self.default_schema_path = os.path.join(self.config_dir, "schema.json")
        #print(self.default_schema_path)
        self.settings_path = os.environ.get("VISC_CONFIG_PATH", self.default_settings_path)
        self.schema_path = os.environ.get("VISC_SCHEMA_PATH", self.default_schema_path)
        
        # Store the loaded config dict for get/set operations
        self._config_dict: Optional[Dict[str, Any]] = None

    def load(self) -> Dict[str, Any]:
        """
        Returns merged config dict (DEFAULT_CONFIG + yaml overrides).
        Validation is best-effort (jsonschema if installed, otherwise basic guards).
        """
        cfg = dict(DEFAULT_CONFIG)

        # 1) Load YAML if exists
        if os.path.exists(self.settings_path):
            try:
                user_cfg = _load_yaml(self.settings_path)
                cfg = _deep_merge(cfg, user_cfg)
                self.logger.info("Loaded settings.yaml: %s", self.settings_path)
            except ImportError:
                self.logger.warning("PyYAML not installed. Using defaults. Install: pip install pyyaml")
            except Exception as e:
                self.logger.error("Failed to read settings.yaml, using defaults. err=%s", e)
        else:
            self.logger.warning("settings.yaml not found at %s (using defaults).", self.settings_path)

        # 2) Validate
        self._validate(cfg)

        # 3) Apply hard guards (never allow unsafe config)
        self._apply_hard_guards(cfg)

        # Store for get/set operations
        self._config_dict = cfg
        return cfg
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a config value using dot-notation key (e.g., "app.mode").
        Returns default if key not found.
        """
        if self._config_dict is None:
            self._config_dict = self.load()
        
        keys = key.split(".")
        value = self._config_dict
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value: Any) -> None:
        """
        Set a config value using dot-notation key (e.g., "app.mode").
        Creates nested dicts as needed.
        """
        if self._config_dict is None:
            self._config_dict = self.load()
        
        keys = key.split(".")
        target = self._config_dict
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
    
    def save(self) -> bool:
        """
        Save current config dict to settings.yaml.
        Returns True if successful, False otherwise.
        """
        if self._config_dict is None:
            self.logger.warning("No config loaded to save.")
            return False
        
        try:
            import yaml  # type: ignore
        except ImportError:
            self.logger.error("PyYAML not installed. Cannot save settings. Install: pip install pyyaml")
            return False
        
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
            
            # Write YAML file
            with open(self.settings_path, "w", encoding="utf-8") as f:
                yaml.dump(self._config_dict, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            
            self.logger.info("Settings saved to: %s", self.settings_path)
            return True
        except Exception as e:
            self.logger.error("Failed to save settings.yaml: %s", e)
            return False
    
    def persist(self) -> bool:
        """Alias for save() for compatibility."""
        return self.save()
    
    def flush(self) -> bool:
        """Alias for save() for compatibility."""
        return self.save()
    
    def write(self) -> bool:
        """Alias for save() for compatibility."""
        return self.save()

    def _validate(self, cfg: Dict[str, Any]) -> None:
        """
        Validate config via jsonschema when available.
        If schema missing or jsonschema not installed, fallback to basic validation.
        """
        # Always run basic validation/normalization first
        self._basic_validate(cfg)

        if os.path.exists(self.schema_path):
            try:
                schema = _load_json(self.schema_path)
            except Exception as e:
                self.logger.warning("schema.json read failed (%s). Skipping schema validation.", e)
                return

            try:
                import jsonschema  # type: ignore
                jsonschema.validate(instance=cfg, schema=schema)
                self.logger.info("Config validated via jsonschema: %s", self.schema_path)
                return
            except ImportError:
                self.logger.warning("jsonschema not installed. Skipping schema validation. Install: pip install jsonschema")
            except Exception as e:
                # Do not crash; log and fallback to basic checks
                self.logger.error("Schema validation failed: %s", e)

        else:
            self.logger.warning("schema.json not found at %s (basic validation only).", self.schema_path)

    def _basic_validate(self, cfg: Dict[str, Any]) -> None:
        """
        Minimal validation so system remains safe even without jsonschema.
        """
        # Enumerations
        mode = cfg.get("mode", {}).get("default_mode", "tabletop")
        if mode not in ("tabletop", "inline"):
            self.logger.warning("Invalid default_mode=%s; forcing tabletop", mode)
            cfg["mode"]["default_mode"] = "tabletop"

        cs = cfg.get("mode", {}).get("default_control_source", "local")
        if cs not in ("local", "remote", "mixed"):
            self.logger.warning("Invalid default_control_source=%s; forcing local", cs)
            cfg["mode"]["default_control_source"] = "local"

        comm_loss = cfg.get("mode", {}).get("comm_loss_action", "pause")
        if comm_loss not in ("pause", "keep_running"):
            self.logger.warning("Invalid comm_loss_action=%s; forcing pause", comm_loss)
            cfg["mode"]["comm_loss_action"] = "pause"

        # Numeric sanity
        try:
            cfg["safety"]["max_current_ma"] = int(cfg["safety"].get("max_current_ma", 150))
        except Exception:
            cfg["safety"]["max_current_ma"] = 150

        try:
            cfg["modbus"]["port"] = int(cfg["modbus"].get("port", 5020))
        except Exception:
            cfg["modbus"]["port"] = 5020

    def _apply_hard_guards(self, cfg: Dict[str, Any]) -> None:
        """
        Absolute guards to never allow unsafe values.
        """
        # Safety: max current cap
        max_ma = int(cfg.get("safety", {}).get("max_current_ma", 150))
        if max_ma > 150:
            self.logger.warning("max_current_ma=%d exceeds 150. Forcing to 150.", max_ma)
            cfg["safety"]["max_current_ma"] = 150
        if max_ma < 1:
            self.logger.warning("max_current_ma=%d invalid. Forcing to 150.", max_ma)
            cfg["safety"]["max_current_ma"] = 150

        # Air calibration caps (keep conservative)
        air_ma = int(cfg.get("safety", {}).get("air_cal_current_ma", 50))
        if air_ma > 80:
            self.logger.warning("air_cal_current_ma=%d too high. Forcing to 60.", air_ma)
            cfg["safety"]["air_cal_current_ma"] = 60
        if air_ma < 5:
            cfg["safety"]["air_cal_current_ma"] = 30

        air_sec = int(cfg.get("safety", {}).get("air_cal_max_sec", 15))
        if air_sec > 30:
            self.logger.warning("air_cal_max_sec=%d too high. Forcing to 20.", air_sec)
            cfg["safety"]["air_cal_max_sec"] = 20

        # Sweep sanity
        fmin = float(cfg.get("sweep", {}).get("f_min", 150.0))
        fmax = float(cfg.get("sweep", {}).get("f_max", 200.0))
        if fmin >= fmax:
            self.logger.warning("sweep f_min>=f_max; forcing to 150..200")
            cfg["sweep"]["f_min"] = 150.0
            cfg["sweep"]["f_max"] = 200.0

        # Modbus port sanity
        port = int(cfg.get("modbus", {}).get("port", 5020))
        if port < 1 or port > 65535:
            self.logger.warning("Invalid modbus port=%d; forcing 5020", port)
            cfg["modbus"]["port"] = 5020
