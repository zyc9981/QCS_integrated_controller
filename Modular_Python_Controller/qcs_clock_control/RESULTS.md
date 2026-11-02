# Host clock-control prototype — results

Implemented an isolated, runnable host package at `Modular_Python_Controller/qcs_clock_control/`. It supports deterministic simulation, JSONL/CSV read-only shadow input, model-dependent closed-loop replay, and a descriptive-only Si5341 N1 numerator calculator. It has no hardware-writing path and is not imported by `python_controller.py`; current acquisition behavior is unchanged.

## Measurement source and limits

The existing analyzer's time-dependent two-way estimate is `epsilon_ps=(fit_center-T_calib)-(fit_rt_center-T_calib_rt)/2` in ps. Its measurement time is based on the analyzed window midpoint; the adaptive window starts at 0.1 s and can reach 1 s. The GUI-only histogram display separately uses a default 500 ms integration. The estimator's `epsilon` sign has not been proven to match `node_time-reference_time` for this clock pair, and its default calibration terms are zero. It can still include path-delay terms.

The real saved `/home/zyc/QCS/20261023_Deployed_test/010_1s.npz` has 998 one-second `epsilon` samples, but no result-arrival timestamp or formal epsilon uncertainty; the available `tau_ref_uncertainty` is not epsilon uncertainty. Calibration/sign provenance is absent. The package's NPZ exporter therefore requires an explicit calibration assertion and makes any arrival-time assumption visible. I ran no actual-data shadow commands because the saved field is not yet demonstrated to satisfy the clock-offset contract. No passive live-estimate stream was found.

## Validation

- Python 3.8.10 interpreter: **12 unit tests passed**; package `compileall` passed.
- Sign/latency/rejection, large-timestamp ps precision, saturation/slew, holdover/reacquisition, command delay/quantization, N1 rational math/register bytes/range, and corrected-offset replay are tested.
- Synthetic shadow input and closed-loop replay both ran. The shadow example is explicitly illustrative, not measured data.
- Model simulations and SVG figures are saved under `results/`; the constant-drift scenario reached a simulated 1.1 ps tail RMS and 2.1 ps absolute P95 after 153 s. Under drift changes/noise, the tail RMS was 2.29 ns; with dropout/reacquisition it was 498 ps. These are conditional model results and do not establish board performance. See `VALIDATION.md` for scenario parameters and detailed metrics.

## Next integration gates

1. Record `measurement_time`, result arrival time, estimate, fit uncertainty/quality, pair ID, channel mapping and calibration provenance from the actual analyzer.
2. Validate that the chosen calibrated estimate is propagation-corrected and map its sign to `node-reference`.
3. Tune/validate the controller with measured noise, latency and real actuator dynamics. N1/OUT8 remains uncommissioned, so every Si5341 register record is hypothetical.

No hardware, clock, instruments, QSFP, FPGA, existing acquisition source, or deployed bitstream was changed.
