# Clock-control prototype validation

## Source and measurement audit

- Correlation implementation: sibling source `QCS_analyzer/qcs_analyzer/qcs_kernal.py`, function `qcs_kernal_sep`, lines 820–856 (defaults), 984–1017 (window and midpoint), 1161–1235 (g² fit, epsilon and fit width), and 1248–1279 (slope estimate/state). The formula implemented is `epsilon=(fit_center-T_calib)-(fit_rt_center-T_calib_rt)/2`. `fit_center` is picoseconds; the time coordinate is the midpoint of a `Ta_s` window. `Ta_s_init=0.1s`, adapts to a 1s max in the shown function. Calibration defaults to zero. This establishes the estimator's formula and units, but not propagation cancellation or node/reference sign for the installed channel map.
- Current GUI histogram path: `Modular_Python_Controller/rx_commands.py`, lines 680–724 configures a default 500 ms integration; lines 740–753 snapshots then clears it. That path is a histogram display and does not produce the controller's calibrated offset record.
- Existing archive `/home/zyc/QCS/20261023_Deployed_test/010_1s.npz` contains `data_dict` with 998 samples, `Ta=Ta_rt=1s`, and `center` through 997 seconds of elapsed sample span. Its `epsilon` ranges 45.856 to 7760.707 ps; `tau_ref_uncertainty` is about 0.118–0.123 ps, but is **not** the uncertainty of `epsilon`. No formal epsilon uncertainty or arrival timestamp is stored. Calibration and channel-to-node sign provenance are absent from the archive. It is therefore not fed to the controller without an explicit calibration/sign assertion.
- No passive live estimate stream was found in the controller project. JSONL/CSV is the future passive input boundary; it does not start or reconfigure acquisition.

The input contract deliberately says `offset_kind=calibrated_clock_offset`; raw g² peaks and unverified `epsilon` are rejected. Measurement time is the acquisition's effective midpoint; arrival time is when the processing result becomes available. For an archived NPZ, the arrival delay must be supplied as an explicit assumption. All absolute software timestamps are integer nanoseconds and are differenced before conversion. Phase values are decimal picoseconds; regression first subtracts an offset origin in Decimal arithmetic.

## Implemented behavior

- Convention: `e=node-reference`, positive means the node is ahead. Positive phase error or positive free-running phase slope requests a negative frequency correction (slow the node).
- The controller performs an eight-sample least-squares drift estimate by default. It subtracts modeled applied phase from recorded offsets before estimating free-running drift; shadow mode passes zero applied phase because its hypothetical commands never affect hardware. Effective measurement age is propagated to current command time using observed net drift.
- Default correction law uses 20 s phase-slew time, 100,000 ppb absolute limit, 50,000 ppb per-update slew limit, 5 s max measurement age, and 1,000 ps max declared uncertainty. These are prototype starting values, not tuned/stability-certified gains. Invalid, wrong-pair, out-of-order, stale, future, and over-uncertainty inputs are rejected. Dropout holdover retains the last command unless configured to decay; a long measurement gap clears slope history for phase-only reacquisition.
- Simulated actuator accumulates rational phase at exact multiplicatively composed rates, applies delayed commands, and quantizes with the exact proposed Si5341 N1 numerator model. The scenario outputs keep hidden truth separate from noise and observations.
- Si command calculator uses proposed `VCO=13,667,168,671.2 Hz`, `NUM=1452136671315`, `DEN=4250000000`, `R8=2`. N1 numerator changes inversely with output frequency. It emits only the descriptive six numerator bytes (`0x030D`–`0x0312`, mask `0x0F` on the high byte); there is no U7 writer and no activation/update/reset/output-enable sequence.
- Closed-loop replay adds the model's cumulative applied correction phase to subsequent recorded free-running offsets. This avoids replaying the same unchanged offsets after simulated actuation.

## Python 3.8 validation

Run on the project-compatible interpreter:

```bash
PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m unittest discover \
  -s Modular_Python_Controller/qcs_clock_control/tests -v
```

Result: **12 tests passed**. Coverage includes sign and units, ps differences on large absolute timestamps, latency extrapolation, invalid/stale/future/pair/low-quality/uncertainty rejection, saturation and slew, holdover/reacquisition, delay/quantization, exact divider arithmetic/bytes/range, and cumulative correction in closed-loop replay. `compileall` also passed under `/usr/bin/python3.8`.

## Model runs (not hardware evidence)

Generated with:

```bash
PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m qcs_clock_control simulate \
  --out Modular_Python_Controller/qcs_clock_control/results
```

All residuals below are simulated. Each scenario uses 1 s nominal updates, 0.8 s acquisition, 0.15–0.45 s processing delay, 0.15–0.4 s command delay, the candidate N1 numerator quantizer, and reproducible random seeds. The tail statistics use the final 60 samples. Acquisition means first entry into ±5 ps for ten consecutive valid updates.

| Scenario | Open-loop final | Closed-loop final | Closed-loop tail RMS / abs P95 | First sustained ±5 ps |
|---|---:|---:|---:|---:|
| Initial +700 ps, +4 ppb, 1.5 ps noise, constant drift | +961,300 ps | -0.012 ps | 1.107 ps / 2.084 ps | 153.15 s |
| Drift changes +3 → -2.5 → +5 ppb; 3 ps noise; latency and irregular update | +547,966 ps | +272.426 ps | 2,293.861 ps / 4,828.721 ps | Not reached |
| -3 → +2 ppb drift; 2 ps noise; 15 s dropout and reacquisition | -299,200 ps | +57.817 ps | 497.514 ps / 1,035.612 ps | Not reached |

The first idealized case meets a 1–5 ps residual scale in this model; the changing-drift/noisy and dropout cases do not. This does not establish actual QCS uncertainty, closed-loop stability on the board, clock actuator performance, or physical 1–5 ps synchronization. The figures are [`constant_offset_and_frequency.svg`](results/constant_offset_and_frequency.svg), [`changing_drift_noise_and_latency.svg`](results/changing_drift_noise_and_latency.svg), and [`dropout_and_reacquisition.svg`](results/dropout_and_reacquisition.svg). CSVs retain truth, noisy input, controller estimate, measurement age, requested/quantized command, and residual by update; `metrics.json` is the machine-readable summary.

## Remaining integration work

1. Add an export point in the existing estimator that records effective midpoint, result arrival time, `epsilon` and its propagated uncertainty, calibration terms, channel mapping, and clock-pair identity without altering acquisition defaults.
2. Establish whether the chosen two-way `epsilon` is propagation compensated for the actual pair and map its sign to `node-reference`. Characterize estimator latency and valid/quality criteria from actual fit results.
3. Validate loop stability with measured noise, delay/jitter, actuator resolution and clock dynamics. A future hardware-writing backend and U7 commissioning require separate approval after the documented electrical/clock commissioning blockers are cleared; neither exists here.

Nothing in this package changed `python_controller.py`, estimator code, instrument settings, FPGA state, U7, QSFP controls, or the deployed clock image.
