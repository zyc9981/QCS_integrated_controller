import json
import tempfile
import unittest
from pathlib import Path

from qcs_clock_control.controller import ClockController, ControllerConfig
from qcs_clock_control.records import MeasurementRecord
from qcs_clock_control.si5341_math import Si5341N1Model
from qcs_clock_control.simulation import SimulatedClockActuator, run_scenario
from qcs_clock_control.shadow import replay_closed_loop
from qcs_clock_control.npz_adapter import export_qcs_npz


class ControllerTests(unittest.TestCase):
    def record(self, t, arrival, e, **kwargs):
        return MeasurementRecord(t, arrival, str(e), "pair", uncertainty_ps="1", **kwargs)

    def test_sign_of_phase_and_drift_corrections(self):
        ctl = ClockController(ControllerConfig(pair_id="pair", phase_slew_tau_s=10,
                                               max_command_slew_ppb_per_update=1e9))
        first = ctl.update(self.record(0, 0, 1000))
        self.assertLess(first["command_ppb"], 0)  # positive node lead => slow node
        second = ctl.update(self.record(1000000000, 1000000000, 2000))
        self.assertGreater(second["estimated_drift_ppb"], 0.0)  # positive e slope
        self.assertLess(second["command_ppb"], -0.001)
        behind = ClockController(ControllerConfig(pair_id="pair", phase_slew_tau_s=10,
                                                 max_command_slew_ppb_per_update=1e9))
        positive = behind.update(self.record(0, 0, -1000))
        self.assertGreater(positive["command_ppb"], 0.0)  # negative offset => speed node up

    def test_measurement_latency_prediction_and_stale_rejection(self):
        ctl = ClockController(ControllerConfig(pair_id="pair", max_measurement_age_s=2,
                                               phase_slew_tau_s=10,
                                               max_command_slew_ppb_per_update=1e9))
        ctl.update(self.record(0, 0, 0))
        ctl.update(self.record(1000000000, 1000000000, 1000))
        delayed = ctl.update(self.record(2000000000, 3000000000, 2000), now_ns=3000000000)
        self.assertAlmostEqual(delayed["measurement_age_ms"], 1000.0)
        self.assertGreater(delayed["estimated_offset_ps"], 2000)
        stale = ctl.update(self.record(3000000000, 7000000000, 3000), now_ns=7000000000)
        self.assertEqual(stale["status"], "rejected_stale")

    def test_quality_pair_valid_and_offset_kind_rejections(self):
        ctl = ClockController(ControllerConfig(pair_id="pair", max_uncertainty_ps=5))
        bad = MeasurementRecord(0, 0, 0, "pair", uncertainty_ps=10)
        self.assertEqual(ctl.update(bad)["status"], "rejected_quality")
        wrong = MeasurementRecord(1, 1, 0, "other")
        self.assertEqual(ctl.update(wrong)["status"], "rejected_pair")
        invalid = MeasurementRecord(2, 2, 0, "pair", valid=False)
        self.assertEqual(ctl.update(invalid)["status"], "rejected_invalid")
        low_quality = MeasurementRecord(3, 3, 0, "pair", quality="poor")
        self.assertEqual(ctl.update(low_quality)["status"], "rejected_quality")
        with self.assertRaises(ValueError):
            MeasurementRecord(0, 0, 0, "pair", offset_kind="raw_g2_peak")

    def test_saturation_slew_and_holdover(self):
        ctl = ClockController(ControllerConfig(pair_id="pair", max_correction_ppb=2,
                                               max_command_slew_ppb_per_update=0.5))
        r = ctl.update(self.record(0, 0, 1000000000))
        self.assertAlmostEqual(r["command_ppb"], -0.5)
        # A proposed command must not become the slew reference until the
        # actuator (or simulated actuator) acknowledges it.
        ctl.confirm_applied(r["command_ppb"])
        h = ctl.holdover(100)
        self.assertAlmostEqual(h["command_ppb"], -0.5)
        saturated = ClockController(ControllerConfig(pair_id="pair", max_correction_ppb=2,
                                                      max_command_slew_ppb_per_update=100))
        sr = saturated.update(self.record(0, 0, 1000000000))
        self.assertAlmostEqual(sr["command_ppb"], -2.0)

    def test_reacquisition_discards_old_drift(self):
        ctl = ClockController(ControllerConfig(pair_id="pair", reacquire_after_s=2,
                                               max_command_slew_ppb_per_update=1e9))
        ctl.update(self.record(0, 0, 0))
        ctl.update(self.record(1000000000, 1000000000, 100000))
        result = ctl.update(self.record(5000000000, 5000000000, 100000), now_ns=5000000000)
        self.assertIsNone(result["estimated_drift_ppb"])
        self.assertEqual(result["mode"], "acquiring")

    def test_large_absolute_timestamps_keep_small_ps_differences(self):
        ctl = ClockController(ControllerConfig(pair_id="pair", drift_window=4))
        epoch = 1800000000000000000
        ctl.update(self.record(epoch, epoch, "1000000000000000.0"))
        result = ctl.update(self.record(epoch + 1000000000, epoch + 1000000000,
                                       "1000000000000001.0"))
        self.assertAlmostEqual(result["estimated_drift_ppb"], 0.001, places=8)


class DividerAndPlantTests(unittest.TestCase):
    def setUp(self):
        self.model = Si5341N1Model("13667168671.2", 1452136671315, 4250000000, 2)

    def test_si_numerator_inverse_and_bytes(self):
        nominal = self.model.describe(0)
        plus = self.model.describe(1000)  # +1 ppm output
        minus = self.model.describe(-1000)
        self.assertEqual(nominal["numerator"], 1452136671315)
        self.assertLess(plus["numerator"], nominal["numerator"])
        self.assertGreater(minus["numerator"], nominal["numerator"])
        self.assertEqual([r["address"] for r in plus["registers"]],
                         ["0x030D", "0x030E", "0x030F", "0x0310", "0x0311", "0x0312"])
        self.assertEqual(plus["registers"][-1]["mask"], "0x0F")
        self.assertLess(abs(plus["representable_correction_ppb"] - 1000), 0.001)
        self.assertEqual(plus["activation_or_reset_operations"], [])
        self.assertAlmostEqual(float(self.model.nominal_hz), 20000000.0, places=6)
        with self.assertRaises(ValueError):
            self.model.describe(1e12)  # would take N1 outside valid divider range

    def test_npz_archive_is_not_assumed_to_be_calibrated(self):
        with self.assertRaisesRegex(ValueError, "refusing raw/unverified"):
            export_qcs_npz("not-opened.npz", "not-created.jsonl", "pair", "epsilon",
                           500, "", confirmed_calibrated_clock_offset=False)

    def test_simulated_delayed_command_and_exact_rate(self):
        plant = SimulatedClockActuator(initial_offset_ps=0, free_ppb=1,
                                       command_delay_s=1, command_quantum_ppb="0.001")
        plant.advance_to(1000000000)
        self.assertAlmostEqual(float(plant.phase_ps), 1000.0, places=6)
        plant.request(-1, plant.time_ns)
        plant.advance_to(2000000000)
        self.assertAlmostEqual(float(plant.phase_ps), 2000.0, places=5)
        plant.advance_to(3000000000)
        # The command takes effect at t=2 s and cancels the free +1 ppb rate.
        self.assertAlmostEqual(float(plant.phase_ps), 2000.0, places=5)

    def test_closed_loop_improves_held_out_constant_drift(self):
        rows, metrics = run_scenario("held_out", duration_s=180, initial_offset_ps=300,
                                     free_ppb=2.0, noise_sigma_ps=0.5,
                                     seed=919, command_delay_s=0.15)
        self.assertLess(metrics["closed_loop_tail_rms_ps"], metrics["open_loop_tail_rms_ps"])
        self.assertGreater(len(rows), 100)

    def test_noisy_change_dropout_scenario_is_reproducible_and_has_holdover(self):
        kw = dict(duration_s=90, initial_offset_ps=100, free_ppb=1,
                  noise_sigma_ps=1.0, dropout_ranges=[(30, 35)], seed=81)
        rows1, m1 = run_scenario("short", **kw)
        rows2, m2 = run_scenario("short", **kw)
        self.assertEqual(m1, m2)
        self.assertGreater(m1["dropout_updates"], 0)

    def test_closed_loop_replay_accumulates_model_corrections(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "offsets.jsonl"
            output = Path(temp) / "replay.jsonl"
            with source.open("w") as stream:
                for i, offset in enumerate((100, 1100, 2100, 3100)):
                    rec = MeasurementRecord(i * 1000000000, i * 1000000000 + 100000000,
                                            offset, "pair")
                    stream.write(json.dumps(rec.to_dict()) + "\n")
            model = Si5341N1Model("13667168671.2", 1452136671315, 4250000000, 2)
            summary = replay_closed_loop(str(source), str(output), "pair", model)
            self.assertEqual(summary["accepted"], 4)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertTrue(rows[-1]["model_dependent_replay"])
            self.assertNotEqual(rows[-1]["simulated_correction_phase_ps"], "0")


if __name__ == "__main__":
    unittest.main()
