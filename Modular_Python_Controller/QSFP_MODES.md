# QSFP modes in the controller

The TimeTag window and HH → QSFP window share one QSFP checkbox, mode selector,
guard field and hardware connection. Enable QSFP and wait for its status before
starting acquisition. Mode and guard are saved in `qsfp_mode_settings.json`;
QSFP starts unchecked on application launch. Controls lock while either window
is acquiring or transmitting. Changing a mode never programs the FPGA.

Continuous keeps QSFP3 TX2 enabled while QSFP is checked and streams HH records
during acquisition. Burst keeps TX2 off during acquisition, preserves the full
batch in `<output>.source.bin`, then sends that completed acquisition. It opens
the laser once for the batch, not once for every 64 KiB DMA packet. Stop Writing
ends acquisition; the batch transfer then finishes before the controls unlock.
The guard defaults to 15 ms and accepts 0..1000 ms. The FPGA counts it from the
successful TX-enable I²C STOP to payload-gate release. No timed CDR hold/release
or externally scheduled RX reset is used. QSFP4's reverse transmitter stays off.

15 ms is provisional: earlier runs showed occasional receiver recovery beyond
20 ms. Choosing a guard does not guarantee RX readiness. Mismatches are logged
and completed corrupt returns are retained; transport failures stop QSFP
submissions while continuous HH acquisition continues locally. Original data,
returned data and `.error.txt` logs remain separate.

## One-time image setup

The mode-capable, previously built simplex image and matching probes are copied
to `FPGA_HH_QSFP/controller_modes_20261018/`. Its manifest records the original
image and SHA256 hashes. With the controller and other XDMA clients closed:

```bash
/home/alzhu/vivado_dl/2025.2/Vivado/bin/vivado -mode batch -source \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/program_qsfp_modes.tcl
sudo sh -c 'echo 1 > /sys/bus/pci/devices/0000:ab:00.0/remove; echo 1 > /sys/bus/pci/rescan'
```

Launch python_controller, open TimeTag or HH → QSFP, select mode and enable QSFP.
The first enable starts one background Vivado connection; later mode changes
reuse it. Do not open a competing Vivado hardware session while the controller
owns it. Disabling QSFP or exiting the app closes the payload gate and disables
TX2. The bridge also requests darkness when its client disconnects or its parent
process exits.

`QSFP_VIVADO` can override the Vivado executable; `QSFP_PROBES_FILE` can override
the matching .ltx path. An incompatible loaded image produces an error before
the bridge changes FPGA outputs. Control errors appear in the status and TX log.

JTAG/I²C command latency adds time before and after each burst. The guard itself
uses the FPGA clock. The guard ends at the payload gate; physical first-bit
transmission can occur later if the local TX datapath is not ready. Laser-off
status confirms the TX_DISABLE register readback, not a measured optical level.

For a separate 500-block pattern check with the same mode controls, close the
controller and run:

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --link-mode burst --guard-ms 15 --pattern-blocks 500 --quiet
```

Use `--link-mode continuous` for the continuous check. Each pattern invocation
is one batch; the control connection closes and disables TX2 when it exits.
The optional `--link-mode` CLI flag applies to pattern testing. GUI HH recording
uses `capture_hh_qsfp` with the selected mode and complete acquisition batches.
