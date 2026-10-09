# HTG-930 working setup snapshot — 2026-10-09

Start with [STARTUP_COMMANDS.txt](STARTUP_COMMANDS.txt). This bundle was copied
from the working setup without changing the running FPGA or clock registers.

## Contents

- `bitstreams/hh_qsfp_top.bit` and `.ltx`: current optical streaming image and
  matching diagnostic probes; use these for normal controller operation.
- `bitstreams/htg930_clock_probe.bit` and `.ltx`: temporary I2C clock-loader image;
  always load the optical image afterward.
- `bitstreams/ibert_gty.bit`: archived GTY PRBS diagnostic image, not application
  data transport. Live swing settings require reapplication after loading.
- `bitstreams/pcie_fifo_loopback_top.bit`: internal FIFO loopback diagnostic;
  bypasses Aurora and optics. Not the normal controller image.
- `bitstreams/vendor_pcie_gen3_x16_example.bit`: vendor PCIe link diagnosis only.
- `clocks/`: exact ClockBuilder register sequence and current settings summary.
- `scripts/`: clock restore, optical programming, VIO diagnostic read/clear.
  Asset paths are relative to this bundle; no dependency on old build directories.
- `source_snapshot/`: build RTL/constraints and host files as they were when this
  bundle was created. Host snapshot is for reference, not a full standalone GUI
  installation. Startup commands run the current controller in the parent repo.
- `evidence/`: swing measurements and latest capture error log, not capture data.
- `MANIFEST.json`, `SHA256SUMS`: origins, sizes, and checksums.

## Observed status and limits

Aligned mmap host buffers passed five 500-block internal-loopback runs and
repeated 500-block optical runs. A subsequent approximately 600.090564-second
HH capture returned all 271,355,640 records (1,085,422,560 raw bytes), with one
flipped bit in block 13237. Local PTU payload and local source copy matched.
The controller logs mismatches and continues acquisition; it does not implement
error correction or retransmission. The command-line pattern test still stops
on its first mismatch. This is a reproducible working baseline, not an error-free
transport guarantee.

Clock and FPGA settings are volatile unless explicitly stored in NVM/flash;
these scripts do not do that. Do not use the stale bring-up status paragraphs
in the original FPGA_HH_QSFP README as the current startup procedure.

The copied binary assets are ignored by this folder's .gitignore to avoid
accidentally adding several hundred MB to Git. They exist locally and should be
included when copying/backing up this folder. No commit or upload was made.
