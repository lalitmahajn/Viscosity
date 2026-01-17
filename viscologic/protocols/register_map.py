# viscologic/protocols/register_map.py
# Modbus register map (Holding Registers) for ViscoLogic
# - Versioned mapping
# - Fixed addresses
# - Scaling: values stored as integers (x100 etc.)
# - Commands via CMD_SEQ handshake to avoid repeats

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
import struct


# ----------------------------
# Mapping Version
# ----------------------------

MAPPING_VERSION = 1


# ----------------------------
# Register Addresses (Holding Registers)
# ----------------------------
# NOTE: Addressing here is 0-based internal. Your modbus library may expose 0-based or 1-based.
# We'll use 0-based in code and keep consistent everywhere.

REG_MAP_VERSION      = 0
REG_HEARTBEAT_OUT    = 1
REG_STATUS_WORD      = 2
REG_ALARM_WORD       = 3

REG_VISC_X100_I32    = 4   # uses 4-5 (int32)
REG_TEMP_X100_I16    = 6   # int16
REG_FREQ_X100_I16    = 7   # int16
REG_HEALTH_U16       = 8   # 0..100

REG_MODE_U16         = 10  # 0 tabletop, 1 inline
REG_CONTROL_SRC_U16  = 11  # 0 local, 1 remote, 2 mixed
REG_REMOTE_EN_U16    = 12  # 0/1
REG_ACTIVE_CTRL_U16  = 13  # 0 local, 1 plc (who is currently driving)

REG_LAST_CMD_SEQ_U16 = 14  # last processed seq
REG_CMD_RESULT_U16   = 15  # 0 idle, 1 ok, 2 err
REG_LAST_CMD_CODE_U16= 16  # last processed cmd code

# Command write area (PLC -> device)
REG_CMD_SEQ_IN_U16   = 20  # PLC writes seq; device processes when seq changes
REG_CMD_CODE_IN_U16  = 21  # numeric command code
REG_CMD_PARAM1_I16   = 22  # param1 (signed)
REG_CMD_PARAM2_I16   = 23
REG_CMD_PARAM3_I16   = 24

# Optional PLC heartbeat in (not required, but useful)
REG_HEARTBEAT_IN_U16 = 30

# Total holding register count (allocate a bank)
HOLDING_REG_COUNT = 64


# ----------------------------
# Status Word Bits (REG_STATUS_WORD)
# ----------------------------
STATUS_SYSTEM_READY           = 0   # bit0
STATUS_SELF_CHECK_FAIL        = 1   # bit1
STATUS_SWEEPING               = 2   # bit2
STATUS_LOCKING                = 3   # bit3
STATUS_LOCKED                 = 4   # bit4
STATUS_PAUSED                 = 5   # bit5
STATUS_FAULT_LATCHED          = 6   # bit6
STATUS_REMOTE_ENABLED         = 7   # bit7
STATUS_REMOTE_ACTIVE          = 8   # bit8 (PLC currently controlling)
STATUS_COMM_LOSS              = 9   # bit9
STATUS_COMMISSIONING_REQUIRED = 12  # bit12
STATUS_ENGINEER_UNLOCKED      = 13  # bit13


STATUS_BIT_NAMES = {
    STATUS_SYSTEM_READY: "SYSTEM_READY",
    STATUS_SELF_CHECK_FAIL: "SELF_CHECK_FAIL",
    STATUS_SWEEPING: "SWEEPING",
    STATUS_LOCKING: "LOCKING",
    STATUS_LOCKED: "LOCKED",
    STATUS_PAUSED: "PAUSED",
    STATUS_FAULT_LATCHED: "FAULT_LATCHED",
    STATUS_REMOTE_ENABLED: "REMOTE_ENABLED",
    STATUS_REMOTE_ACTIVE: "REMOTE_ACTIVE",
    STATUS_COMM_LOSS: "COMM_LOSS",
    STATUS_COMMISSIONING_REQUIRED: "COMMISSIONING_REQUIRED",
    STATUS_ENGINEER_UNLOCKED: "ENGINEER_UNLOCKED",
}


# ----------------------------
# Alarm Word Bits (REG_ALARM_WORD)
# ----------------------------
ALARM_ADC_FAULT        = 0
ALARM_TEMP_FAULT       = 1
ALARM_OVERCURRENT      = 2
ALARM_OVERHEAT         = 3
ALARM_SIGNAL_CLIP      = 4
ALARM_LOST_LOCK        = 5
ALARM_CONFIG_INVALID   = 6
ALARM_STORAGE_ERROR    = 7
ALARM_MODBUS_ERROR     = 8

ALARM_BIT_NAMES = {
    ALARM_ADC_FAULT: "ADC_FAULT",
    ALARM_TEMP_FAULT: "TEMP_FAULT",
    ALARM_OVERCURRENT: "OVERCURRENT",
    ALARM_OVERHEAT: "OVERHEAT",
    ALARM_SIGNAL_CLIP: "SIGNAL_CLIP",
    ALARM_LOST_LOCK: "LOST_LOCK",
    ALARM_CONFIG_INVALID: "CONFIG_INVALID",
    ALARM_STORAGE_ERROR: "STORAGE_ERROR",
    ALARM_MODBUS_ERROR: "MODBUS_ERROR",
}


# ----------------------------
# Command Codes (PLC -> device)
# ----------------------------
CMD_NONE               = 0
CMD_START              = 1
CMD_STOP               = 2
CMD_PAUSE              = 3
CMD_RESUME             = 4
CMD_RESET_ALARMS       = 5

CMD_SET_MODE           = 10  # param1 = 0 tabletop, 1 inline
CMD_SET_CONTROL_SOURCE = 11  # param1 = 0 local, 1 remote, 2 mixed
CMD_SET_REMOTE_ENABLE  = 12  # param1 = 0/1
CMD_SET_PROFILE        = 13  # param1 = profile_id (int)

CMD_BEGIN_AIR_CAL      = 20
CMD_ABORT              = 99

CMD_CODE_NAMES = {
    CMD_NONE: "NONE",
    CMD_START: "START",
    CMD_STOP: "STOP",
    CMD_PAUSE: "PAUSE",
    CMD_RESUME: "RESUME",
    CMD_RESET_ALARMS: "RESET_ALARMS",
    CMD_SET_MODE: "SET_MODE",
    CMD_SET_CONTROL_SOURCE: "SET_CONTROL_SOURCE",
    CMD_SET_REMOTE_ENABLE: "SET_REMOTE_ENABLE",
    CMD_SET_PROFILE: "SET_PROFILE",
    CMD_BEGIN_AIR_CAL: "BEGIN_AIR_CAL",
    CMD_ABORT: "ABORT",
}


# ----------------------------
# Command Result (device -> PLC)
# ----------------------------
CMD_RESULT_IDLE = 0
CMD_RESULT_OK   = 1
CMD_RESULT_ERR  = 2

CMD_RESULT_NAMES = {
    CMD_RESULT_IDLE: "IDLE",
    CMD_RESULT_OK: "OK",
    CMD_RESULT_ERR: "ERR",
}


# ----------------------------
# Scaling helpers
# ----------------------------

def clamp_int(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def to_u16(v: int) -> int:
    return int(v) & 0xFFFF


def to_i16(v: int) -> int:
    v = int(v)
    v = clamp_int(v, -32768, 32767)
    # store as unsigned 16-bit in register
    return v & 0xFFFF


def from_i16(reg_u16: int) -> int:
    x = int(reg_u16) & 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def set_bit(word: int, bit: int, value: bool) -> int:
    if value:
        return word | (1 << bit)
    return word & ~(1 << bit)


def get_bit(word: int, bit: int) -> bool:
    return bool((word >> bit) & 1)


# ----------------------------
# int32 packing (2 registers)
# We'll use HIGH word first: [addr]=high, [addr+1]=low
# ----------------------------

def to_i32(v: int) -> int:
    v = int(v)
    if v < -2147483648:
        v = -2147483648
    if v > 2147483647:
        v = 2147483647
    return v


def set_i32(regs: list[int], addr: int, value: int) -> None:
    v = to_i32(value)
    u32 = v & 0xFFFFFFFF
    hi = (u32 >> 16) & 0xFFFF
    lo = u32 & 0xFFFF
    regs[addr] = hi
    regs[addr + 1] = lo


def get_i32(regs: list[int], addr: int) -> int:
    hi = regs[addr] & 0xFFFF
    lo = regs[addr + 1] & 0xFFFF
    u32 = (hi << 16) | lo
    # signed
    return u32 - 0x100000000 if u32 & 0x80000000 else u32


# ----------------------------
# Register Bank
# ----------------------------

class RegisterBank:
    def __init__(self, size: int = HOLDING_REG_COUNT):
        self.regs = [0] * int(size)

    def set_u16(self, addr: int, value: int) -> None:
        self.regs[addr] = to_u16(value)

    def get_u16(self, addr: int) -> int:
        return self.regs[addr] & 0xFFFF

    def set_i16(self, addr: int, value: int) -> None:
        self.regs[addr] = to_i16(value)

    def get_i16(self, addr: int) -> int:
        return from_i16(self.regs[addr])

    def set_i32(self, addr: int, value: int) -> None:
        set_i32(self.regs, addr, value)

    def get_i32(self, addr: int) -> int:
        return get_i32(self.regs, addr)

    def as_list(self) -> list[int]:
        return list(self.regs)


# ----------------------------
# Encode measurement -> registers
# ----------------------------

def encode_measurement(bank: RegisterBank, frame: Dict[str, Any]) -> None:
    """
    frame keys:
      viscosity_cp (float), temp_c (float), freq_hz (float), health_pct (int),
      status_word (int), alarm_word (int)
    """
    visc_x100 = int(round(float(frame.get("viscosity_cp", 0.0)) * 100.0))
    temp_x100 = int(round(float(frame.get("temp_c", 0.0)) * 100.0))
    freq_x100 = int(round(float(frame.get("freq_hz", 0.0)) * 100.0))
    health = int(frame.get("health_pct", 0) or 0)

    bank.set_i32(REG_VISC_X100_I32, visc_x100)
    bank.set_i16(REG_TEMP_X100_I16, temp_x100)
    bank.set_i16(REG_FREQ_X100_I16, freq_x100)
    bank.set_u16(REG_HEALTH_U16, clamp_int(health, 0, 100))

    bank.set_u16(REG_STATUS_WORD, int(frame.get("status_word", 0) or 0))
    bank.set_u16(REG_ALARM_WORD, int(frame.get("alarm_word", 0) or 0))


def set_defaults(bank: RegisterBank, *, mode: int = 0, control_source: int = 0, remote_enable: int = 0) -> None:
    bank.set_u16(REG_MAP_VERSION, MAPPING_VERSION)
    bank.set_u16(REG_HEARTBEAT_OUT, 0)
    bank.set_u16(REG_STATUS_WORD, 0)
    bank.set_u16(REG_ALARM_WORD, 0)

    bank.set_u16(REG_MODE_U16, mode)
    bank.set_u16(REG_CONTROL_SRC_U16, control_source)
    bank.set_u16(REG_REMOTE_EN_U16, remote_enable)
    bank.set_u16(REG_ACTIVE_CTRL_U16, 0)

    bank.set_u16(REG_LAST_CMD_SEQ_U16, 0)
    bank.set_u16(REG_CMD_RESULT_U16, CMD_RESULT_IDLE)
    bank.set_u16(REG_LAST_CMD_CODE_U16, CMD_NONE)

    # Clear command input area
    bank.set_u16(REG_CMD_SEQ_IN_U16, 0)
    bank.set_u16(REG_CMD_CODE_IN_U16, CMD_NONE)
    bank.set_i16(REG_CMD_PARAM1_I16, 0)
    bank.set_i16(REG_CMD_PARAM2_I16, 0)
    bank.set_i16(REG_CMD_PARAM3_I16, 0)


def bump_heartbeat(bank: RegisterBank) -> int:
    hb = (bank.get_u16(REG_HEARTBEAT_OUT) + 1) & 0xFFFF
    bank.set_u16(REG_HEARTBEAT_OUT, hb)
    return hb


# ----------------------------
# Decode PLC command (handshake)
# ----------------------------

@dataclass
class DecodedCommand:
    seq: int
    code: int
    param1: int
    param2: int
    param3: int


def decode_new_command(bank: RegisterBank, last_seen_seq: int) -> Tuple[int, Optional[DecodedCommand]]:
    """
    Device keeps track of last_seen_seq (from internal memory, not from register)
    If PLC writes a new REG_CMD_SEQ_IN_U16 value (different from last_seen_seq), treat it as a new command.
    """
    seq = bank.get_u16(REG_CMD_SEQ_IN_U16)
    if seq == last_seen_seq:
        return last_seen_seq, None

    code = bank.get_u16(REG_CMD_CODE_IN_U16)
    p1 = bank.get_i16(REG_CMD_PARAM1_I16)
    p2 = bank.get_i16(REG_CMD_PARAM2_I16)
    p3 = bank.get_i16(REG_CMD_PARAM3_I16)

    cmd = DecodedCommand(seq=seq, code=code, param1=p1, param2=p2, param3=p3)
    return seq, cmd


def write_cmd_result(bank: RegisterBank, *, last_cmd_seq: int, last_cmd_code: int, result_code: int) -> None:
    bank.set_u16(REG_LAST_CMD_SEQ_U16, last_cmd_seq & 0xFFFF)
    bank.set_u16(REG_LAST_CMD_CODE_U16, last_cmd_code & 0xFFFF)
    bank.set_u16(REG_CMD_RESULT_U16, result_code & 0xFFFF)


# ----------------------------
# Utilities: pretty decode
# ----------------------------

def decode_status_bits(status_word: int) -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    for bit, name in STATUS_BIT_NAMES.items():
        out[name] = get_bit(status_word, bit)
    return out


def decode_alarm_bits(alarm_word: int) -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    for bit, name in ALARM_BIT_NAMES.items():
        out[name] = get_bit(alarm_word, bit)
    return out

# -------------------------------------------------
# Compatibility: layout() helper (expected by orchestrator)
# -------------------------------------------------

def _build_layout() -> Dict[str, int]:
    """
    Builds a symbolic -> address mapping so orchestrator and modbus
    code can ask regmap.layout()['STATUS_WORD'] etc.
    """
    return {
        "MAP_VERSION": REG_MAP_VERSION,
        "HEARTBEAT_OUT": REG_HEARTBEAT_OUT,
        "STATUS_WORD": REG_STATUS_WORD,
        "ALARM_WORD": REG_ALARM_WORD,

        "VISCOSITY_I32": REG_VISC_X100_I32,
        "TEMP_X100": REG_TEMP_X100_I16,
        "FREQ_X100": REG_FREQ_X100_I16,
        "HEALTH": REG_HEALTH_U16,

        "MODE": REG_MODE_U16,
        "CONTROL_SOURCE": REG_CONTROL_SRC_U16,
        "REMOTE_ENABLE": REG_REMOTE_EN_U16,
        "ACTIVE_CONTROL": REG_ACTIVE_CTRL_U16,

        "LAST_CMD_SEQ": REG_LAST_CMD_SEQ_U16,
        "CMD_RESULT": REG_CMD_RESULT_U16,
        "LAST_CMD_CODE": REG_LAST_CMD_CODE_U16,

        "CMD_SEQ_IN": REG_CMD_SEQ_IN_U16,
        "CMD_CODE_IN": REG_CMD_CODE_IN_U16,
        "CMD_PARAM1": REG_CMD_PARAM1_I16,
        "CMD_PARAM2": REG_CMD_PARAM2_I16,
        "CMD_PARAM3": REG_CMD_PARAM3_I16,
        
        # Legacy control word support
        "CONTROL_WORD": 40,  # REG_CONTROL_WORD
        
        # Float32 register pairs for orchestrator
        "VISCOSITY_F32_HI": 50,
        "VISCOSITY_F32_LO": 51,
        "TEMP_C_F32_HI": 52,
        "TEMP_C_F32_LO": 53,
        "FREQ_HZ_F32_HI": 54,
        "FREQ_HZ_F32_LO": 55,
        "MAG_F32_HI": 56,
        "MAG_F32_LO": 57,
        "CONFIDENCE_F32_HI": 58,
        "CONFIDENCE_F32_LO": 59,
    }


# ----------------------------
# Float32 encoding/decoding (IEEE 754)
# ----------------------------

def f32_to_u16pair(value: float) -> Tuple[int, int]:
    """
    Convert float32 to two uint16 registers (IEEE 754).
    Returns: (high_word, low_word)
    """
    # Pack as IEEE 754 float32 (4 bytes, big-endian)
    bytes_val = struct.pack('>f', float(value))
    # Unpack as two uint16 (big-endian)
    hi, lo = struct.unpack('>HH', bytes_val)
    return int(hi), int(lo)


def u16pair_to_f32(hi: int, lo: int) -> float:
    """
    Convert two uint16 registers to float32 (IEEE 754).
    """
    # Pack as two uint16 (big-endian)
    bytes_val = struct.pack('>HH', int(hi) & 0xFFFF, int(lo) & 0xFFFF)
    # Unpack as IEEE 754 float32
    return float(struct.unpack('>f', bytes_val)[0])


# ----------------------------
# Control Word (PLC -> Device) - Legacy support
# ----------------------------

CONTROL_BIT_START      = 0
CONTROL_BIT_STOP      = 1
CONTROL_BIT_ACK       = 2
CONTROL_BIT_RESET     = 3
CONTROL_BIT_LOCAL_START = 4
CONTROL_BIT_LOCAL_STOP  = 5

# Control word register (if using legacy control word approach)
# Note: Current implementation uses CMD_SEQ handshake, but legacy support available
REG_CONTROL_WORD = 40  # Optional legacy register

# Extend RegisterBank with additional methods
_RegisterBankBase = RegisterBank

class RegisterBank(_RegisterBankBase):  # extend existing class
    _layout_cache = None

    def __init__(self, size: int = HOLDING_REG_COUNT):
        super().__init__(size)
        if RegisterBank._layout_cache is None:
            RegisterBank._layout_cache = _build_layout()

    def layout(self) -> Dict[str, int]:
        """
        New orchestrator expects this function.
        Old code keeps working because we don't modify internal behavior.
        """
        layout_dict = dict(self._layout_cache)
        # Add CONTROL_WORD for legacy support (if orchestrator needs it)
        if "CONTROL_WORD" not in layout_dict:
            layout_dict["CONTROL_WORD"] = REG_CONTROL_WORD
        # Add F32 register pairs for orchestrator
        if "VISCOSITY_F32_HI" not in layout_dict:
            layout_dict["VISCOSITY_F32_HI"] = 50
            layout_dict["VISCOSITY_F32_LO"] = 51
            layout_dict["TEMP_C_F32_HI"] = 52
            layout_dict["TEMP_C_F32_LO"] = 53
            layout_dict["FREQ_HZ_F32_HI"] = 54
            layout_dict["FREQ_HZ_F32_LO"] = 55
            layout_dict["MAG_F32_HI"] = 56
            layout_dict["MAG_F32_LO"] = 57
            layout_dict["CONFIDENCE_F32_HI"] = 58
            layout_dict["CONFIDENCE_F32_LO"] = 59
        return layout_dict

    def encode_status_word(self, flags: Dict[str, bool]) -> int:
        """
        Encode status flags dictionary into a status word integer.
        flags keys: running, locked, fault, alarm_active, remote_enabled
        """
        word = 0
        
        # Map dictionary keys to status bits
        word = set_bit(word, STATUS_SYSTEM_READY, True)  # System is ready
        
        if flags.get("running", False):
            # If running, set appropriate bits based on state
            # For now, set SWEEPING bit (orchestrator handles state details)
            word = set_bit(word, STATUS_SWEEPING, True)
        
        word = set_bit(word, STATUS_LOCKED, flags.get("locked", False))
        word = set_bit(word, STATUS_FAULT_LATCHED, flags.get("fault", False) or flags.get("alarm_active", False))
        word = set_bit(word, STATUS_REMOTE_ENABLED, flags.get("remote_enabled", False))
        
        return word & 0xFFFF
    
    def decode_status_word(self, word: int) -> Dict[str, bool]:
        """
        Decode status word integer into flags dictionary.
        """
        return {
            "system_ready": get_bit(word, STATUS_SYSTEM_READY),
            "self_check_fail": get_bit(word, STATUS_SELF_CHECK_FAIL),
            "sweeping": get_bit(word, STATUS_SWEEPING),
            "locking": get_bit(word, STATUS_LOCKING),
            "locked": get_bit(word, STATUS_LOCKED),
            "paused": get_bit(word, STATUS_PAUSED),
            "fault": get_bit(word, STATUS_FAULT_LATCHED),
            "remote_enabled": get_bit(word, STATUS_REMOTE_ENABLED),
            "remote_active": get_bit(word, STATUS_REMOTE_ACTIVE),
            "comm_loss": get_bit(word, STATUS_COMM_LOSS),
            "commissioning_required": get_bit(word, STATUS_COMMISSIONING_REQUIRED),
            "engineer_unlocked": get_bit(word, STATUS_ENGINEER_UNLOCKED),
        }
    
    def encode_control_word(
        self,
        start: bool = False,
        stop: bool = False,
        ack: bool = False,
        reset: bool = False,
        local_start: bool = False,
        local_stop: bool = False,
    ) -> int:
        """
        Encode control flags into control word integer (legacy support).
        """
        word = 0
        word = set_bit(word, CONTROL_BIT_START, start)
        word = set_bit(word, CONTROL_BIT_STOP, stop)
        word = set_bit(word, CONTROL_BIT_ACK, ack)
        word = set_bit(word, CONTROL_BIT_RESET, reset)
        word = set_bit(word, CONTROL_BIT_LOCAL_START, local_start)
        word = set_bit(word, CONTROL_BIT_LOCAL_STOP, local_stop)
        return word & 0xFFFF
    
    def decode_control_word(self, word: int) -> Dict[str, bool]:
        """
        Decode control word integer into flags dictionary (legacy support).
        """
        return {
            "start": get_bit(word, CONTROL_BIT_START),
            "stop": get_bit(word, CONTROL_BIT_STOP),
            "ack": get_bit(word, CONTROL_BIT_ACK),
            "reset": get_bit(word, CONTROL_BIT_RESET),
            "local_start": get_bit(word, CONTROL_BIT_LOCAL_START),
            "local_stop": get_bit(word, CONTROL_BIT_LOCAL_STOP),
        }
    
    def encode_alarm_word(self, alarms: Dict[str, bool]) -> int:
        """
        Encode alarm flags dictionary into alarm word integer.
        """
        word = 0
        word = set_bit(word, ALARM_ADC_FAULT, alarms.get("ADC_FAULT", False))
        word = set_bit(word, ALARM_TEMP_FAULT, alarms.get("TEMP_FAULT", False))
        word = set_bit(word, ALARM_OVERCURRENT, alarms.get("OVERCURRENT", False))
        word = set_bit(word, ALARM_OVERHEAT, alarms.get("OVERHEAT", False))
        word = set_bit(word, ALARM_SIGNAL_CLIP, alarms.get("SIGNAL_CLIP", False))
        word = set_bit(word, ALARM_LOST_LOCK, alarms.get("LOST_LOCK", False))
        word = set_bit(word, ALARM_CONFIG_INVALID, alarms.get("CONFIG_INVALID", False))
        word = set_bit(word, ALARM_STORAGE_ERROR, alarms.get("STORAGE_ERROR", False))
        word = set_bit(word, ALARM_MODBUS_ERROR, alarms.get("MODBUS_ERROR", False))
        return word & 0xFFFF
    
    def f32_to_u16pair(self, value: float) -> Tuple[int, int]:
        """
        Convert float32 to two uint16 registers (IEEE 754).
        Returns: (high_word, low_word)
        """
        return f32_to_u16pair(value)