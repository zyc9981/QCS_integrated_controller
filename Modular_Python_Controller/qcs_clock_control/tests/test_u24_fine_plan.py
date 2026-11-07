"""Exercise the exact commissioning script with a mock I2C device."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from test_u24_n1 import FakeClient

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / 'FPGA_HH_QSFP/clock_circuit_audit_20261101/commissioning/u24_clock_control/scripts/apply_u24_fine_n1_plan.py'
spec = importlib.util.spec_from_file_location('fine_plan', str(SCRIPT))
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class FinePlanTests(unittest.TestCase):
    def client(self):
        client = FakeClient(page=7)
        client.registers.update(plan.EXPECTED_STATIC)
        for addresses, value in [(plan.NUM_ADDRS, plan.BASELINE_NUM),
                                 (plan.DEN_ADDRS, plan.BASELINE_DEN)]:
            for i, address in enumerate(addresses):
                client.registers[address] = (value >> (8*i)) & 255
        return client

    def run_plan(self, client, directory):
        def selector(_vivado, action, value=None):
            return {'QCS_SELECTOR_ORIGINAL': '3',
                    'QCS_SELECTOR_VALUE': '2' if action == 'prepare' else str(value)}
        output = Path(directory) / 'result.json'
        with patch.object(plan, 'PACKAGE', Path(directory)), \
             patch.object(plan, 'run_selector', side_effect=selector), \
             patch.object(plan, 'FileMmio', return_value=MagicMock()), \
             patch.object(plan, 'PcieI2cClient', return_value=client), \
             patch.object(plan.sys, 'argv', ['plan', '--apply', '--confirm',
                 'APPLY-U24-FINE-N1', '--output', str(output)]), \
             contextlib.redirect_stdout(io.StringIO()):
            plan.main()
        return json.loads(output.read_text())

    def test_exact_ratio_muting_staging_and_protected_registers(self):
        client = self.client()
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_plan(client, directory)
        self.assertTrue(result['applied'])
        self.assertEqual(plan.NOMINAL_NUM * plan.BASELINE_DEN,
                         plan.BASELINE_NUM * plan.DENOMINATOR)
        writes = client.data_writes
        self.assertEqual(writes[0], (0x013A, 0x04))
        latch = next(i for i, (a, _) in enumerate(writes) if a == 0x0317)
        self.assertEqual({a for a, _ in writes[1:latch]},
                         {0x013A} | set(plan.NUM_ADDRS) | set(plan.DEN_ADDRS))
        self.assertEqual(writes[-1], (0x013A, 0x06))
        self.assertEqual(client.page, 7)
        self.assertEqual(result['selector_restored'], 3)

    def test_failure_restores_both_divider_terms_and_output(self):
        client = self.client()
        original = client.transact
        failed = [False]
        def fail_once(command):
            register = (((command >> 25) & 0x1F) << 8) | (command & 255)
            if register == 0x0315 and not command & (1 << 24) and not failed[0]:
                failed[0] = True
                raise IOError('injected denominator write failure')
            return original(command)
        client.transact = fail_once
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(IOError, 'denominator write'):
                self.run_plan(client, directory)
            result = json.loads((Path(directory) / 'result.json').read_text())
        self.assertFalse(result['applied'])
        self.assertEqual(result['automatic_rollback'], 'verified baseline restored')
        self.assertEqual(plan.join_bytes(client.registers, plan.NUM_ADDRS), plan.BASELINE_NUM)
        self.assertEqual(plan.join_bytes(client.registers, plan.DEN_ADDRS), plan.BASELINE_DEN)
        self.assertEqual(client.registers[0x013A], 6)
        self.assertEqual(client.page, 7)

    def test_wrong_baseline_refuses_without_clock_writes(self):
        client = self.client()
        client.registers[0x030D] ^= 1
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, 'baseline differs'):
                self.run_plan(client, directory)
        self.assertEqual(client.data_writes, [])
