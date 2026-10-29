# GTY receiver adaptation hold sweep — 2026-10-16

Holding the GTY CDR through darkness and releasing it after 5 or 10 ms improved
native PRBS recovery in this experiment. Equalizer hold alone did not recover
within the 20 ms capture. This is evidence that GTY clock-recovery control
contributes to the observed failures. It does not identify the QSFP's internal
recovery time, and it did not demonstrate reception within microseconds.

## Setup and method

- Same fibers, delay and attenuation as the preceding experiments; no physical changes.
- Forward path: QSFP3 TX2 / GTY X1Y49 → fiber → QSFP4 RX2 / GTY X1Y58.
- Only QSFP4's GTY receiver is held. QSFP3's receiver is an unheld reverse reference.
- Native GTY PRBS31, with Aurora-driven RX restarts, gearbox slips and automatic
  polarity changes suppressed. No explicit GT RX reset during darkness or capture.
- Each trial normalizes the receiver under steady light, then requires a clean
  1 ms native PRBS capture immediately before asserting the selected holds.
- Equalizer group: AGC, LF, KH, CFOK, UT, VP, offset cancellation, DFE taps 2..15.
  All corresponding override inputs remain zero. CDR group: RXCDRHOLD.
- Dark hold command: 1000 ms, plus management/JTAG sequencing overhead.
- Release delays from QSFP3 TX-enable I2C STOP: 0, 10, 100, 500, 1000, 2000,
  5000 and 10000 µs. The no-hold reference runs once per repetition.
- Capture window: 20 ms. Qualification: lock, RX reset-done and a running native
  clock, with no new error indications for 100 µs. Errors after qualification
  continue to be counted. Final quiet-tail timing is also reported.
- Three repetitions of each of 25 cold conditions; order reverses in the middle
  repetition. There are 75 cold trials and 15 control trials, 90 total.

## Results on QSFP4 RX

“Quiet through end” requires a quiet tail of at least 100 µs continuing to the
20 ms capture end. The start is calculated from the last observed error and
first lock, with native-counter clock crossing latency of several FPGA cycles.

| Hold mode | Release after enable STOP | Quiet through end | Start of final quiet tail |
| --- | ---: | ---: | --- |
| None | 0 | 0/3 | Not reached within 20 ms |
| Equalizer | All eight delays | 0/24 | Not reached within 20 ms |
| CDR | 0–2000 µs, six delays | 3/18 | Sporadic recovery only |
| CDR | 5000 µs | 3/3 | 6.329–7.893 ms; median 6.760 ms |
| CDR | 10000 µs | 3/3 | 8.139–9.240 ms; median 8.140 ms |
| Equalizer + CDR | 0–2000 µs, six delays | 0/18 | Not reached within 20 ms |
| Equalizer + CDR | 5000 µs | 1/3 | 6.740 ms in the successful trial |
| Equalizer + CDR | 10000 µs | 3/3 | 7.100–9.670 ms; median 8.601 ms |

All 13 cold trials that reached an initial 100 µs quiet interval subsequently
showed further errors before their final quiet tail. Consequently, the first
quiet interval alone would have declared recovery too early. For example,
CDR hold released at 5 ms first qualified from 4.880, 6.640 and 6.167 ms, but
the final quiet tails began at 7.893, 6.760 and 6.329 ms respectively.

In some 10 ms hold trials, clean reception began before hold release and
continued afterward. That is valid here: these are adaptation holds, not RX
reset requests. It is not treated as post-reset acquisition.

Full per-delay results are in `HOLD_README.md` and `hold_summary.json` in the
measurement directory below. Native RX error indications count cycles with
errors; they are not exact bit counts or BER.

## Controls and implementation checks

- Internal PMA loopback: clean on both receivers. Deliberate native TX error
  injection: detected locally and through the optical forward path, with the
  unaffected receiver remaining clean.
- Native illuminated optical baselines: 2/2 clean on both receivers.
- Aurora illuminated payload baselines: 2/2 intact, 8192 words each.
- Illuminated hold controls: 2/2 clean for every mode, including 10 ms holds.
- Each of the 83 hold schedules confirmed assertion before the measured
  trial, exact programmed release tick, and return to zero. Return signals
  followed release by 5 ns for no hold and 15 ns for the active modes.
- Synthesized netlist check: Q3 hold pins grounded; Q4 CDR and 21 selected
  equalizer holds independently driven; override pins grounded.
- Timer simulation checked zero/nonzero release timing, waiting for STOP,
  return signals, abort and rearming. Software plan and reporting checks passed.
- Routed FPGA timing: WNS +0.476 ns, WHS +0.010 ns, WPWS +0.361 ns; the
  existing counter clock-crossing bus-skew checks passed.

## What this establishes

The controlled change to GTY CDR handling improved native PRBS acquisition
without changing the fiber, QSFP settings, pattern or RX-reset policy.
The GTY clock-recovery path therefore matters to the recovery behavior.

The experiment does not prove that a particular stored setting was lost.
RXCDRHOLD freezes the loop / locks to reference; it cannot guarantee retained
phase relative to incoming data. The QSFP transmitter turn-on time, receiver
electrical waveform and any internal module retimer state were not measured.
They can still contribute to the remaining several milliseconds.

Three successes per condition are a useful initial result, not a production
reliability guarantee. These measurements use a shared-board clock arrangement
and native PRBS; they do not establish the same behavior with independent
boards or Aurora payloads. The next useful test would apply the best CDR hold
timing to Aurora and verify actual payloads repeatedly. Production streaming
behavior has not been changed by this diagnostic.

The documented hold behavior is described in AMD UG578 v1.4, Tables 4-9 and
4-11 and the RX CDR Lock to Reference section:
[UltraScale Architecture GTY Transceivers User Guide](https://docs.amd.com/api/khub/documents/BY7rRWkUQliMvNvosLhSZA/content).

## Artifacts and repeat command

Measurement directory:

`FPGA_HH_QSFP/burst_guard/measurements/20261016_164054_211675/`

Key files: `plan.csv`, `hold_trials.csv`, `prbs_trials.csv`, `hold_summary.json`,
`HOLD_README.md`, `trials.csv`, `power.csv`, `vivado.log`,
`final_source_manifest.json`. The prior diagnostic image is backed up in
`FPGA_HH_QSFP/burst_guard/backups/pre_receiver_hold/`.

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-test prbs-hold \
  --guard-reset-mode keep --guard-us 20000 --guard-dark-ms 1000 \
  --guard-trials 3 --guard-baseline-trials 2 --guard-prbs-quiet-us 100 \
  --guard-hold-modes none,equalizer,cdr,both \
  --guard-hold-release-us 0,10,100,500,1000,2000,5000,10000
```

The runner exited successfully and restored both modules' original byte 86
values (0), then programmed the working `hh_qsfp_top.bit` image. The original
working setup bundle was not modified. Before subsequent XDMA use:

```bash
sudo sh -c 'echo 1 > /sys/bus/pci/devices/0000:ab:00.0/remove; echo 1 > /sys/bus/pci/rescan'
sudo modprobe xdma
```
