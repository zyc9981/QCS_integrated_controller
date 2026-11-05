# QCS clock-control implementation results

Implemented a Python 3.8 host package at `Modular_Python_Controller/qcs_clock_control/`. It now contains a shared JSONL parser for TCP/file/stdin, a TCP receiver and synthetic sender, feedback controller, exact Si5341 N1 numerator arithmetic, dry-run path, and a restricted Vivado/VIO transaction backend. Existing `python_controller.py` and acquisition behavior are untouched.

## Safety boundary and current hardware state

Dry-run is the default. Live operation requires `--mode live`, `--allow-live-writes`, and a commissioning manifest with completed physical/vendor gates. The checked-in manifest template has `status=NOT COMMISSIONED` and fails closed. The current clock-audit evidence says N1 is unconfigured and OUT8 is powered down, so the backend cannot run against the present baseline. It never performs initial N1 activation, changes OUT8 enable/power, denominator, N0, shared PLL, or global reset. When later authorized, it verifies the Si5341 grade/revision, controller-idle signature, payload gate closed, exact static N1/OUT8 state and current numerator; then it stages only six N1 NUM bytes, verifies them, pulses `0x0317[0]`, and verifies the self-clearing latch/readback. It holds the project control lease, rejects competing Vivado/I²C users, uses the existing management VIO and mux-mask `0x40` path (the FPGA engine returns the mux to zero), and restores the original Si5341 page. A partial transaction latches the host actuator fault and is never reported as successfully applied.

No hardware transactions, clock activation/tuning, FPGA programming, instrument reconfiguration, or QSFP changes were performed for this implementation. Mock I²C transactions are software validation only.

## Measurement source and sign

The existing analyzer computes `epsilon_ps=(fit_center-T_calib)-(fit_rt_center-T_calib_rt)/2` in ps and uses the analysis-window midpoint as effective measurement time; the adaptive window starts at 0.1 s and can reach 1 s. The UI's separate live histogram uses a 500 ms integration. The existing estimator's epsilon sign has not been proven to equal `node-reference`, and propagation/path calibration is not established. It is rejected unless a producer sends the explicit mapping `offset = sign_multiplier × source_estimate − path_delay_correction` with calibration ID and `propagation_corrected` status.

Wire age uses sender `age_ms_at_send` plus UTC transit age and declared UTC uncertainty. Receiver and sender monotonic values are never compared; the accepted effective time is mapped onto local monotonic time. Sender/receiver UTC synchronization and truthful combined uncertainty are required. Old, future, stale, duplicate, out-of-order, poor-quality, uncalibrated, and wrong-pair records are rejected.

## Validation

- `/usr/bin/python3.8`: **22 tests passed**.
- Tests include both phase signs, drift direction, delay/age and stale rejection, duplicate sequence, command saturation and slew, dropouts/reacquisition, exact divider bytes, full TCP dry-run transaction, mock I²C writes/readback and update-bit behavior, commissioning-gate refusal, precondition mismatch, and injected partial transaction failure not reported as an applied correction.
- Actual CLI TCP demonstration: 3 mock measurements received and logged; sender completed successfully. No hardware backend was instantiated.
- Tcl bridge passed Tcl 8.6 completeness parsing; package passed Python 3.8 compileall.
- Existing simulation suite re-run. In the ideal constant +4 ppb / 1.5 ps noise scenario it reached a model-dependent 1.11 ps tail RMS and 2.08 ps absolute P95 after 153 s. Changing-drift/noisy and dropout scenarios ended at 2.29 ns and 498 ps tail RMS; they do not meet 1–5 ps. Those outcomes depend on the simplified controller/plant and are not physical clock performance.

## Required before physical feedback

1. Confirm the actual g² estimator channel mapping, sign, path-delay correction, effective midpoint and uncertainty, and export the declared calibrated wire record. The archived NPZ does not contain formal epsilon uncertainty or arrival time.
2. Complete N1→OUT8 commissioning: measure bank-71 VADJ, resolve OUT8 startup/shutdown transient behavior, validate the initial N1 activation sequence, and verify the diagnostic clock input. The existing audit reports these as outstanding; no live update can proceed until an approved manifest is created from real evidence/readbacks.
3. Tune/validate feedback gains, command latency, stability and frequency-step response against the installed clock after commissioning. Simulation is not a substitute for this physical tuning.
