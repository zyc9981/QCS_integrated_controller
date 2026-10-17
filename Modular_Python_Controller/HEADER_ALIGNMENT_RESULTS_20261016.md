# Receiver header/alignment recovery — 2026-10-16

## Finding

The long OFF/ON delay occurs mainly **before the receiver obtains a consistently
alignable header stream**. The FPGA is actively searching during that interval:
its RX clock runs, header-valid indications arrive, about half the available
headers are illegal initially, and the gearbox repeatedly slips alignment.
This differs from an idle software delay or a fixed Aurora handshake wait.

These digital observations do **not** distinguish laser settling, module receiver
or retimer acquisition, GTY analog CDR acquisition, and other transient signal
impairments. They do not establish that Aurora alone causes the delay or that a
particular analog component takes a fixed 9 ms.

## Run and conditions

Results directory:
`FPGA_HH_QSFP/burst_guard/measurements/20261016_124018_009589/`

The current fibers, delay, and attenuation were retained. The requested dark or
reset hold was 1,000 ms, with additional I2C/JTAG sequencing time. Optical dark
interval and turn-on power were not measured. Guard deadline: 20,000 us.
Each trial sent 8,192 64-bit words after the deadline, with the FPGA checking the
received pattern. This diagnostic uses no PCIe or XDMA.

| Condition | Trials | Intact payloads | Both-channel ready, median | Observed range |
| --- | ---: | ---: | ---: | ---: |
| Continuously illuminated baseline | 3 | 3 | Already ready | Already ready |
| Laser OFF/ON, no explicit Aurora reset | 5 | 5 | 5.668 ms | 5.220–10.798 ms |
| Light ON, Aurora reset | 5 | 5 | 0.319 ms | 0.318625–0.318635 ms |
| Light ON, receiver + Aurora reset | 5 | 5 | 0.689 ms | 0.682–0.787 ms |

The control timings in this table use the engine's guard origin after arm
acknowledgments. `startup_timing.csv` records signal edges relative to explicit
reset release or, for bursts, QSFP3's TX-enable I2C STOP. The difference is small
but the two origins should not be treated as exactly identical.

All 18 payloads were intact: 1,179,648 bytes compared. Some startup soft-error
flags were latched. This finite payload sample at a 20 ms guard does not establish
zero physical BER, validate shorter guards, or provide a deployment margin.

Slow DOM readback: QSFP3 TX2 +0.83 dBm; QSFP4 RX2 −9.08 dBm, giving an approximate
forward loss of 9.90 dB. DOM is not a fast settling measurement and has calibration
uncertainty.

## What the new counters showed

Counters run in each native RX clock domain and are sampled into 100 us windows.
For the forward receiver, QSFP4:

- Across the first millisecond of the five OFF/ON trials, 49.07% of available
  headers were illegal. There were 90,461 gearbox-slip edges in those five
  combined 1 ms intervals.
- The first complete 100 us window with available headers and **zero illegal
  headers** ended at 4.4, 4.6, 4.8, 5.6, or 9.7 ms. These are window bounds,
  not exact analog settling times.
- Total slip counts per OFF/ON trial were 75,011–163,084. In the continuously
  illuminated Aurora-only reset controls, there were no slips or illegal
  headers in the captured windows.
- No complete 100 us window had a stopped native RX clock in any trial.
  Partial-window reset effects remain visible in the counts.
- The receiver-only reset controls recovered quickly while light stayed on;
  their forward receivers needed just 25–51 gearbox slips per trial.

### Representative OFF/ON trial: id 3

| Time after QSFP3 enable STOP | Observation at QSFP4 |
| --- | --- |
| First several milliseconds | RX clock running; mostly invalid alignment; repeated gearbox slips |
| 5.5–5.6 ms window | 39,060 available headers, zero illegal headers, zero slips |
| 5.7637 ms | Existing Aurora CDR/reset FSM requests its automatic RX restart |
| 6.1333 ms | Native RX reset-done returns high |
| 6.4412 ms | Block synchronization is stable again |
| 6.4414 ms | Both channels ready |
| 20 ms | Test payload launched and returned intact |

The QSFP3 reset/clock-ready indications had settled before the forward enable
origin in this trial. QSFP4's TX was enabled earlier in the sequence, allowing
the reverse direction to recover first. Thus the two receivers' absolute start
conditions are asymmetric; the forward receiver is the main OFF/ON observation.

The roughly 0.8–1.1 ms between the first clean-header window bound and both-channel
readiness includes header qualification, an automatic receiver restart, and
requalification. The preceding several milliseconds dominate this run.
Shortening only the final handshake cannot remove that earlier interval.

## Instrumentation and validation

The generated Aurora wrappers expose native header/data-valid signals, legal and
illegal header counts, gearbox-slip edges, block synchronization, six alignment
FSM states, and alignment-reset events. There are 16 free-running 32-bit counters
per receiver. Registered Gray counters cross through two synchronizer stages;
metrics have a few native cycles of sampling uncertainty. Window deltas handle
32-bit wrap. Header-valid means interface validity, not correct optical data.
Random header bits can be legal approximately half the time.

The recorder stores at most 256 snapshots, including the initial sample. It
reports overflow for longer captures. Readback occurs after the trial freezes,
so JTAG reading does not delay measured acquisition. Snapshot storage uses eight
block-RAM primitives per receiver, checked before implementation.

Validation: native-counter simulation; Gray decoding and recorder timing,
freeze, overflow and rearm simulation; CSV decoder wrap checks; mocked Tcl VIO
readback; on-board baseline and paired controls. Final setup WNS +0.548 ns, hold
WHS +0.003 ns. Gray bus skew: QSFP3 0.966 ns and QSFP4 1.082 ns against a 2.400 ns
requirement. Build provenance is saved in `build_manifest.json` in the run.

## Files and repeat command

- `header_activity_raw.csv`: cumulative raw counter snapshots.
- `header_activity.csv`: differences and fractions for each window.
- `header_activity_summary.json`: first clean windows, slips and reset totals.
- `startup_timing.csv`: timestamped signal edges, including automatic resets.
- `header_recovery.png`: representative forward receiver traces for three modes.
- `trials.csv`, `power.csv`, `vivado.log`: payload results, DOM, and restoration.

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-reset-mode keep \
  --guard-test compare-all --guard-us 20000 --guard-dark-ms 1000 \
  --guard-trials 5 --guard-baseline-trials 3 --guard-baseline-us 20000 \
  --guard-header-trace
```

The runner restored QSFP3 and QSFP4 byte 86 to zero and reprogrammed the working
streaming image successfully. Before using XDMA again:

```bash
sudo sh -c 'echo 1 > /sys/bus/pci/devices/0000:ab:00.0/remove; echo 1 > /sys/bus/pci/rescan'
sudo modprobe xdma
```
