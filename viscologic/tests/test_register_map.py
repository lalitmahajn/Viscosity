# viscologic/tests/test_register_map.py
# Basic tests for Modbus register mapping

import unittest

from viscologic.protocols.register_map import (
    RegisterMap,
    clamp_u16,
    f32_to_u16pair,
    u16pair_to_f32,
    bool_to_u16,
    u16_to_bool,
)


class TestRegisterMapHelpers(unittest.TestCase):
    def test_clamp_u16(self):
        self.assertEqual(clamp_u16(-1), 0)
        self.assertEqual(clamp_u16(0), 0)
        self.assertEqual(clamp_u16(10), 10)
        self.assertEqual(clamp_u16(70000), 65535)

    def test_bool_u16(self):
        self.assertEqual(bool_to_u16(True), 1)
        self.assertEqual(bool_to_u16(False), 0)
        self.assertTrue(u16_to_bool(1))
        self.assertFalse(u16_to_bool(0))
        self.assertTrue(u16_to_bool(2))

    def test_float_roundtrip(self):
        for val in [0.0, 1.0, -1.0, 123.456, -987.25, 1e-6, 1e6]:
            hi, lo = f32_to_u16pair(val)
            back = u16pair_to_f32(hi, lo)
            # float32 precision tolerance
            self.assertAlmostEqual(back, float(val), places=3)


class TestRegisterMapLayout(unittest.TestCase):
    def test_layout_has_required_points(self):
        rm = RegisterMap()
        layout = rm.layout()

        # Must include some key addresses
        self.assertIn("CONTROL_WORD", layout)
        self.assertIn("STATUS_WORD", layout)
        self.assertIn("VISCOSITY_F32_HI", layout)
        self.assertIn("VISCOSITY_F32_LO", layout)
        self.assertIn("TEMP_C_F32_HI", layout)
        self.assertIn("TEMP_C_F32_LO", layout)

        # addresses must be ints within range
        for k, addr in layout.items():
            self.assertIsInstance(addr, int, msg=f"{k} not int")
            self.assertGreaterEqual(addr, 0)
            self.assertLess(addr, 10000)

    def test_encode_decode_status_word(self):
        rm = RegisterMap()
        status = {
            "running": True,
            "locked": True,
            "fault": False,
            "alarm_active": True,
            "remote_enabled": True,
        }
        word = rm.encode_status_word(status)
        decoded = rm.decode_status_word(word)

        self.assertEqual(bool(decoded.get("running")), True)
        self.assertEqual(bool(decoded.get("locked")), True)
        self.assertEqual(bool(decoded.get("fault")), False)
        self.assertEqual(bool(decoded.get("alarm_active")), True)
        self.assertEqual(bool(decoded.get("remote_enabled")), True)

    def test_control_word_flags(self):
        rm = RegisterMap()
        word = rm.encode_control_word(
            start=True,
            stop=False,
            ack=False,
            reset=False,
            local_start=False,
            local_stop=True,
        )
        decoded = rm.decode_control_word(word)

        self.assertTrue(decoded["start"])
        self.assertFalse(decoded["stop"])
        self.assertFalse(decoded["ack"])
        self.assertFalse(decoded["reset"])
        self.assertFalse(decoded["local_start"])
        self.assertTrue(decoded["local_stop"])


if __name__ == "__main__":
    unittest.main()
