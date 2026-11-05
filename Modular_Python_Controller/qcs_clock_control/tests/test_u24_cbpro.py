import tempfile
import unittest
from pathlib import Path

from qcs_clock_control.pcie_i2c import EXPECTED_ID, REG_ID
from qcs_clock_control.u24_cbpro import (ProfileError, U24ProfileTransport,
                                         _u24_command, parse_cbpro_register_file,
                                         dry_run_summary, REVIEWED_PROFILE_SHA256)


def fixture_text(input_select=0x0F):
    registers = [
        (0x000B, 0x74), (0x0021, input_select), (0x0102, 0x01),
        (0x0108, 0x01), (0x010D, 0x01), (0x0112, 0x01),
        (0x0117, 0x01), (0x011C, 0x01), (0x0121, 0x01),
        (0x0126, 0x01), (0x012B, 0x01), (0x0130, 0x01),
        (0x013A, 0x02), (0x013B, 0x09), (0x013C, 0x33),
        (0x013D, 0x09), (0x0310, 0x50), (0x0316, 0xA0),
        (0x0943, 0x00), (0x0949, 0x00), (0x094A, 0x00),
        (0x0A03, 0x02), (0x0A04, 0x00), (0x0A05, 0x02),
        (0x0B4A, 0x1D), (0x001C, 0x01),
    ]
    return ("# Part: Si5341\n# Design ID: HTGU24\n# Device Revision: D\n"
            "Address,Data\n# Start configuration preamble\n"
            "0x0B24,0xC0\n# Delay 300 msec\n" +
            "".join("0x%04X,0x%02X\n" % x for x in registers))


class FakeMmio(object):
    def read32(self, offset):
        return EXPECTED_ID if offset == REG_ID else 0


class FakeClient(object):
    def __init__(self):
        self.mmio = FakeMmio()
        self.page = 5
        self.registers = {0x00FE: 0x0F, 0x0002: 0x41, 0x0003: 0x53,
                          0x0004: 0x00, 0x0005: 0x03, 0x000B: 0x74}
        self.commands = []
        self.fail_at = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def transact(self, command):
        self.commands.append(int(command))
        if self.fail_at is not None and len(self.commands) == self.fail_at:
            raise IOError("injected mock I2C failure")
        mux = (command >> 16) & 0xFF
        if mux != 0x02:
            raise AssertionError("U24 command used mux 0x%02X" % mux)
        reg = command & 0xFF
        page_select = bool(command & (1 << 30))
        if page_select:
            self.page = (command >> 25) & 0x1F
        address = (self.page << 8) | reg
        if command & (1 << 24):
            if reg == 1 and not page_select:
                return self.page
            return self.registers.get(address, 0)
        value = (command >> 32) & 0xFF
        # The soft reset action self-clears in the hardware.
        self.registers[address] = 0 if address == 0x001C else value
        return 0


class U24ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile_path = Path(self.temp.name) / "profile.txt"
        self.profile_path.write_text(fixture_text())

    def test_profile_selects_crystal_and_dry_run_is_non_hardware(self):
        profile = parse_cbpro_register_file(self.profile_path)
        summary = dry_run_summary(profile)
        self.assertEqual(summary["input_selection_register"], 0x0F)
        self.assertEqual(summary["host_io_vdd_sel"], 0)
        self.assertEqual(summary["target"],
                         "U24 address 0x75, motherboard mux mask 0x02")
        self.assertEqual(summary["ordered_register_writes"], 27)

    def test_profile_that_selects_external_input_is_rejected(self):
        self.profile_path.write_text(fixture_text(input_select=0x03))
        with self.assertRaisesRegex(ProfileError, "profile mismatch"):
            parse_cbpro_register_file(self.profile_path)

    def test_live_transport_writes_ordered_bytes_and_verifies_page(self):
        repo = Path(__file__).resolve().parents[3]
        profile_path = (repo / "FPGA_HH_QSFP/clock_circuit_audit_20261101/"
                        "commissioning/u24_clock_control/profiles/"
                        "HTG930_U24-HTGU24-Registers.txt")
        profile = parse_cbpro_register_file(profile_path)
        self.assertEqual(profile["sha256"], REVIEWED_PROFILE_SHA256)
        client = FakeClient()
        transport = U24ProfileTransport(client, sleeper=lambda _seconds: None,
                                        monotonic=lambda: 0.0)
        snapshot = Path(self.temp.name) / "before.json"
        result = transport.apply_profile(profile, snapshot)
        self.assertEqual(result["status"], "applied_and_readback_verified")
        self.assertTrue(result["page_restore_verified"])
        self.assertEqual(result["page_restored"], 5)
        self.assertTrue(snapshot.exists())
        self.assertEqual(client.registers[0x0021], 0x0F)
        self.assertEqual(client.registers[0x013A], 0x02)
        self.assertEqual(client.registers[0x013D], 0x09)
        self.assertTrue(all((command >> 16) & 0xFF == 0x02
                            for command in client.commands))
        self.assertTrue(all((command >> 8) & 0x7F == 0x75
                            for command in client.commands))

    def test_command_builder_encodes_u24_mux_address_page_and_write_data(self):
        command = _u24_command(0x0943, value=0x01)
        self.assertEqual((command >> 16) & 0xFF, 0x02)
        self.assertEqual((command >> 8) & 0x7F, 0x75)
        self.assertEqual(command & 0xFF, 0x43)
        self.assertEqual((command >> 25) & 0x1F, 0x09)
        self.assertTrue(command & (1 << 30))
        self.assertEqual((command >> 32) & 0xFF, 1)


if __name__ == "__main__":
    unittest.main()
