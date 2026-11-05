import json
import contextlib
import io
import tempfile
import threading
import time
import unittest
from pathlib import Path

from qcs_clock_control.actuator import (ActuatorError, MockI2CDevice, NUM_ADDRS,
                                        PartialClockWrite, Si5341N1Actuator)
from qcs_clock_control.network import (MeasurementReceiver, decode_wire_line,
                                       make_wire_measurement, serve_jsonl)
from qcs_clock_control.node import run_node
from qcs_clock_control.si5341_math import Si5341N1Model


def commissioned_state():
    regs = {0x0130: 0x06, 0x0131: 0x09, 0x0132: 0x33, 0x0133: 0x09,
            0x0313: 0x80, 0x0314: 0xDA, 0x0315: 0x51, 0x0316: 0xFD,
            0x0A03: 0x03, 0x0A04: 0x01, 0x0A05: 0x03, 0x0B4A: 0x1C}
    nominal = 1452136671315
    for i, address in enumerate(NUM_ADDRS):
        regs[address] = (nominal >> (8*i)) & 0xff
    return regs


def manifest_dict(regs):
    return {"status": "commissioned", "approval_id": "test-only", "device": "Si5341 Rev D",
            "target_serial": "210249AE83E1",
            "output_path": "N1->OUT8->bank71", "nominal_numerator": 1452136671315,
            "numerator": 1452136671315, "denominator": 4250000000, "r_divider": 2,
            "physical_preconditions": {"vadj_1v8_verified": True,
                "out8_transient_approved": True, "n1_activation_vendor_validated": True,
                "diagnostic_clock_verified": True},
            "expected_registers": {"0x%04X" % k: "0x%02X" % v for k, v in regs.items()}}


class WireInputTests(unittest.TestCase):
    def test_wire_time_reconstructed_locally_and_sign_kept(self):
        mono, utc = 9_000_000_000, 1_800_000_000_000_000_000
        obj = make_wire_measurement("A", "B", 7, "25.125", 12.0,
                                    now_utc_ns=utc-3_000_000)
        line = json.dumps(obj)
        record = decode_wire_line(line, mono, utc, max_clock_uncertainty_ms=1)
        self.assertEqual(record.pair_id, "A-B")
        self.assertEqual(str(record.offset_ps), "25.125")
        self.assertEqual(record.measurement_time_ns, mono-15_100_000)

    def test_optional_acquisition_interval_maps_to_local_monotonic(self):
        mono, utc = 9_000_000_000, 1_800_000_000_000_000_000
        obj = make_wire_measurement("A", "B", 8, 25, 100,
                                    now_utc_ns=utc-3_000_000,
                                    acquisition_interval_ms=40)
        record = decode_wire_line(json.dumps(obj), mono, utc)
        self.assertEqual(record.acquisition_end_ns-record.acquisition_start_ns, 40_000_000)
        self.assertEqual(record.measurement_time_ns,
                         (record.acquisition_start_ns+record.acquisition_end_ns)//2 - 100_000)

    def test_uncalibrated_future_and_duplicate_rejected(self):
        now = 1_800_000_000_000_000_000
        bad = make_wire_measurement("A", "B", 0, 1, 0, now_utc_ns=now)
        bad["offset_kind"] = "raw_g2_peak"
        with self.assertRaisesRegex(ValueError, "uncalibrated"):
            decode_wire_line(json.dumps(bad), 100, now)
        future = make_wire_measurement("A", "B", 1, 1, 0, now_utc_ns=now+10_000_000)
        with self.assertRaisesRegex(ValueError, "future"):
            decode_wire_line(json.dumps(future), 100, now)
        accepted = make_wire_measurement("A", "B", 2, 1, 0, now_utc_ns=now)
        receiver = MeasurementReceiver(lambda r, o: {"status": "accepted"})
        receiver.process_line(json.dumps(accepted), 100, now)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            receiver.process_line(json.dumps(accepted), 200, now+1)

    def test_hmac_authentication(self):
        key = b"test-secret"
        now = 1_800_000_000_000_000_000
        signed = make_wire_measurement("A", "B", 0, "12", 0,
                                       now_utc_ns=now, auth_token=key)
        parsed = decode_wire_line(json.dumps(signed), 100, now,
                                  auth_token=key, require_auth=True)
        self.assertEqual(str(parsed.offset_ps), "12")
        signed["offset_ps"] = "13"
        with self.assertRaisesRegex(ValueError, "authentication_failed"):
            decode_wire_line(json.dumps(signed), 100, now,
                              auth_token=key, require_auth=True)
        with self.assertRaisesRegex(ValueError, "authentication_required"):
            decode_wire_line(json.dumps(make_wire_measurement("A", "B", 1, 12, 0,
                                                               now_utc_ns=now)),
                              100, now, auth_token=key, require_auth=True)


class HardwareActuatorTests(unittest.TestCase):
    def _make_actuator(self, device, regs):
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(manifest_dict(regs), handle)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Si5341N1Actuator(handle.name, device)

    def test_actual_mock_i2c_byte_writes_update_and_readback(self):
        regs = commissioned_state()
        device = MockI2CDevice(regs)
        actuator = self._make_actuator(device, regs)
        verified = actuator.verify()
        self.assertTrue(verified["acknowledged"])
        actual = actuator.apply(1000)  # +1 ppm; N numerator decreases
        self.assertTrue(actual["applied"])
        self.assertEqual(actual["status"], "applied_and_readback_verified")
        self.assertLess(actuator.current_num, 1452136671315)
        self.assertEqual([a for a, _ in device.writes], list(NUM_ADDRS)+[0x0317])
        self.assertEqual(device.latched_num, actuator.current_num)
        self.assertTrue(all(regs[a] == device.registers[a] for a in
                            (0x0130, 0x0131, 0x0132, 0x0133, 0x0313, 0x0314,
                             0x0315, 0x0316, 0x0A03, 0x0A04, 0x0A05, 0x0B4A)))
        restarted = self._make_actuator(device, regs)
        restarted.verify()
        self.assertEqual(restarted.current_num, actuator.current_num)

    def test_incomplete_manifest_and_transaction_failure_not_applied(self):
        regs = commissioned_state()
        device = MockI2CDevice(regs, fail_after=len(regs)+3)
        actuator = self._make_actuator(device, regs)
        before = actuator.current_num
        with self.assertRaises(PartialClockWrite):
            actuator.apply(-1000)
        self.assertEqual(actuator.current_num, before)
        self.assertTrue(actuator.faulted)
        with self.assertRaises(ActuatorError):
            actuator.apply(0)

        path = Path(__file__).parents[1] / "examples/commissioned_manifest.template.json"
        with self.assertRaisesRegex(ActuatorError, "completed commissioning"):
            Si5341N1Actuator(str(path), MockI2CDevice(regs))

    def test_wrong_initial_state_refuses_before_any_write(self):
        regs = commissioned_state()
        changed = dict(regs, **{})
        changed[0x0A03] = 1
        device = MockI2CDevice(changed)
        actuator = self._make_actuator(device, regs)
        with self.assertRaises(ActuatorError):
            actuator.apply(100)
        self.assertEqual(device.writes, [])

    def test_failed_hardware_write_is_not_reported_as_applied(self):
        regs = commissioned_state()
        device = MockI2CDevice(regs, fail_after=len(regs)+3)
        actuator = self._make_actuator(device, regs)
        callback = run_node(None, "A-B", Si5341N1Model("13667168671.2", 1452136671315,
                                                        4250000000, 2),
                            "live", actuator=actuator)
        receiver = MeasurementReceiver(callback)
        wire = make_wire_measurement("A", "B", 0, 1000, 0)
        with contextlib.redirect_stdout(io.StringIO()):
            result = receiver.process_line(json.dumps(wire))
        callback.close()
        self.assertEqual(result["status"], "actuation_failed")
        self.assertEqual(result["actuator_result"], "failed_not_applied")
        self.assertNotIn("applied_correction_ppb", result)


class EndToEndNodeTests(unittest.TestCase):
    def test_tcp_measurement_drives_controller_and_dry_run_command(self):
        model = Si5341N1Model("13667168671.2", 1452136671315, 4250000000, 2)
        callback = run_node(None, "A-B", model, "dry-run")
        receiver = MeasurementReceiver(callback)
        stop = threading.Event()
        server_ready = []
        # Bind on a known ephemeral port ourselves because serve_jsonl runs its
        # accept loop in the thread and returns only when stopped.
        import socket
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        thread = threading.Thread(target=serve_jsonl,
                                  args=("127.0.0.1", port, receiver, stop))
        thread.start()
        time.sleep(0.05)
        import socket as socket_module
        with contextlib.redirect_stdout(io.StringIO()):
            with socket_module.create_connection(("127.0.0.1", port), timeout=2) as sock:
                stream = sock.makefile("rwb", buffering=0)
                wire = make_wire_measurement("A", "B", 0, "1000", 0,
                                             utc_uncertainty_ms=0.1)
                stream.write((json.dumps(wire) + "\n").encode())
                response = json.loads(stream.readline())
        stop.set()
        thread.join(2)
        callback.close()
        self.assertEqual(response["status"], "accepted")
        result = response["result"]
        self.assertEqual(result["actuator_result"], "simulated_only_not_hardware_applied")
        self.assertLess(float(result["requested_correction_ppb"]), 0.0)
        self.assertTrue(result["divider_command"]["registers"])

    def test_tcp_to_controller_to_mock_live_actuator(self):
        regs = commissioned_state()
        device = MockI2CDevice(regs)
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(manifest_dict(regs), handle)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        actuator = Si5341N1Actuator(handle.name, device)
        actuator.verify()
        callback = run_node(None, "A-B", Si5341N1Model("13667168671.2", 1452136671315,
                                                        4250000000, 2),
                            "live", actuator=actuator)
        receiver = MeasurementReceiver(callback)
        wire = make_wire_measurement("A", "B", 0, 1000, 20)
        with contextlib.redirect_stdout(io.StringIO()):
            result = receiver.process_line(json.dumps(wire))
        callback.close()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["actuator_result"], "applied_and_readback_verified")
        self.assertEqual(device.latched_num, actuator.current_num)
        self.assertEqual([a for a, _ in device.writes], list(NUM_ADDRS)+[0x0317])


if __name__ == "__main__":
    unittest.main()
