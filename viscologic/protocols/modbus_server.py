# viscologic/protocols/modbus_server.py
# Modbus TCP server (Pymodbus 3.11 compliant)

from __future__ import annotations
import time
import threading
import logging
import traceback
from typing import Any, Dict, Optional

from viscologic.protocols.register_map import (
    RegisterBank, HOLDING_REG_COUNT, set_defaults,
    encode_measurement, bump_heartbeat,
    decode_new_command, write_cmd_result,
    CMD_RESULT_OK, CMD_RESULT_ERR,
    CMD_START, CMD_STOP, CMD_PAUSE, CMD_RESUME,
    CMD_RESET_ALARMS, CMD_SET_MODE,
    CMD_SET_CONTROL_SOURCE, CMD_SET_REMOTE_ENABLE,
    CMD_SET_PROFILE, CMD_BEGIN_AIR_CAL, CMD_ABORT
)

from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.datastore import ModbusServerContext, ModbusDeviceContext
from pymodbus.pdu.device import ModbusDeviceIdentification


class _HoldingDataBlock(ModbusSequentialDataBlock):
    """Thread-safe data block for holding registers."""
    def __init__(self, address, values, lock, logger):
        super().__init__(address, values)
        self._lock = lock
        self._logger = logger

    def getValues(self, address, count=1):
        with self._lock:
            return super().getValues(address, count)

    def setValues(self, address, values):
        with self._lock:
            return super().setValues(address, values)


class ModbusServer:
    def __init__(self, config: Dict[str, Any], bus: Any, logger=None):
        self.config = config or {}
        self.bus = bus
        self.logger = logger or logging.getLogger("viscologic.modbus")

        mb = self.config.get("modbus", {}) or {}
        self.host = str(mb.get("host", "0.0.0.0"))
        self.port = int(mb.get("port", 5020))
        self.unit_id = int(mb.get("unit_id", 1))

        self._lock = threading.RLock()
        self._bank = RegisterBank(size=HOLDING_REG_COUNT)

        set_defaults(
            self._bank,
            mode=0,
            control_source=0,
            remote_enable=int(bool((self.config.get("mode", {}) or {}).get("remote_enable", False))),
        )

        self._ctx = None
        self._stop_event = threading.Event()
        self._last_seen_cmd_seq = 0

    def start(self):
        self._stop_event.clear()

        block = _HoldingDataBlock(0, self._bank.as_list(), self._lock, self.logger)

        store = ModbusDeviceContext(hr=block)

        self._ctx = ModbusServerContext(
            devices={self.unit_id: store},
            single=False,
        )

        threading.Thread(target=self._run_server, daemon=True).start()
        threading.Thread(target=self._run_update_loop, daemon=True).start()

        self.logger.info(
            "Modbus server started host=%s port=%d unit_id=%d",
            self.host, self.port, self.unit_id
        )

    def stop(self):
        self._stop_event.set()
        self.logger.info("Modbus server stop requested.")

    def _run_server(self):
        try:
            if self._ctx is None:
                self.logger.error("Server context not initialized")
                return

            identity = ModbusDeviceIdentification()
            identity.VendorName = "Predictron"
            identity.ProductCode = "VISC"
            identity.ProductName = "ViscoLogic"
            identity.ModelName = "ViscoLogic-RT"
            identity.MajorMinorRevision = "1.0"

            # Pymodbus 3.11 async server — no allow_reuse_address / defer_start
            StartTcpServer(
                context=self._ctx,
                identity=identity,
                address=(self.host, self.port),
            )

        except Exception:
            self.logger.error("Modbus TCP server crashed", exc_info=True)
            traceback.print_exc()

    def _run_update_loop(self):
        while not self._stop_event.is_set():
            try:
                self._push_frame()
                self._handle_plc_command()
            except Exception:
                self.logger.error("Modbus update loop error", exc_info=True)
            time.sleep(0.1)

    def _push_frame(self):
        try:
            frame = self.bus.get_latest_frame()
        except Exception:
            frame = {}

        with self._lock:
            encode_measurement(self._bank, frame)
            bump_heartbeat(self._bank)

    def _handle_plc_command(self):
        with self._lock:
            last_seen, decoded = decode_new_command(self._bank, self._last_seen_cmd_seq)

        if decoded is None:
            return

        self._last_seen_cmd_seq = last_seen

        try:
            ok = self._dispatch_to_bus(decoded)

            with self._lock:
                write_cmd_result(
                    self._bank,
                    last_cmd_seq=decoded.seq,
                    last_cmd_code=decoded.code,
                    result_code=CMD_RESULT_OK if ok else CMD_RESULT_ERR,
                )

        except Exception:
            with self._lock:
                write_cmd_result(
                    self._bank,
                    last_cmd_seq=decoded.seq,
                    last_cmd_code=decoded.code,
                    result_code=CMD_RESULT_ERR,
                )
            self.logger.error("PLC CMD failed", exc_info=True)

    def _dispatch_to_bus(self, d):
        code = int(d.code)
        p1 = int(d.param1)

        mapping = {
            CMD_START: ("START", {}),
            CMD_STOP: ("STOP", {}),
            CMD_PAUSE: ("PAUSE", {}),
            CMD_RESUME: ("RESUME", {}),
            CMD_RESET_ALARMS: ("RESET_ALARMS", {}),
            CMD_SET_MODE: ("SET_MODE", {"mode": p1}),
            CMD_SET_CONTROL_SOURCE: ("SET_CONTROL_SOURCE", {"control_source": p1}),
            CMD_SET_REMOTE_ENABLE: ("SET_REMOTE_ENABLE", {"remote_enable": bool(p1)}),
            CMD_SET_PROFILE: ("SET_PROFILE", {"profile_id": p1}),
            CMD_BEGIN_AIR_CAL: ("BEGIN_AIR_CAL", {}),
            CMD_ABORT: ("ABORT", {}),
        }

        if code not in mapping:
            return False

        cmd, params = mapping[code]
        return self.bus.push_command("PLC", cmd, params, seq_id=d.seq)
    
    # ----------------------------
    # Register access methods (for orchestrator compatibility)
    # ----------------------------
    
    def get_holding_register(self, address: int) -> int:
        """
        Get holding register value (for orchestrator compatibility).
        Thread-safe access to register bank.
        """
        with self._lock:
            return self._bank.get_u16(address)
    
    def set_holding_register(self, address: int, value: int) -> None:
        """
        Set holding register value (for orchestrator compatibility).
        Thread-safe access to register bank.
        """
        with self._lock:
            self._bank.set_u16(address, value)
    
    def read_holding_register(self, address: int) -> int:
        """Alias for get_holding_register (for orchestrator compatibility)."""
        return self.get_holding_register(address)
    
    def write_holding_register(self, address: int, value: int) -> None:
        """Alias for set_holding_register (for orchestrator compatibility)."""
        self.set_holding_register(address, value)
    
    def get_register_bank(self) -> RegisterBank:
        """
        Get the internal register bank (for direct access if needed).
        Note: Use with caution - prefer get_holding_register/set_holding_register for thread safety.
        """
        return self._bank

