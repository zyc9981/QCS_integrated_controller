import tempfile
import unittest
from pathlib import Path

from qcs_clock_control.actuator import EXPECTED_FIXED, NUM_ADDRS, STATIC_STATE_ADDRS, build_n1_register_plan
from qcs_clock_control.pcie_i2c import (
    EXPECTED_ID, REG_COMMAND_HIGH, REG_COMMAND_LOW, REG_ID, REG_LOCK,
    REG_START, REG_STATUS, START_MAGIC, PcieI2cClient,
    PcieSi5341Transport, make_i2c_command,
)


class FakeBridgeMmio:
    """MMIO and Si5341 register behavior for end-to-end software-path tests."""
    def __init__(self, registers, current_page=7, nack=False, lock_fault=False):
        self.regs = dict(registers)
        self.page = current_page
        self.nack = nack
        self.lock_fault = lock_fault
        self.locked = False
        self.seq = 0
        self.data = 0
        self.error = 0
        self.success = 0
        self.low = 0
        self.high = 0
        self.started = []

    def _status(self):
        return ((self.seq & 0xFFFF) << 16) | (self.data << 8) | (self.error << 4) | \
               (int(self.lock_fault) << 3) | (self.success << 2) | (int(self.locked) << 1)

    def read32(self, offset):
        if offset == REG_ID:
            return EXPECTED_ID
        if offset == REG_STATUS:
            return self._status()
        return 0

    def write32(self, offset, value):
        if offset == REG_LOCK:
            self.locked = bool(value & 1)
        elif offset == REG_COMMAND_LOW:
            self.low = value & 0x7FFFFFFF
        elif offset == REG_COMMAND_HIGH:
            self.high = value & 0xFF
        elif offset == REG_START:
            if value != START_MAGIC or not self.locked:
                self.error, self.success = 2, 0
                return
            cmd = (self.high << 32) | self.low
            self.started.append(cmd)
            self.seq = (self.seq + 1) & 0xFFFF
            if self.nack:
                self.error, self.success = 1, 0
                return
            self.error = 0
            if (cmd >> 30) & 1:
                self.page = (cmd >> 25) & 0x1F
            reg = cmd & 0xFF
            addr = (cmd >> 8) & 0x7F
            is_read = (cmd >> 24) & 1
            is_write = (cmd >> 15) & 1
            if addr != 0x77:
                self.error, self.success = 1, 0
                return
            full = (self.page << 8) | reg
            if reg == 1 and is_read and not ((cmd >> 30) & 1):
                self.data = self.page
            elif is_read:
                self.data = self.regs.get(full, 0)
            elif is_write:
                val = (cmd >> 32) & 0xFF
                self.regs[full] = val
                if full == 0x0317 and val & 1:
                    self.regs[full] = val & 0xFE
            self.success = 1


def commissioned_registers():
    numerator = 1452136671315
    registers = dict(EXPECTED_FIXED)
    for i, address in enumerate(NUM_ADDRS):
        registers[address] = (numerator >> (8 * i)) & 0xFF
    registers.update({0x00FE: 0x0F, 0x0002: 0x41, 0x0003: 0x53,
                      0x0004: 0x00, 0x0005: 0x03, 0x0317: 0x00})
    return registers, numerator


class PcieI2cTests(unittest.TestCase):
    def test_command_encoding_includes_page_for_writes(self):
        read_cmd = make_i2c_command(0x77, 0x0D, page=3, read=True)
        write_cmd = make_i2c_command(0x77, 0x0D, page=3, value=0xA5)
        self.assertEqual((read_cmd >> 25) & 0x3F, 0x23)  # page plus page-select bit
        self.assertTrue((read_cmd >> 24) & 1)
        self.assertTrue((write_cmd >> 30) & 1)
        self.assertTrue((write_cmd >> 15) & 1)
        self.assertEqual((write_cmd >> 32) & 0xFF, 0xA5)

    def test_complete_transport_read_update_and_page_restore(self):
        registers, current_num = commissioned_registers()
        mmio = FakeBridgeMmio(registers, current_page=7)
        with tempfile.TemporaryDirectory() as tmp:
            client = PcieI2cClient(mmio, lock_path=Path(tmp) / "lock")
            transport = PcieSi5341Transport(client)
            expected = {a: registers[a] for a in STATIC_STATE_ADDRS}
            verified = transport.verify_state(expected)
            self.assertTrue(verified["acknowledged"])
            self.assertEqual(verified["registers"][0x030D], registers[0x030D])
            self.assertEqual(mmio.page, 7)
            target = current_num - 1
            full_expected = dict(expected)
            full_expected.update({a: registers[a] for a in NUM_ADDRS})
            plan = build_n1_register_plan(target, full_expected)
            result = transport.apply_n1(target, full_expected, plan)
            self.assertTrue(result["acknowledged"])
            actual = sum(mmio.regs[a] << (8 * i) for i, a in enumerate(NUM_ADDRS))
            self.assertEqual(actual, target)
            self.assertEqual(mmio.page, 7)
            self.assertEqual(mmio.regs[0x0317] & 1, 0)
            self.assertGreater(len(mmio.started), 30)

    def test_nack_is_not_reported_as_success(self):
        registers, _ = commissioned_registers()
        mmio = FakeBridgeMmio(registers, nack=True)
        with tempfile.TemporaryDirectory() as tmp:
            client = PcieI2cClient(mmio, lock_path=Path(tmp) / "lock")
            client.acquire()
            try:
                with self.assertRaisesRegex(Exception, "NACK"):
                    client.transact(make_i2c_command(0x77, 0xFE, read=True))
            finally:
                client.release()

    def test_selector_fault_refuses_lock_and_rolls_back_request(self):
        registers, _ = commissioned_registers()
        mmio = FakeBridgeMmio(registers, lock_fault=True)
        with tempfile.TemporaryDirectory() as tmp:
            client = PcieI2cClient(mmio, lock_path=Path(tmp) / "lock")
            with self.assertRaisesRegex(Exception, "QSFP3 is not selected"):
                client.acquire()
            self.assertFalse(mmio.locked)


if __name__ == "__main__":
    unittest.main()
