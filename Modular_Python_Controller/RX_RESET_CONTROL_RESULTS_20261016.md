# Steady-light GTY receiver-reset control

Run: `FPGA_HH_QSFP/burst_guard/measurements/20261016_005927_110502`.

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --guard-sweep --guard-test compare-all --guard-reset-mode keep \
  --guard-us 50000,5000,1000,500,100 --guard-dark-ms 1000 \
  --guard-trials 10 --guard-baseline-trials 20
```

## Implementation and checks

Diagnostic config bit4 is exposed through the generated Aurora wrappers and
ORed into each GT Wizard `gtwiz_reset_rx_datapath_in`. TX reset and common PLL
reset inputs are unchanged. Lasers stay enabled in receiver-reset trials.
Aurora reset is asserted with the RX reset request, then both requests are
released. The Wizard executes its physical RX reset sequence after request
release; this is the startup timestamp origin. It is not an optical-module
reset or a requested TX/common-PLL reset.

The diagnostic image was rebuilt. Setup WNS +0.595 ns, hold WHS +0.010 ns,
no failing timing endpoints; routed bus-skew constraints met. Synthesis,
implementation and bitstream generation passed. Host plan checks confirmed
three conditions, paired seeds and alternating order. Tcl reset-observation
checks passed: both native RXRESETDONE signals were observed low during each
receiver-reset trial. Raw snapshots/decoded timestamps preserve the evidence.
The earlier diagnostic bit/probes are backed up in backups/pre_gt_reset.

The script restores module byte86 and the normal working streaming image after
the run. Both restored byte86 values were 0, and final image restoration was
confirmed in vivado.log. Host PCIe rescan remains necessary before XDMA use.

## Outcomes

20/20 continuous baseline frames were intact.

| Nominal guard | OFF/ON intact | Aurora reset, steady light: intact | RX + Aurora reset, steady light: intact |
| --- | ---: | ---: | ---: |
| 50 ms | 9/10 | 10/10 | 10/10 |
| 5 ms | 1/10 | 10/10 | 10/10 |
| 1 ms | 0/10 | 10/10 | 8/10 |
| 0.5 ms | 0/10 | 9/10 | 0/10 |
| 0.1 ms | 0/10 | 0/10 | 0/10 |

At 1 ms, receiver-reset trials included one not-ready attempt and one complete
frame with 3 differing bits (ID82, TX/RX soft-error flags). All other complete
frames were intact. Remaining failures were not ready at the deadline; no
receive timeouts. Channel-up alone therefore does not guarantee immediately
error-free reception. These small samples do not establish a safe minimum guard.

## Recovery from direct timestamps

For successful 50 ms trials, take the later of the final channel-up edges on
QSFP3 and QSFP4 in each trial:

| Condition | Minimum | Median | Maximum |
| --- | ---: | ---: | ---: |
| Steady-light Aurora reset | 318.650 us | 318.655 us | 318.670 us |
| Steady-light RX + Aurora reset | 682.110 us | 689.915 us | 1036.050 us |
| Laser OFF/ON | 7.454 ms | 8.809 ms | 9.857 ms |

For steady-light RX reset, forward receiver QSFP4 milestones (successful 50 ms
trials):

| Milestone | Minimum us | Median us | Maximum us |
| --- | ---: | ---: | ---: |
| Final native RXRESETDONE assertion | 363.090 | 367.043 | 368.700 |
| Final block-sync assertion | 674.000 | 677.253 | 1035.870 |
| Final channel-up assertion | 682.110 | 689.915 | 1036.010 |

The typical sequence is about 0.37 ms of RX reset/reinitialization, then about
0.31 ms of header alignment/validation, followed by channel readiness. Some
trials need additional alignment time. Medians of independent stages are not
additive per-trial durations.

OFF/ON timestamps start at forward transmitter enable-write STOP. Steady-light
control timestamps start at reset-request release. The engine guard starts
later, after clock-domain arm ACKs; the figures above use direct startup
register timestamps, not nominal guard thresholds. OFF/ON may become ready,
lose readiness and return before payload launch; its final observed up edge
can be later than the engine's first-ready time. The 50 ms failure was not
silently excluded from the acquisition table; it is censored from readiness
latency statistics because readiness did not complete in that window.

## What we can conclude

Receiver datapath reset/reinitialization with an already present optical signal
usually completes in under about 1 ms in this setup. It does not inherently
require the 5–10+ ms commonly seen after darkness. The additional delay is
associated with restoring the optical/electrical stream after loss of light
and its ensuing alignment/reset/retry behavior.

This narrows the cause but does not distinguish optical transmitter enable/
settling, QSFP receiver reacquisition, and FPGA alignment/retry state after a
loss of light. It does not prove the optical module alone is responsible.
Physical light-on timing still requires a fast optical detector; module DOM
cannot resolve that timing. RXCDRLOCK remains a reserved raw diagnostic and
cannot establish analog CDR acquisition time.

## Status-label qualification

The generated wrapper's exported `gt_pll_lock` is QPLL lock AND synchronized
TX/RX reset-helper done, not a raw physical PLL-lock or clock-running indicator.
The decoded CSV now calls this field `pll_and_reset_ready`. Its falling during
RX reset does not prove that the transmitter clock stopped or QPLL lost lock.
Earlier CSVs used the generic label `tx_clock_stable`; interpret those using
this implementation-specific qualification.

## Repeating just the receiver control

Use `--guard-test illuminated-rx-reset` with normal guard options. The diagnostic
bitstream must include the new receiver reset control. `compare-all` runs all
three conditions. The working production streaming image is unchanged. Keep
this ignored FPGA folder with the host scripts and MANIFEST.json when copying.
