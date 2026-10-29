# Native GTY PRBS versus Aurora recovery — 2026-10-16

## Result

Removing Aurora did not make OFF/ON recovery immediate. With its automatic RX
restarts suppressed, the native PRBS checker found **no continuous 100 us quiet
interval in five 20 ms forward-path captures**. The paired Aurora trials all
returned intact payloads and became ready in 5.330–8.175 ms.

A follow-up showed that a late GTY RX reset can restore native PRBS reception:
reset requests released 10 ms after laser enable produced qualified intervals in
3/3 trials. Requests released at 0, 1, or 5 ms produced none in 3/3 trials each.

**Receiver state and reset timing matter.** These experiments do not identify a
fixed voltage threshold as the cause, establish Aurora header search as the sole
limitation, or distinguish optical-module settling from GTY CDR/equalizer/PCS
recovery. No reliable sub-millisecond recovery method has been demonstrated.

## Validation and optical conditions

The existing fibers, attenuation, clock configuration, lane locations, and TX
swing settings were retained. Forward route: QSFP3 TX2 / GTY X1Y49 to QSFP4 RX2 /
GTY X1Y58. QSFP4 TX2 was enabled earlier, so the reverse direction was already
illuminated before the forward time origin.

The diagnostic uses native PRBS31 (selector `0101`) at the existing 25.78125 Gb/s
GT configuration. In PRBS mode it suppresses Aurora-driven GT RX reset requests,
gearbox slips delivered to the GTY, and automatic polarity changes. Polarity is
held at the previously validated zero setting. No XDMA or Python transfer timing
is involved in acquisition measurements.

Before measuring bursts, the runner validated:

- Both GTs in near-end PMA loopback: clean native PRBS reception.
- Forced errors on Q3 in internal loopback: detected at Q3, with no qualification.
- Three continuously illuminated optical baselines: no error-indicated cycles
  on either receiver in the 20 ms captures.
- Forced errors at Q3 TX over the optical path: detected at Q4, with no qualification.
- Aurora baselines after switching back from PRBS: intact payloads.

With light already present, fresh PRBS checker acquisition took approximately
0.085–0.090 us, followed by the requested 100 us quiet qualification. This is
checker acquisition on an already settled optical path, **not laser OFF/ON or
analog CDR settling time**.

## Main paired comparison

Completed run:
`FPGA_HH_QSFP/burst_guard/measurements/20261016_150000_418811/`

Settings: requested dark hold 1,000 ms, observation/guard 20,000 us, quiet
qualification 100 us, five paired bursts, alternating mode order.

| Forward-path condition | Trials | Outcome |
| --- | ---: | --- |
| Native PRBS, continuously illuminated | 3 | All clean; first lock about 0.09 us |
| Native PRBS after laser OFF/ON, no automatic RX restart | 5 | No 100 us quiet interval within 20 ms |
| Aurora after laser OFF/ON | 5 | All payloads intact; ready 5.330–8.175 ms, median 6.322 ms |

Native PRBS first-lock indications appeared at 10.450–13.734 ms, but reception
remained error-indicated afterward. These flags are sticky and **were not counted
as successful recovery**. RX clocks continued running and no RX-notready/stall
flags were observed in those five native captures.

The PRBS and Aurora cases change both the serial pattern and the automatic reset
policy. Therefore the timing difference does not isolate one header-counter
parameter. It establishes that bypassing Aurora is insufficient by itself, while
Aurora's existing recovery machinery can restore communication.

## Scheduled RX-reset follow-up

Completed run:
`FPGA_HH_QSFP/burst_guard/measurements/20261016_151024_707042/`

Same optics, 20 ms captures and 100 us qualification; three repetitions per
reset-request release delay, plus no-restart references.

| Reset request released after forward TX-enable STOP | Qualified forward captures |
| --- | ---: |
| No deliberate restart | 0/3 |
| 0 ms | 0/3 |
| 1 ms | 0/3 |
| 5 ms | 0/3 |
| 10 ms | 3/3 |

For 10 ms releases:

- First qualifying quiet interval began at 10.610–10.685 ms.
- Some errors returned afterward: 10, 8, and 2 error-indicated native cycles,
  respectively, after first qualification.
- Last detected errors occurred at 11.128, 10.975, and 10.884 ms. Continuous
  healthy quiet tails then extended through the end of the 20 ms captures.

Thus first qualification alone should not be treated as permanent recovery. This
small sample supports late-reset recovery, not a guaranteed deployment guard.

The GT Wizard executes its RX reset sequence **after its reset request is
released**. A held request does not imply native RXRESETDONE is already low.
The earlier-illuminated reverse receiver can therefore qualify before a scheduled
restart. Such pre-release qualification is explicitly excluded from post-reset
timing; this does not mean the reverse receiver failed to recover afterward.
The forward receiver is the relevant cold-start endpoint here.

## Measurement definition and limitations

The checker is freshly reset for every trial. A 200 MHz hardware timer starts at
QSFP3's successful TX-enable I2C STOP. PRBS baseline timing starts at hardware
checker release. The checker is held reset before that origin, preventing a lock
flag retained from a previous trial from being mistaken for acquisition.

Native `RXPRBSERR` cycles are counted in the RX clock domain, Gray-coded and
synchronized to the timer. Qualification requires PRBS lock, RX reset-done, a
running native clock and 100 us without error indications. A 1 us native-clock
watchdog prevents a stopped clock from being treated as a quiet receiver.
Reported timestamps have 5 ns tick resolution plus several cycles of checker and
clock-domain-crossing latency.

**Error-indicated cycles are not exact bit-error counts or BER.** Native lock is
sticky; errors after qualification and the last-error timestamp are retained.
A finite quiet interval cannot guarantee future error-free transmission. These
measurements do not measure optical laser settling directly or analog CDR lock.

Reference: AMD [UG578, RX Pattern Checker and TX Pattern Generator](https://docs.amd.com/api/khub/documents/BY7rRWkUQliMvNvosLhSZA/content),
Tables 4-24/4-25 and 3-25. The diagnostic uses the existing synchronous gearbox;
its native PRBS link-acquisition count is 15. RXPRBSLOCKED is sticky until checker
reset, and RXPRBSERR is a non-sticky indication.

## Implementation, checks and files

New RTL: `FPGA_HH_QSFP/burst_guard/rtl/prbs_recovery.v` and generated native-PRBS
port patches in `scripts/expose_prbs.py`. Host summaries:
`Modular_Python_Controller/prbs_recovery.py`. Existing header counter CDC and
block-RAM snapshot infrastructure are reused. Mode zero retains Aurora behavior.

Checks passed: observer simulation (fresh reset, STOP origin, quiet interval,
sticky-lock errors, native-clock watchdog, freeze/abort), paired plan generation,
mocked Tcl status decoding/arm preservation, FPGA timing, internal loopback,
forced-error controls, optical baselines, and paired hardware captures.
Setup WNS +0.327 ns; hold WHS +0.010 ns. Gray bus skew 1.000/1.051 ns against
2.400 ns requirements. The working streaming bitstream itself was not revised.

Raw data: `prbs_trials.csv`, `trials.csv`, `startup_timing.csv` and, where enabled,
`header_activity.csv`. Summaries: `prbs_summary.json` and `PRBS_README.md`.

Two earlier runs were interrupted by diagnostic-runner checks and are retained
for audit: `20261016_145600_175437` (arm-toggle bookkeeping corrected) and
`20261016_150500_938673` (pre-release reverse qualification correctly excluded).
Only the completed runs above support the tables.

Repeat commands are in `OPTICAL_GUARD_SWEEP.md` under **Native PRBS versus Aurora
recovery** and **Native PRBS with scheduled RX-reset request release**.

Both modules' original byte-86 values (zero) and the working streaming image were
restored after each run. Before using XDMA again:

```bash
sudo sh -c 'echo 1 > /sys/bus/pci/devices/0000:ab:00.0/remove; echo 1 > /sys/bus/pci/rescan'
sudo modprobe xdma
```

A useful next controlled experiment is preserving selected GTY receiver state
through darkness and comparing against these PRBS baselines. That has not yet
been implemented or shown to reduce recovery time.
