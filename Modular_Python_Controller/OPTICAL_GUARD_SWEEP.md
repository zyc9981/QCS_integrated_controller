# Optical guard-time sweep

This experiment uses a separate FPGA diagnostic image. Python starts one Vivado
batch session; JTAG configures each trial and reads its counters. No XDMA or HH
acquisition runs during the diagnostic. The path remains QSFP3 TX2 / X1Y49 ->
fiber -> QSFP4 RX2 / X1Y58, at the current 25.78125 Gbps line rate and electrical
swing settings (430 mV forward, 490 mV reverse). Fibers, attenuators, and U7 clock
settings are left unchanged.

## Build once

```bash
/home/alzhu/vivado_dl/2025.2/Vivado/bin/vivado -mode batch -nojournal \
  -source /home/zyc/QCS/QCS_integrated_controller/FPGA_HH_QSFP/burst_guard/scripts/build.tcl
```

The build creates new IP/project files under `FPGA_HH_QSFP/burst_guard/build` and
checks final setup timing before exporting the debug probes. It does not
overwrite the working streaming project or bundled bitstream. The FPGA folder
is ignored by Git, so retain/copy it separately when moving the repository.

## Run

Close all controller, DMA, and other Vivado sessions using this board, then:

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --block-size 65536 \
  --guard-us 1000000,100000,10000,1000,100,50,20,10,8,6,4,2 \
  --guard-trials 10 --guard-baseline-trials 20 --guard-dark-ms 100
```

The diagnostic image is programmed once per complete sweep, not once per
guard setting. Programming and final restoration take roughly a minute each.
Use `--guard-output /path/to/new-directory` to choose the result directory.
Otherwise results are saved under `FPGA_HH_QSFP/burst_guard/measurements`.
`--guard-timeout-ms` sets receive allowance after the selected guard (default
100 ms). `--pattern-blocks` is not the sweep length: use `--guard-trials`.

Use `--guard-reset-mode keep` to toggle lasers without explicitly resetting
Aurora between trials. Use `--guard-reset-mode compare` to interleave paired
trials with/without explicit reset, using the same seed and alternating order.
The default is `reset`. Automatic Aurora link recovery remains enabled in every
mode; `keep` does not guarantee that the core never resets internally.

## Trial sequence and timing

1. Save both modules' original TX-disable bytes (86). Enable only TX2 on each
   module; other three optical wavelengths are disabled in this experiment.
2. Establish a continuously illuminated baseline. Each trial transmits a seeded
   xorshift64 pattern, with the seed saved in plan.csv. This is a diagnostic
   frame of the selected size; it has no HHQ1 header and is not an IBERT PRBS.
3. For each burst trial, assert Aurora reset only in `reset` mode, and disable all lasers on
   both modules. Wait the configured dark interval (initially >=100 ms). FPGA
   PLLs and clocks are not deliberately power-cycled.
4. Enable QSFP4 TX2 (reverse/control direction), release Aurora reset, and arm
   the FPGA generator/checker. Enable QSFP3 TX2. The guard counter starts at the
   I2C STOP of that target-register write, before the I2C mux-cleanup transaction.
5. At the requested guard deadline, require both synchronized Aurora channel-up
   signals. If they are not ready, record failed acquisition; do not postpone
   the payload and misleadingly claim that the short guard worked.
6. If ready, send the complete pattern using the AXI stream ready/valid
   handshake. Count received words, XOR/popcount bit differences, and end/keep
   errors. A missing return times out in FPGA logic. A new trial clears the
   generator/checker, without leaving a host DMA read blocked. Aurora is explicitly
   reset between trials only when that mode is selected.

The counter clock is 200 MHz (5 ns resolution). Clock-domain synchronization
adds several FPGA cycles of uncertainty to status timestamps and payload launch.
`first_tx_us` records the synchronized first accepted TX beat; it may be later
than the requested guard because of CDC and Aurora TX-ready pauses.

This measures **command-to-payload guard requirements**. It does not measure
actual optical light-on time. I2C module response, optical turn-on, module CDR,
and FPGA/Aurora synchronization contribute to the result. QSFP4 is enabled
before the timing origin, so this is not simultaneous laser switching on both
ends. DOM snapshots are slow estimates and do not resolve microsecond pulses.

## Results

- `trials.csv`: every trial, outcome, word/bit counts, timestamps, flags, raw status.
- `summary.json` / `README.md`: grouped acquisition success, intact frames, BER.
- `plan.csv`: guard settings, trial seeds and frame sizes.
- `power.csv`: baseline/dark per-channel DOM TX/RX snapshots in 0.1 uW units.
- `saved_module_settings.csv`: original TX-disable bytes for recovery.
- `vivado.log`: programming, errors, and restoration confirmation.

Outcome codes: 1 = complete frame; 2 = channel not ready at deadline; 3 = receive
timeout; 4 = malformed/short frame. Result 1 can still contain payload errors.
Flags: bit 0 invalid keep, 1 early end, 2 missing end at expected length, 8 RX
hard error, 9 RX soft error, 16 TX hard error, 17 TX soft error. BER includes all
64 bits of each word of full valid frames. Incomplete/malformed frames are
excluded from BER, counted as acquisition failures, and retain their partial
counts in the trial CSV. No arrivals means BER is unavailable, not zero.

Keep optical power and dark interval fixed during a sweep. If the continuous
baseline already has errors, a guard-time result alone cannot separate those
errors from settling effects. A small successful pilot does not establish a
minimum reliable guard time; repeat many trials and allow deployment margin.

## Restoration

The script restores original module byte 86 values, then reloads
`FPGA_working_setup_20261009/bitstreams/hh_qsfp_top.bit` and its probes, including
after a caught trial/I2C error. Python Ctrl-C requests a stop between trials and
waits for restoration. Do not forcibly kill Vivado while it is restoring.
If restoration reports an error, inspect the log before running the controller.
After successful restoration, refresh PCIe from your terminal:

```bash
sudo sh -c '
device=/sys/bus/pci/devices/0000:ab:00.0
if [ -r "$device/vendor" ] && [ "$(cat "$device/vendor")" = "0x10ee" ]; then
    echo 1 > "$device/remove"
fi
echo 1 > /sys/bus/pci/rescan
'
sudo modprobe xdma
```

## Startup timing instrumentation

The updated diagnostic also records native GTY RXCDRLOCK, the GT Wizard CDR
stable estimate, RXRESETDONE, Aurora block synchronization and its propagation
permission, wrapper CDR-reset and HP/PMA-reset activity, lane_up, channel_up,
combined PLL/reset readiness (`gt_pll_lock`), system/explicit Aurora/GT reset, hard/soft errors, and MMCM status on both QSFP3
and QSFP4. Exposing existing status wires does not change initialization settings.
`build.tcl` reapplies the generated-wrapper status-port patch and disables IP
synthesis cache reuse; regenerated wrappers must not silently lose the patch.

Run the same `--guard-sweep` command. Additional outputs:

- `startup_raw.csv`: frozen FPGA register snapshots per trial.
- `startup_timing.csv`: decoded per-signal first high, last rise/fall, counts,
  initial/final state, and final high interval start, all in microseconds.
- `startup_summary.json`: grouped final-state and transition statistics.

Recording begins when the diagnostic controller is aborted, before laser disable
and the dark interval. Time zero in the CSV is still QSFP3 enable-write STOP.
Negative times indicate an event before that origin. An initially high signal
has a first-high time at the observation window start, not a newly measured
lock event. `final_high_since_us` is the start of the final observed high
interval; it is useful when lock/reset signals toggle repeatedly. Blank times
mean not observed. Failed short-guard trials are censored at their deadline,
so absence of a later event does not imply it never happens.

The observer samples two-flop synchronized levels at 200 MHz. Timing has a few
cycles of synchronization uncertainty. Pulses shorter than a sampling period
may be missed; transition counts saturate at 32767. The existing native-domain
sticky hard/soft error flags in trials.csv remain the error reference. AMD UG578 marks RXCDRLOCK as reserved, so `cdr_lock_raw_reserved` is only a
raw diagnostic and must not be interpreted as reliable physical lock timing.
In this generated GT Wizard version, the helper CDR-stable output is a
synchronized copy of that raw signal; reset completion can alternatively use
a timeout. Neither CDR field establishes valid received data or optical power.
Aurora `gt_pll_lock` is documented as TX-clock stability, not a direct QPLL-lock
measurement. RX reset done, block sync, lane/channel readiness are the useful
functional milestones. See [UG578](https://docs.amd.com/api/khub/documents/BY7rRWkUQliMvNvosLhSZA/content)
and [Aurora status ports](https://docs.amd.com/r/en-US/pg074-aurora-64b66b/Status-Control-and-Transceiver-Ports).
DOM still cannot measure laser turn-on. Without external optical measurement,
these timestamps localize digital recovery stages, not internal module settling.
Both directions are observed because duplex Aurora readiness requires the
reverse/control path as well as the forward payload path.

## Steady-light control experiment

`--guard-test illuminated-reset` keeps TX2 on both modules enabled, holds
Aurora's explicit `reset_pb` for `--guard-dark-ms` milliseconds, then releases
reset and records recovery. This uses the existing diagnostic image and does
not assert the independent PMA-reset input. `--guard-test compare` interleaves
these controls with normal bursts, pairing seeds and alternating order.
`--guard-reset-mode` applies to burst trials; the illuminated control always
uses explicit reset. Default `--guard-test burst` preserves previous behavior.

Example:

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-test compare --guard-reset-mode keep \
  --guard-us 50000,20000,5000,1000,100 --guard-dark-ms 1000 --guard-trials 10
```

**Timing origins differ:** burst startup timestamps are relative to QSFP3's
enable-write STOP; illuminated-reset startup timestamps are relative to the
VIO reset-release/arm command. Existing engine guard timing in the latter starts
after the generator/checker's clock-domain arming acknowledgments. Therefore
use startup_timing.csv to compare recovery from reset release; a nominal short
illuminated guard passing does not by itself establish that recovery finished
within that interval of reset release. `dark_ms` in an illuminated-control row
means reset hold time; lasers are not disabled. Module writes reassert the same
TX-enable setting before the hold, allowing steady light before release.

This control separates steady-light recovery from recovery after darkness,
but does not uniquely measure optical-module settling: automatic GT resets,
alignment and reset-entry state can differ between the two conditions.

## Steady-light receiver-reset control

The updated diagnostic exposes config bit4 to each GT Wizard's
`gtwiz_reset_rx_datapath_in`, ORed with its existing automatic receiver reset.
It leaves the TX reset controls and common PLL configuration unchanged. The
module lasers remain enabled. The default bit4 value is zero.

`--guard-test illuminated-rx-reset` holds this receiver reset together with
Aurora reset for `--guard-dark-ms`, with light ON, then releases both. The
startup recorder's origin is release. The Wizard holds its reset helper while the request is high, then executes
the physical reset sequence after release. For trials observed for at least
5 us, the script requires RXRESETDONE low initially or a falling edge on both sides to confirm
actual receiver reset and reject an old bitstream without the control.
`--guard-test compare-all` interleaves burst, steady-light Aurora-only reset,
and steady-light RX + Aurora reset trials with paired seeds and alternating order.
`--guard-reset-mode` still controls only the burst condition. This RX control
requires the rebuilt diagnostic bitstream; the earlier steady-light Aurora-only
mode needs no hardware changes. This is a receiver datapath reset, not a reset
of the optical modules or a deliberate TX/common-PLL reset.

### Generated PLL-status qualification

The generated wrapper drives `PLLLKDET_OUT` (exported as `gt_pll_lock`) from
QPLL lock AND synchronized TX/RX reset-helper completion. The observer names
this `pll_and_reset_ready`. It can fall during receiver reset without a loss
of physical PLL lock or a TX-clock stoppage. Earlier CSVs called this field
`tx_clock_stable` following the generic port description; do not interpret it
as a direct PLL-lock or TX-clock measurement.

## Timed receiver restart after laser enable

`--guard-test burst-restart` holds RX datapath reset requests during darkness,
then a hardware timer releases them at the chosen delay after QSFP3 enable STOP.
No software sleep or JTAG transaction controls this timing edge. Config bit5
selects the sequencer; config[31:8] contains the delay in 5 ns ticks. Bit4 remains
the independent manual RX reset control. Default bit5 is zero.

`--guard-rx-release-us 0,100,500,1000` sweeps release delays. Delays must be less
than every guard deadline. `--guard-test compare-restart` interleaves paired
normal bursts (no explicit reset) and controlled-restart bursts for each delay.
The ordinary reference is pooled across repeated pairs at the same guard.
`--guard-reset-mode` does not change these two specific comparison conditions.

Example:

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-test compare-restart \
  --guard-us 5000,2000 --guard-rx-release-us 0,100,500,1000 \
  --guard-dark-ms 1000 --guard-trials 10
```

This requires the rebuilt timed-restart diagnostic. Startup metadata bit66
advertises the capability. In that image, observed signal14 is now
`diagnostic_rx_reset_request` on each side, replacing the rarely active GT/PMA
reset output; the decoder retains `gt_reset` for older snapshots without bit66.
The runner checks that the observed RX request falling edge matches the selected
release delay within 50 ns (allowing synchronization/sampling uncertainty).
`rx_release_us` is included in plan/trials and both grouped summaries. Guard
remains command-to-payload time from forward TX enable STOP. Clock recovery and
automatic core recovery are not bypassed. This is a controlled-recovery test,
not a direct optical turn-on measurement or a production change.

## Native header/alignment windows

The header-activity diagnostic build adds passive, free-running counters in each
Aurora receiver's native RX clock domain. It captures cumulative snapshots every
100 us, from QSFP3's TX-enable I2C STOP until trial completion. For an illuminated
control the origin is reset release/arming. Readback happens after capture has
frozen and therefore does not delay the measured recovery.

Example (keeps the current optical path and attenuation):

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-reset-mode keep \
  --guard-test compare-all --guard-us 20000 --guard-dark-ms 1000 \
  --guard-trials 5 --guard-baseline-trials 3 --guard-baseline-us 20000 \
  --guard-header-trace
```

Requires the newly built header-activity diagnostic image; the runner restores
the working streaming image afterward. Readback adds JTAG time between trials.
The baseline observation interval defaults to zero for existing commands.

Outputs: `header_activity_raw.csv` (raw snapshots), `header_activity.csv`
(per-window counter differences), and `header_activity_summary.json`.
Each receiver has 16 counters: native clock cycles, data-valid and header-valid
cycles, legal and illegal headers, gearbox-slip edges, block-sync occupancy and
rising edges, alignment-reset occupancy, six alignment FSM state occupancies,
and alignment-reset rising edges.

The recorder stores at most 256 snapshots (initial plus 255 windows); longer
trials set the overflow flag and retain only the early recovery interval.
Snapshots use registered Gray counters and two-stage clock-domain crossings;
each metric has a few native cycles of sampling uncertainty. Counters wrap
modulo 2^32; interpret short window differences, not absolute count values.
Native-clock pauses during reset are recorded as fewer native cycles.

**Interpretation:** `RXHEADERVALID` means that an interface header is available,
not that it is correct. Random two-bit values give legal 01/10 headers about
half the time. Look for the illegal-header fraction approaching zero together
with block synchronization and intact received test payloads. These observations
cannot directly measure laser settling or analog CDR lock.

## Native PRBS versus Aurora recovery

Use the native GTY PRBS31 generator/checker to separate recovery of a known bit
sequence from Aurora framing and automatic receiver-reset policy:

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-test prbs-compare \
  --guard-reset-mode keep --guard-us 20000 --guard-dark-ms 1000 \
  --guard-trials 5 --guard-baseline-trials 3 \
  --guard-prbs-quiet-us 100 --guard-header-trace
```

This requires the PRBS diagnostic build. `--guard-us` is the observation window
for native PRBS and the launch deadline for paired Aurora trials. Native PRBS
runs continuously throughout its observation; it does not send HHQ1 packets.

Validation runs first: near-end PMA loopback, deliberate errors in that loopback,
illuminated optical baselines, and deliberate errors transmitted over the
forward optical path. A failed validation stops the comparison and restores the
working image. The runner then alternates PRBS and Aurora OFF/ON trial ordering.

For native PRBS, the checker is held reset before each observation and released
at the QSFP3 TX-enable I2C STOP. The continuously illuminated baseline uses a
hardware trigger. Aurora-driven GT receiver restarts, gearbox-slip requests to
the GTY, and automatic polarity changes are suppressed in native PRBS mode.
The serial pattern and reset policy therefore differ between the two modes;
this comparison does not isolate only the Aurora header counter.

The native PRBS lock indication is sticky. Recovery qualification also requires
a running native RX clock, RX reset-done, and a continuous quiet interval with
no `RXPRBSERR` indications. The default interval is 100 us (configurable from
10 to 10000 us). The timer uses 5 ns ticks, with several clock cycles of CDC and
checker latency. A 1 us native-clock watchdog prevents a stopped receiver clock
from masquerading as a quiet link.

`prbs_trials.csv` records first lock, first qualified quiet interval, last error,
error-indicated native cycles, native clock cycles, longest quiet interval and
errors after first qualification. These error-indicated cycles are **not exact
bit-error counts or BER**. `prbs_summary.json` and `PRBS_README.md` summarize the
results and pair them with Aurora's `trials.csv`. A finite error-free interval
does not guarantee future error-free packets.

Reference: AMD [UG578, RX Pattern Checker and TX Pattern Generator](https://docs.amd.com/api/khub/documents/BY7rRWkUQliMvNvosLhSZA/content),
particularly Tables 4-24/4-25 and 3-25. This build uses synchronous gearbox mode
`00001`; the additional asynchronous-gearbox PRBS switching procedure does not
apply. PRBS31 selector is `0101`; RXPRBSLOCKED remains asserted until checker
reset, and RXPRBSERR is a non-sticky indication rather than a precise bit count.

### Native PRBS with scheduled RX-reset request release

The `prbs-restart` test uses the existing hardware reset sequencer. Example:

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-test prbs-restart \
  --guard-reset-mode keep --guard-us 20000 --guard-dark-ms 1000 \
  --guard-trials 3 --guard-baseline-trials 2 --guard-prbs-quiet-us 100 \
  --guard-rx-release-us 0,1000,5000,10000
```

Each repetition includes a no-restart reference and the requested reset delays.
These are **reset-request release times** after laser enable. The GT Wizard
performs its physical RX reset sequence afterward; holding its request high does
not imply the native RXRESETDONE signal is already low throughout the hold.
Acquisition before a scheduled restart is excluded from post-reset timing.
Intentional reset/stall flags remain in the raw results and should be interpreted
with the planned release time. Reverse RX is illuminated before the forward
origin, so it may acquire before the scheduled reset and is not the primary
optical OFF/ON measurement.
# GTY adaptation hold sweep

`prbs-hold` holds only QSFP4 RX2 / GTY X1Y58 after a clean, illuminated
native PRBS check. Other module settings, fiber and attenuation remain those
of the existing experiment. Each trial starts with receiver normalization
under steady light, then requires a clean 1 ms PRBS check immediately before
hold assertion. There is no deliberate RX reset during darkness or capture.

The equalizer group freezes AGC, LF, KH, CFOK, UT, VP, offset cancellation and
DFE taps 2..15 using the documented HOLD inputs, with overrides kept zero.
The CDR group uses RXCDRHOLD. Holding that loop / locking to reference does
not preserve sampling phase relative to the returning signal. Both groups
are asynchronous GTY inputs driven from the always-running 200 MHz init clock.

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-test prbs-hold \
  --guard-reset-mode keep --guard-us 20000 --guard-dark-ms 1000 \
  --guard-trials 3 --guard-baseline-trials 2 --guard-prbs-quiet-us 100 \
  --guard-hold-modes none,equalizer,cdr,both \
  --guard-hold-release-us 0,10,100,500,1000,2000,5000,10000
```

The no-hold reference runs once per repetition; each other mode runs at every
release delay. Steady-light controls hold each mode for the largest delay
without darkness. Release is timed from the successful QSFP3 TX-enable I2C
STOP. Pin-level return signals confirm assertion before darkness and release
timing; they do not report hidden analog state. Physical optical onset is
not measured. The default observation window is the specified `--guard-us`.

Results include `hold_trials.csv`, `hold_summary.json`, `HOLD_README.md`,
and the native `prbs_trials.csv`. Error indications count native clock cycles,
not precise bit BER. Qualification is a finite 100 us quiet interval; later
errors and the final quiet tail are reported separately. A steady-light hold
control that introduces errors invalidates a simple state-retention claim for
that mode. No improvement does not prove that the QSFP alone is responsible.

The diagnostic image needs the receiver-hold update (`scripts/rebuild_startup.tcl`).
The working streaming image and module byte 86 are restored at exit. Rescan
PCIe before subsequent XDMA use, as described below.

