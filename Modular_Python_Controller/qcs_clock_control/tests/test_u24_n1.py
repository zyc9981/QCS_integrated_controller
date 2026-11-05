import unittest

from qcs_clock_control.actuator import ActuatorError, NUM_ADDRS
from qcs_clock_control.pcie_i2c import EXPECTED_ID, REG_ID
from qcs_clock_control.u24_cbpro import EXPECTED_DEVICE_ID, U24_ADDRESS
from qcs_clock_control.u24_n1 import (EXPECTED_STATIC, NOMINAL_NUMERATOR,
                                      N1_DENOMINATOR, N1_STEP_WORD,
                                      apply_u24_n1_numerator,
                                      calculate_u24_n1_ppm, read_u24_state)


class FakeMmio(object):
    def read32(self, offset):
        return EXPECTED_ID if offset == REG_ID else 0


class FakeClient(object):
    def __init__(self, page=4):
        self.mmio = FakeMmio()
        self.page = page
        self.commands = []
        self.data_writes = []
        self.registers = dict(EXPECTED_DEVICE_ID)
        self.registers.update(EXPECTED_STATIC)
        for index, address in enumerate(NUM_ADDRS):
            self.registers[address] = (NOMINAL_NUMERATOR >> (8 * index)) & 0xFF
        for index, address in enumerate(range(0x0313, 0x0317)):
            self.registers[address] = (N1_DENOMINATOR >> (8 * index)) & 0xFF
        self.registers[0x0317] = 0
        self.fail_at = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def transact(self, command):
        self.commands.append(command)
        if self.fail_at == len(self.commands):
            raise IOError("injected transaction failure")
        if ((command >> 16) & 0xFF) != 0x02 or ((command >> 8) & 0x7F) != U24_ADDRESS:
            raise AssertionError("wrong U24 mux or address")
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
        self.registers[address] = value
        self.data_writes.append((address, value))
        if address == 0x0317:
            self.registers[address] = value & 0xFE
        return 0


class U24N1Tests(unittest.TestCase):
    def test_ppm_direction_step_and_range(self):
        positive = calculate_u24_n1_ppm("1.0")
        negative = calculate_u24_n1_ppm("-1.0")
        self.assertLess(positive["numerator"], NOMINAL_NUMERATOR)
        self.assertGreater(negative["numerator"], NOMINAL_NUMERATOR)
        self.assertEqual((NOMINAL_NUMERATOR - positive["numerator"]) % N1_STEP_WORD, 0)
        self.assertEqual((negative["numerator"] - NOMINAL_NUMERATOR) % N1_STEP_WORD, 0)
        self.assertAlmostEqual(positive["representable_ppm"], 1.000018, places=4)
        self.assertAlmostEqual(negative["representable_ppm"], -1.000018, places=4)
        with self.assertRaisesRegex(ValueError, "limited to"):
            calculate_u24_n1_ppm("200.1")

    def test_live_snapshot_preserves_page_and_checks_u24_state(self):
        client = FakeClient(page=7)
        state = read_u24_state(client)
        self.assertEqual(state["numerator"], NOMINAL_NUMERATOR)
        self.assertEqual(state["denominator"], N1_DENOMINATOR)
        self.assertEqual(state["original_page"], 7)
        self.assertEqual(client.page, 7)

    def test_update_writes_only_n1_num_and_latches_then_verifies(self):
        client = FakeClient(page=3)
        target = calculate_u24_n1_ppm("1.0")["numerator"]
        result = apply_u24_n1_numerator(client, target)
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["previous_numerator"], NOMINAL_NUMERATOR)
        self.assertEqual(client.page, 3)
        self.assertEqual(sum(client.registers[a] << (8 * i)
                             for i, a in enumerate(NUM_ADDRS)), target)
        written_addresses = {address for address, _value in client.data_writes}
        self.assertEqual(written_addresses, set(NUM_ADDRS) | {0x0317})
        self.assertEqual(sum(client.registers[a] << (8 * i)
                             for i, a in enumerate(range(0x0313, 0x0317))),
                         N1_DENOMINATOR)

    def test_static_mismatch_fails_before_register_writes(self):
        client = FakeClient()
        client.registers[0x013A] = 0x01
        with self.assertRaisesRegex(ActuatorError, "profile precondition mismatch"):
            apply_u24_n1_numerator(client, calculate_u24_n1_ppm("1")["numerator"])
        self.assertEqual(client.data_writes, [])


if __name__ == "__main__":
    unittest.main()
