# GTY/Aurora startup timing investigation

Run: `FPGA_HH_QSFP/burst_guard/measurements/20261015_235025_566760`.
Command: `optical_stream.py --source pattern --guard-sweep --guard-reset-mode keep --guard-us 50000,20000,10000,5000 --guard-dark-ms 1000 --guard-trials 20 --guard-baseline-trials 20`.

## What changed

Added a passive 200 MHz recorder for 16 existing status signals per Aurora
instance. Generated wrapper patches expose native status wires; no protocol
settings or startup timers were changed. Original electrical swings remain
430 mV on QSFP3 TX2 and 490 mV on QSFP4 TX2. No U7 clock settings changed.

The recorder starts before laser disable and freezes at each trial end. It
records first-high, last rising/falling edge, saturated edge counts and initial/
final levels. All times in startup_timing.csv are relative to QSFP3 TX-enable
I2C STOP. Negative values are events before enabling the forward transmitter.
Initial-high timestamps are observation-window starts, not fresh lock events.

## Validation

- Recorder simulation passed initial-level, rise/fall counting, timing-origin,
  baseline rearm, and freeze checks.
- Python decoder checks and Tcl syntax checks passed.
- Synthesis, implementation and bitstream generation completed.
- Setup WNS +0.555 ns; hold WHS +0.011 ns; no failing timing endpoints.
- Routed bus-skew report met constraints; implementation had no critical warnings.
- Exported probes contain all 16 packed timestamp buses and metadata.
- Original module byte86 settings (0 on both) and working streaming bitstream
  were restored; confirmed in vivado.log. Host PCIe rescan remains necessary.

## Frame results

| Condition | Intact / attempted | Not ready | Bit errors in complete frames |
| --- | ---: | ---: | ---: |
| Continuous baseline | 20/20 | 0 | 0 |
| 50 ms guard | 19/20 | 1 | 0 |
| 20 ms guard | 20/20 | 0 | 0 |
| 10 ms guard | 18/20 | 2 | 0 |
| 5 ms guard | 3/20 | 17 | 0 |

The nonmonotonic 50 vs 20 ms result reflects recovery variability and limited
samples. These runs do not establish a guaranteed minimum guard.

## Where the delay occurs

A representative clean trial (ID20, 50 ms guard), forward receiver QSFP4:

| Milestone | Time after QSFP3 enable STOP |
| --- | ---: |
| Last HP/PMA recovery-reset pulse ends | 7.371955 ms |
| CDR-wrapper reset pulse begins | 8.101990 ms |
| Final RX reset done assertion | 8.470115 ms |
| Final block-sync assertion | 8.777695 ms |
| Final lane-up assertion | 8.777700 ms |
| Final channel-up assertion | 8.890110 ms |

The wrapper deliberately performs a receiver reset after detecting initial
block synchronization. Thus the observation is not a simple once-through
CDR -> reset done -> block sync chain. Multiple reset and synchronization
transitions explain why final transitions, rather than initial high flags,
are needed.

Across the 19 successful 50 ms burst trials on QSFP4, medians of per-trial gaps:

- Final RX reset done -> final block sync: 356.050 us (range 307.580–4105.470 us).
- Final block sync -> final lane up: 0.010 us (range 0.005–0.010 us).
- Final lane up -> final channel up: 0.130 us (range 0.120–112.410 us).

These gaps are computed per trial; medians of separate timestamps must not be
subtracted to reconstruct a typical trial. First both-channel readiness ranged
from 4.504 to 38.595 ms among those successful trials. In slow trial23, QSFP4's
RX reset completed at 38.121300 ms, block sync at 38.594500 ms, and channel up
at 38.594645 ms. Most of that trial elapsed before the final reset completed.

In failed 50 ms trial37, QSFP4 RX reset done was high by 4.665285 ms, but block
sync and lane/channel up never asserted within the 50 ms observation window.
QSFP3 recovered its receive lane yet its channel also remained down, consistent
with the duplex channel depending on both directions. RX reset done alone is
therefore not sufficient evidence of a working received bitstream.

The recorder observed up to 21 HP/PMA recovery-reset pulses in a trial window
that includes the dark interval, plus the wrapper CDR-reset pulse. This proves
that “no explicit reset” does not prevent automatic resets. The generated
Aurora hot-plug recovery code also uses a 24-bit INIT_CLK counter: its full
range at 200 MHz is 83.88608 ms. It resets on valid received control traffic
or other reset conditions, so that range is not a fixed delay for every burst.
This is a concrete recovery mechanism to investigate next, not proof that
this watchdog alone caused every slow trial.

**Conclusion:** the dominant delay lies before usable block synchronization,
including transceiver recovery/reset/retry and alignment behavior. The final
lane/channel readiness transition usually contributes very little. The present
measurements cannot separate the optical module's turn-on time from actual
analog CDR settling and early alignment/retry time. No timer was tuned here.

## Interpretation limits

AMD UG578 Table4-11 marks native RXCDRLOCK as reserved. It is saved as
`cdr_lock_raw_reserved`, never used as proof of physical CDR acquisition.
The generated GT Wizard helper CDR-stable signal is a synchronized copy of that
raw output; reset logic also has a timeout fallback. Aurora `gt_pll_lock` means
TX-clock stability, so the CSV calls it `tx_clock_stable`.

Sources: [AMD UG578](https://docs.amd.com/api/khub/documents/BY7rRWkUQliMvNvosLhSZA/content),
[Aurora status ports](https://docs.amd.com/r/en-US/pg074-aurora-64b66b/Status-Control-and-Transceiver-Ports),
and the generated RTL under `burst_guard/build/burst_guard.gen/sources_1/ip/`.

Inputs use two-flop synchronization and 5 ns sampling, so very narrow pulses
can be missed and timestamps have several-cycle uncertainty. Existing native
sticky error flags remain the error reference. Failed short-guard trials are
censored; later recovery is not observed. Optical turn-on/extinction still
requires a fast photodetector and oscilloscope. DOM is too slow for that.

## Files and repeating the measurement

`startup_raw.csv`, `startup_timing.csv`, and `startup_summary.json` are saved
alongside the usual trials, power, and restoration logs in the run directory.
Future `--guard-sweep` runs automatically collect these timestamps. The startup
observer's counter has 21.47 s range; the host limits dark + guard + receive
allowance to 18 s, leaving room for command overhead.

The FPGA folder is ignored by Git. Keep its diagnostic sources, scripts,
bitstream/probes and MANIFEST.json together when moving the project. The prior
diagnostic bitstream/probes are backed up in `backups/pre_startup_timestamps`.
