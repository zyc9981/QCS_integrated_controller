# Steady-light Aurora reset control

Run: `FPGA_HH_QSFP/burst_guard/measurements/20261016_003905_286021`.

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-test compare --guard-reset-mode keep \
  --guard-us 50000,20000,5000,1000,100 --guard-dark-ms 1000 \
  --guard-trials 10 --guard-baseline-trials 20
```

## Conditions

1. Burst: lasers off for 1 second, no explicit Aurora reset, then enable the
   reverse transmitter first and time forward QSFP3 enable STOP.
2. Illuminated reset: TX2 on both modules stays enabled, explicit Aurora reset
   is held for 1 second, then released. The startup recorder's origin is the
   VIO reset-release/arm command. This is reset_pb, not a PMA reset.

Paired seeds, alternating condition order, unchanged fibers/attenuation and
clock/swing settings. The existing timestamp diagnostic bitstream was used;
this feature required host/Tcl changes only. Python/Tcl syntax and mocked plan
checks for paired seeds, alternating order and reset modes passed.

## Results

Baseline: 20/20 complete and intact.

| Nominal guard | OFF/ON: intact | Steady light + Aurora reset: intact |
| --- | ---: | ---: |
| 50 ms | 10/10 | 10/10 |
| 20 ms | 9/10 | 10/10 |
| 5 ms | 1/10 | 10/10 |
| 1 ms | 0/10 | 10/10 |
| 100 us | 0/10 | 0/10 |

All complete frames had zero bit errors. Other attempts were not ready at the
deadline. One not-ready burst (ID92) saw a spurious one-word RX fragment with
39 differing bits and early-end/keep/soft-error flags before payload launch;
this is not a completed test frame and is excluded from full-frame BER.
There were no receive timeouts.

The illuminated-control engine guard starts after clock-domain arm ACKs, while
startup timestamps start at reset release. Per-event timestamps, rather than
nominal guard thresholds alone, provide the direct recovery measurement.

Across the successful 50 ms trials, the later of the two final channel-up edges:

| Condition | Minimum | Median | Maximum |
| --- | ---: | ---: | ---: |
| Steady light + Aurora reset | 318.650 us | 318.655 us | 318.660 us |
| Laser OFF/ON | 6.655 ms | 8.683 ms | 10.730 ms |

For OFF/ON, this is final stable readiness, which can be later than the engine's
first-ready timestamp if readiness drops and returns before payload launch.
Times use the distinct origins defined above and do not measure laser light-on.

## What this establishes

With steady light and an already initialized GTY, Aurora can rebuild its lane/
channel in about 0.32 ms. A representative control (ID21) had block sync at
307.370/307.375 us on QSFP4/QSFP3 and channel up at 318.655/307.550 us.
RXRESETDONE stayed high, and the wrapper CDR-reset and HP/PMA-reset signals
had no transitions in all ten successful 50 ms control trials. The approximately
0.307 ms block revalidation is consistent with the generated 60,000-header
acceptance window.

Thus the larger OFF/ON delay is associated with recovering from loss of light,
including module/electrical settling, GTY recovery and automatic reset/alignment
behavior. This control does not establish that the optical module alone is slow:
its steady-light GTY remained initialized, so the analog/retry path was different.
The next discriminating control is a deliberately forced GTY RX/PMA reset while
keeping light stable, compared with OFF/ON. That requires exposing an appropriate
reset control in the diagnostic design; no such reset was added or tried here.

RXCDRLOCK remains a reserved raw diagnostic and cannot measure actual CDR
acquisition. External fast optical detection is still needed for laser turn-on.
See the prior startup timing report and OPTICAL_GUARD_SWEEP.md for limitations.

## Restoration and repeating

The log confirms both module byte86 settings restored to 0 and the normal
working optical image reprogrammed. Refresh host PCIe before using XDMA again.
Future CLI use: `--guard-test burst` (default), `illuminated-reset`, or `compare`.
The FPGA diagnostic folder is ignored by Git; retain it separately with the
updated host files when copying the project.
