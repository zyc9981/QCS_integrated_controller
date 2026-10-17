# Guard sweep executed 2026-10-15

The fibers, attenuation, delay, and U7 clock configuration were left unchanged
at the user's request. Two sweeps ran on the HTG-930 using the separate
`FPGA_HH_QSFP/burst_guard` diagnostic image. Only optical TX2 on each module was
enabled during trials; the other wavelengths were disabled. Both modules'
original TX-disable byte values were saved as 0 and restored as 0 afterward.

## Results

Each trial uses a 65,536-byte FPGA-generated xorshift64 frame, with the seed
recorded in plan.csv. The dark interval was 100 ms after disable operations.
Aurora logic was reset between bursts; its PLLs were not deliberately reset.
Guard time starts at the QSFP3 TX-enable target-register I2C STOP. QSFP4 TX2
is enabled earlier for reverse/control traffic. Timing resolution is 5 ns,
with several cycles of clock-crossing uncertainty.

Pilot: 10/10 baseline frames intact. At 1 s and 100 ms guards, 3/3 bursts each
returned intact. At 10 ms, 1 ms, 100 us, 20 us, 6 us, and 2 us, none of the
three pilot trials per setting met the Aurora-readiness deadline.

Refinement:

| Mode / guard | Acquired | Intact | Not ready by deadline | Differing bits in full frames |
| --- | ---: | ---: | ---: | ---: |
| Continuous baseline | 100/100 | 100 | 0 | 0 |
| 100 ms | 30/30 | 30 | 0 | 0 |
| 50 ms | 30/30 | 30 | 0 | 0 |
| 30 ms | 30/30 | 30 | 0 | 0 |
| 20 ms | 30/30 | 30 | 0 | 0 |
| 15 ms | 30/30 | 30 | 0 | 0 |
| 12 ms | 10/30 | 10 | 20 | 0 |
| 10 ms | 3/30 | 3 | 27 | 0 |

There were no receive timeouts or malformed frames in the refinement. Compared
full frames contained 137,887,744 bits, with zero observed differing bits.
This BER sample excludes failed acquisitions; it is not raw optical-lane BER.
Successful burst trials reported readiness from approximately 5.83 to 14.71 ms
after the forward enable command. The selected 15 ms guard was the shortest
setting with 30/30 intact returns in the refinement; 20 ms is a provisional
setting with more margin for further testing, not a production guarantee.

These measurements apply to **this module-control and Aurora-reset procedure**.
They do not establish the laser's intrinsic settling time, rule out a faster
burst architecture, or demonstrate the 6 us regime discussed in the paper.
Actual light-on time has not been measured with a fast optical detector.

Pilot DOM snapshots on TX2: QSFP3 TX +0.83 dBm, QSFP4 RX -9.14 dBm (approximately
9.97 dB apparent loss); reverse RX at QSFP3 +1.37 dBm. All channels' dark-state
TX/RX snapshots were at the module's raw monitor floor. DOM is a slow estimate,
not a calibrated extinction-ratio or switching-time measurement.

## Artifacts

- Pilot: `FPGA_HH_QSFP/burst_guard/measurements/20261015_183021_577381/`
- Refinement: `FPGA_HH_QSFP/burst_guard/measurements/20261015_183314_412379/`
- Each contains plan.csv, trials.csv, power.csv, saved_module_settings.csv,
  summary.json, README.md, and vivado.log with restoration messages.
- Diagnostic source and bitstream checksums: `FPGA_HH_QSFP/burst_guard/MANIFEST.json`.
- Final routed setup slack +0.701 ns; hold slack +0.015 ns; no DRC errors or
  bus-skew violations in the routed report.
- Digital simulation checked intact frames, injected bit errors, early frame
  ends, missing returns, readiness failure, and recovery to the next trial.
  Python syntax, Tcl full-width control/status parsing, and CSV aggregation
  checks also passed.

See [OPTICAL_GUARD_SWEEP.md](OPTICAL_GUARD_SWEEP.md) for rerun commands and the
PCIe rescan required after restoring the working streaming image. The diagnostic
FPGA folder is ignored by Git and must be retained separately if moving hosts.

## Comparison: toggle lasers without explicit Aurora reset

Run: `FPGA_HH_QSFP/burst_guard/measurements/20261015_185936_706573`.
Same fibers/attenuation, 100 ms dark interval, 64 KiB diagnostic frames.
50 continuously illuminated baseline frames passed. Each guard had 20 trials
per mode; paired seeds and alternating mode order. No FPGA RTL rebuild was
needed: controller abort/rearm and Aurora reset are separate existing controls.

| Guard | Explicit reset: intact | No explicit reset: intact |
| --- | ---: | ---: |
| 50 ms | 20/20 | 20/20 |
| 20 ms | 20/20 | 18/20 |
| 15 ms | 20/20 | 20/20 |
| 12 ms | 12/20 | 18/20 |
| 10 ms | 11/20 | 15/20 |
| 5 ms | 1/20 | 1/20 |
| 1 ms | 0/20 | 0/20 |
| 100 us | 0/20 | 0/20 |
| 6 us | 0/20 | 0/20 |

At 10 ms without explicit reset, one additional trial produced an early end
(one received word, 32 differing bits, RX soft error); it was excluded from
full-frame BER. At 5 ms without explicit reset, one additional full frame had
3 differing bits and an RX soft error. Remaining failed trials missed channel
readiness at the deadline. Successful full frames in explicit-reset mode had
no bit errors.

At the longest guard (50 ms), median first channel-ready time was 8.158 ms
without explicit reset versus 12.258 ms with explicit reset. One no-reset trial
took 20.366 ms. Removing the reset often helps, but does not establish reliable
submillisecond operation. The 15 ms vs 20 ms success reversal illustrates the
limited sample and recovery variability; do not infer a reliable minimum.

Automatic Aurora recovery remains enabled: “no explicit reset” does not mean
Aurora never resets internally after loss of light. Both modules' lasers were
toggled; this experiment does not cover keeping the reverse control laser on.
Guard origin is the TX-enable I2C STOP, not measured optical turn-on.
