# Timed receiver restart after transmitter enable

Run: `FPGA_HH_QSFP/burst_guard/measurements/20261016_031029_739749`.

## Added code

The diagnostic holds both receiver reset requests during darkness and releases
them in FPGA logic at a programmable delay after the forward QSFP3 TX-enable
I2C STOP. Config bit5 enables the sequencer; config[31:8] gives delay ticks at
200 MHz (5 ns). Manual bit4 receiver reset still works independently. Neither
mode changes default production behavior; both controls default to zero.

The GT Wizard executes its actual physical reset sequence after request release.
The output is a reset request, not a claim that the analog receiver is physically
held reset throughout the dark interval. Aurora automatic recovery remains active.

New CLI modes: `--guard-test burst-restart` and `--guard-test compare-restart`.
New sweep argument: `--guard-rx-release-us`. References in compare-restart use
no explicit Aurora reset; each restart trial is paired with the same test seed
and order alternates. References are pooled across release-delay pairs in the
summary. Results now retain release delay as a separate grouping dimension.

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-test compare-restart \
  --guard-reset-mode keep --guard-us 5000,2000 \
  --guard-rx-release-us 0,100,500,1000 --guard-dark-ms 1000 \
  --guard-trials 10 --guard-baseline-trials 20
```

## Validation

- Sequencer simulation passed delays 0/1/20/200000 ticks, hold before enable
  STOP, disable bypass and abort/rearm.
- Python/Tcl checks passed pairing, grouped release-delay summaries and syntax.
- Synthesis, implementation and bitstream generation passed.
- Setup WNS +0.669 ns; hold WHS +0.011 ns; no failing timing endpoints.
- Routed bus-skew report met constraints.
- Observed request-release edges were exactly requested delay +0.015 us in
  all 80 restart trials (two-flop/sampling observation delay). The runner checked
  each against a 50 ns tolerance. Startup metadata bit66 confirms the new schema.
- Previous diagnostic bit/probes retained in backups/pre_timed_restart.

The updated observer records `diagnostic_rx_reset_request` in status position14
on both sides. The decoder preserves the previous `gt_reset` interpretation for
older snapshots without capability bit66.

## Results

Continuous baseline: 20/20 intact. Fiber, attenuation and clock/swing settings
were unchanged. Each burst had a requested 1 second dark interval.

| RX request release after TX-enable STOP | Intact at 5 ms guard | Intact at 2 ms guard |
| --- | ---: | ---: |
| Normal automatic recovery (pooled reference) | 1/40 | 0/40 |
| 0 us | 1/10 | 0/10 |
| 100 us | 3/10 | 0/10 |
| 500 us | 0/10 | 0/10 |
| 1000 us | 3/10 | 0/10 |

Controlled restart total: 7/40 intact at 5 ms, 0/40 at 2 ms. All complete
frames were intact; failures missed channel readiness. One not-ready 2 ms trial
(ID174) saw a spurious one-word fragment with 28 differing bits before payload
launch. This incomplete fragment is excluded from full-frame BER and retained
in trials.csv. No receive timeouts occurred.

The reference/controlled difference is suggestive but the sample is small and
no setting was reliably successful. No production guard recommendation follows
from these data, and this is not a reliable short-burst fix.

## What the timestamps tell us

In all 40 controlled 2 ms trials, forward QSFP4 native RXRESETDONE was high by
the deadline, but block synchronization was still low. Median final reset-done
assertion by release delay:

| RX request release | RX reset done after TX-enable STOP |
| --- | ---: |
| 0 us | 365.135 us |
| 100 us | 468.265 us |
| 500 us | 867.725 us |
| 1000 us | 1366.920 us |

Thus a confirmed, timely receiver reset completed well before the 2 ms deadline;
usable block synchronization did not. For example, trial21 completed RX reset
at 363.005 us but had no forward block synchronization by 5 ms. Trial33 completed
RX reset at 368.460 us and obtained block sync at 4005.145 us.

This rules out slow completion of the requested reset as the sole explanation
for these failures. The remaining delay is between reset completion and usable
received block synchronization. It can include optical-module turn-on or
reacquisition, receiver data settling, and FPGA alignment/search behavior.
It does not directly measure optical light-on or prove which component dominates.
Native RXCDRLOCK remains reserved and is not used to establish analog CDR lock.

## Restoration

Both module byte86 values were restored to 0. The normal working streaming
bitstream was reprogrammed and restoration confirmed in vivado.log. Refresh
host PCIe before using XDMA again. Production streaming RTL/bitstream was not
modified. The FPGA diagnostic folder is ignored by Git and must be retained
with the host scripts when moving the project.
