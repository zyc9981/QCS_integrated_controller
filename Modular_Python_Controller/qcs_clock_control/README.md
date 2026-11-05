# QCS clock control node

This package is isolated from `python_controller.py` and the deployed acquisition path. It does not change HydraHarp/Swabian acquisition code. Default operation is **dry-run**. A separately gated Vivado/VIO Si5341 writer is included for use only after N1→OUT8 has been commissioned. No hardware write, clock activation, FPGA programming, or instrument reconfiguration was performed while implementing or validating it. The current audit baseline has N1 numerator/denominator zero and OUT8 disabled, so live mode must refuse to initialize.

## Measurement contract and limits

The analyzer source is `../../../QCS_analyzer/qcs_analyzer/qcs_kernal.py` (sibling repository). In its time-dependent two-way estimator, each forward result is fitted in ps; `point_ps` is the midpoint of the analyzed window. It computes

`epsilon_ps = (fit_center_ps - T_calib) - (fit_rt_center_ps - T_calib_rt) / 2`.

The g² histogram implementation forms event differences as `t_B - t_A`; reversing channels reverses the peak sign. `epsilon` is in ps. Its sign is **not proven to be** `node_time-reference_time` until channel roles, calibration constants, optical/electrical path delays, and the selected clock pair are documented. The default calibration terms in the analyzer function are zero. Do not use a raw peak or default-calibrated epsilon as a clock offset without that mapping. The current kernel also updates `u0` from a fitted-center slope; that is an estimator skew, not by itself an actuator-ready command.

The kernel uses adaptive `Ta_s`: initial default 0.1 s, capped at 1 s. It timestamps each window at its center. The UI's separate live Time Tagger histogram has a default 500 ms integration and snapshots/clears after polling. Existing saved `/home/zyc/QCS/20261023_Deployed_test/010_1s.npz` contains a `data_dict` with `center`, `epsilon`, `tau`, `tau_rt`, `tau_ref`, `tau_ref_uncertainty`, `Ta`, `Ta_rt`, `sigma`, `sigma_rt`, and coincidence counts; `Ta` is 1 s for that file. It does **not** include result-arrival timestamps or a formal uncertainty for `epsilon`. The old archive's center values are floating-point ps. This package subtracts the first center before conversion to integer ns.

TCP JSONL uses protocol `qcs-offset-v1`: `node_id`, `reference_id`, monotonic `sequence`, `pair_id="node_id-reference_id"`, decimal-string `offset_ps`, `offset_kind="calibrated_clock_offset"`, `sign_convention="node_time_minus_reference_time"`, `valid`, `quality`, optional `uncertainty_ps`, `effective_time_utc_ns`, `sent_utc_ns`, `age_ms_at_send`, `utc_uncertainty_ms`, `timebase="utc_epoch_ns"`, and calibration fields `status="propagation_corrected"`, `calibration_id`, `source_estimate_ps`, `epsilon_sign_multiplier` (+1 or −1), and signed `path_delay_correction_ps`. The receiver verifies `offset_ps = sign_multiplier × source_estimate_ps − path_delay_correction_ps`. Optional `acquisition_start_utc_ns` and `acquisition_end_utc_ns` carry the integration interval; when present they must bracket the effective time (normally the g² window midpoint). The existing estimator exposes the window length `Ta`; arrival is receiver-stamped when the record arrives. The producer must establish the channel polarity and propagation/path correction before setting the calibration status. The existing analyzer's `epsilon` does **not** yet have an established sign/path calibration and must not be sent as calibrated until that mapping is resolved. For live mode each JSON object must also include `auth_hmac_sha256`, an HMAC-SHA256 over canonical sorted compact JSON excluding that field, using a shared token file; dry-run accepts unsigned input. HMAC authenticates messages but does not encrypt the TCP stream.

The receiver never compares sender and local monotonic clocks. It computes age from sender age-at-send plus UTC transit age (including declared UTC uncertainty), rejects stale records and unsynchronized UTC, then maps effective time to a receiver-local monotonic timestamp by subtracting age from local receive-monotonic time. Thus sender and receiver UTC must be synchronized within their declared bounds. Duplicate and out-of-order sequence numbers are rejected for each node/reference pair. File/stdin input uses the same wire parser via `consume-wire`.

## Control law

Define `e = node_time - reference_time`, positive when node clock is ahead. The controller estimates free relative frequency by least-squares regression of `(measured offset - modeled applied phase)` over a sliding window. It predicts phase forward from effective measurement time to command time using the observed net slope, then requests the absolute fractional correction

`u = ((1 - e_pred/tau) / (1 + y_free) - 1)`,

where `tau` is phase-slew time and `y_free` is estimated free-running fractional frequency. Positive phase error requests a slower node. Rates compose multiplicatively. The output is saturated and rate-limited. It rejects invalid, wrong-pair, out-of-order, future, stale, and over-uncertainty records. Missing estimates hold the previous command; optional decay and long-gap reacquisition are configurable. A proposal changes the slew reference only after the actuator acknowledges it. Failed I²C transactions are surfaced as failed actuation and never logged as a successful adjustment.

## Simulated actuator and Si5341 math

The model tracks phase as an exact rational sum of fractional-rate × elapsed time, including multiplicative rate composition, command delay, and command quantization. The default simulation quantizer calls the exact Si5341 N1 numerator arithmetic for the proposed 20 MHz profile. N1 frequency is proportional to `1/NUM`: smaller numerator raises output frequency. Denominator and R divider remain fixed. Live operation stages only `0x030D..0x0312`, verifies bytes, then pulses only `0x0317[0]`; it never activates N1/OUT8, changes denominator/N0/shared PLL/global reset, or changes output enables. Transactions use the existing controller management VIO, U7 address `0x77`, mux mask `0x40` with the controller's mux-to-zero behavior, and restore the original chip page. They do not program the FPGA. Live mode requires explicit command-line opt-in, a commissioning manifest with all hardware gates approved, a fresh identity/readback check, exclusive JTAG/I²C access and a closed controller payload gate. The checked-in manifest template is uncommissioned and fails closed.

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

Start a local dry-run node (terminal 1), then a synthetic sender (terminal 2):

```bash
PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m qcs_clock_control listen \
  --bind 127.0.0.1 --port 9876 --pair nodeA-nodeB --mode dry-run \
  --log Modular_Python_Controller/qcs_clock_control/results/node_demo.jsonl

PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m qcs_clock_control mock-server \
  --host 127.0.0.1 --port 9876 --node nodeA --reference nodeB \
  --count 5 --interval-s 1 --initial-offset-ps 1000 --drift-ppb 1
```

For real distributed input, bind to `0.0.0.0` or the selected interface and send the same JSONL wire format to that TCP port. `mock-server` is a synthetic test sender. File or stdin input:

```bash
PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m qcs_clock_control consume-wire measurements.jsonl --pair nodeA-nodeB
cat measurements.jsonl | PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m qcs_clock_control consume-wire - --pair nodeA-nodeB
```

Once N1→OUT8 is commissioned, the live command is:

```bash
PYTHONPATH=Modular_Python_Controller /usr/bin/python3.8 -m qcs_clock_control listen \
  --bind 0.0.0.0 --port 9876 --pair nodeA-nodeB --mode live \
  --allow-live-writes \
  --auth-token-file /secure/path/qcs_clock_hmac.key \
  --commissioning-manifest /path/to/completed_n1_out8_commissioning.json \
  --log Modular_Python_Controller/qcs_clock_control/results/node_live.jsonl
```

This is expected to refuse with the current hardware state. Complete clock-path commissioning first: physically measure bank-71 VADJ, approve OUT8 startup/shutdown transient behavior, validate the initial N1 activation sequence, and verify the diagnostic clock input. Create a strong shared token outside the repository (for example `umask 077; openssl rand -hex 32 > /secure/path/qcs_clock_hmac.key`) and copy it securely to both hosts. Do not modify the example manifest to bypass these checks; create a fresh commissioning record with actual readbacks and approvals.

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

The tests cover both correction directions, phase/frequency drift, stale/future/quality/pair and duplicate rejection, HMAC, large absolute timestamps with ps differences, saturation/slew, holdover/reacquisition, delayed command timing, exact Si divider quantization and byte packing, TCP dry-run and TCP-to-mock-live-I²C, write/readback/update and failure paths, closed-loop replay phase accumulation, and held-out deterministic simulations. Scenario outputs and SVG plots are under `results/`; all residual values there are model-dependent.
