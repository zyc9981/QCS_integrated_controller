# QCS clock discipline prototype (offline/shadow only)

This package is isolated from `python_controller.py` and the deployed acquisition path. It imports no HydraHarp, Swabian, Vivado, I²C, PCIe, or network-control interface. The only Si5341 code returns descriptive register-byte records; there is no method that sends commands. N1/OUT8 values are the **proposed, not commissioned** profile from the local commissioning package.

## Measurement contract and limits

The analyzer source is `../../../QCS_analyzer/qcs_analyzer/qcs_kernal.py` (sibling repository). In its time-dependent two-way estimator, each forward result is fitted in ps; `point_ps` is the midpoint of the analyzed window. It computes

`epsilon_ps = (fit_center_ps - T_calib) - (fit_rt_center_ps - T_calib_rt) / 2`.

The g² histogram implementation forms event differences as `t_B - t_A`; reversing channels reverses the peak sign. `epsilon` is in ps. Its sign is **not proven to be** `node_time-reference_time` until channel roles, calibration constants, optical/electrical path delays, and the selected clock pair are documented. The default calibration terms in the analyzer function are zero. Do not use a raw peak or default-calibrated epsilon as a clock offset without that mapping. The current kernel also updates `u0` from a fitted-center slope; that is an estimator skew, not by itself an actuator-ready command.

The kernel uses adaptive `Ta_s`: initial default 0.1 s, capped at 1 s. It timestamps each window at its center. The UI's separate live Time Tagger histogram has a default 500 ms integration and snapshots/clears after polling. Existing saved `/home/zyc/QCS/20261023_Deployed_test/010_1s.npz` contains a `data_dict` with `center`, `epsilon`, `tau`, `tau_rt`, `tau_ref`, `tau_ref_uncertainty`, `Ta`, `Ta_rt`, `sigma`, `sigma_rt`, and coincidence counts; `Ta` is 1 s for that file. It does **not** include result-arrival timestamps or a formal uncertainty for `epsilon`. The old archive's center values are floating-point ps. This package subtracts the first center before conversion to integer ns.

For real input, one JSONL/CSV row means one already-calibrated scalar offset for one explicitly named pair. Fields are integer `measurement_time_ns` and `arrival_time_ns` on a shared monotonic timeline, decimal-string `offset_ps`, `pair_id`, `valid`, `quality`, optional `uncertainty_ps`, and `offset_kind="calibrated_clock_offset"`. `measurement_time_ns` is the estimator's effective time (normally window midpoint); arrival is when the estimate became available. The contract refuses `raw_g2_peak` or uncalibrated epsilon. The NPZ adapter requires an explicit command-line assertion plus calibration/sign note, and makes the missing arrival-latency assumption visible in every exported row.

## Control law

Define `e = node_time - reference_time`, positive when node clock is ahead. The controller estimates free relative frequency by least-squares regression of `(measured offset - modeled applied phase)` over a sliding window. It predicts phase forward from effective measurement time to command time using the observed net slope, then requests the absolute fractional correction

`u = ((1 - e_pred/tau) / (1 + y_free) - 1)`,

where `tau` is phase-slew time and `y_free` is estimated free-running fractional frequency. Positive phase error requests a slower node. Rates compose multiplicatively. The output is saturated and rate-limited. It rejects invalid, wrong-pair, out-of-order, future, stale, and over-uncertainty records. Missing estimates hold the previous command; optional decay and long-gap reacquisition are configurable. Controller outputs are commands **requested** in shadow mode and do not imply they were applied.

## Simulated actuator and Si5341 math

The model tracks phase as an exact rational sum of fractional-rate × elapsed time, including multiplicative rate composition, command delay, and command quantization. The default simulation quantizer calls the exact Si5341 N1 numerator arithmetic for the proposed 20 MHz profile. N1 frequency is proportional to `1/NUM`: smaller numerator raises output frequency. Denominator and R divider remain fixed. The command record lists only numerator register byte values at `0x030D..0x0312` (top byte mask `0x0F`); it contains no update, activation, reset, or output-enable action.

Candidate constants are from `FPGA_HH_QSFP/clock_circuit_audit_20261101/commissioning/register_plan.json` and `commissioning/REGISTER_SEQUENCE.md`: proposed VCO 13,667,168,671.2 Hz, `NUM=1452136671315`, `DEN=4250000000`, `R8=2` → nominal 20 MHz. This profile remains uncommissioned and is only a mathematical reference.

## Commands (Python 3.8)

From the repository root:

```bash
PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m qcs_clock_control simulate \
  --out Modular_Python_Controller/qcs_clock_control/results

PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m qcs_clock_control shadow \
  Modular_Python_Controller/qcs_clock_control/examples/shadow_input.jsonl \
  --pair nodeA-nodeB --config Modular_Python_Controller/qcs_clock_control/examples/controller.json \
  --out Modular_Python_Controller/qcs_clock_control/results/shadow.jsonl

PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m qcs_clock_control replay \
  calibrated_offsets.jsonl --pair nodeA-nodeB --command-delay-s 0.25 \
  --out Modular_Python_Controller/qcs_clock_control/results/replay.jsonl
```

The example JSONL is explicitly synthetic and is not project measurement data. A closed-loop replay adjusts each recorded free-running offset by the accumulated simulated correction phase; it never feeds unchanged residuals back after pretending commands were applied.

To export the existing analyzer NPZ, NumPy is optional and needed only by this adapter. The command refuses to treat `epsilon` as a clock offset until the caller supplies the calibration/sign assertion:

```bash
PYTHONPATH=Modular_Python_Controller python3 -m qcs_clock_control npz-export \
  /home/zyc/QCS/20261023_Deployed_test/010_1s.npz \
  --offset-field epsilon --pair nodeA-nodeB --arrival-latency-ms 500 \
  --calibration-note 'REPLACE: state path-delay calibration and channel-to-node sign mapping' \
  --confirm-calibrated-clock-offset --out calibrated_offsets.jsonl
```

The 500 ms above is an example assumption, not an observed archive latency. Do not use the placeholder note or command before establishing calibration. Then use `shadow` or `replay` on that JSONL. Shadow/replay only read the source and write a separate output file.

## Validation

```bash
PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m unittest discover \
  -s Modular_Python_Controller/qcs_clock_control/tests -v
```

The tests cover correction sign, phase and drift direction, stale/future/quality/pair rejection, large absolute timestamps with ps differences, saturation/slew, holdover/reacquisition, delayed command timing, exact Si divider quantization and byte packing, closed-loop replay phase accumulation, and held-out deterministic simulations. Scenario outputs and SVG plots are under `results/` and all residual values there are model-dependent.
