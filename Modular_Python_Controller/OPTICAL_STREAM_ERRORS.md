# Streaming mismatch handling

The standalone pattern command now continues after a completed-block data
mismatch, including with the legacy engine, profiling, or pipeline depth 2:

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --pattern-blocks 500 --block-size 65536 --quiet
```

On the first mismatch it prints an error-log path. By default this is a new
`qsfp_errors_<timestamp>_<pid>.log` in the terminal's current directory. Every
mismatch is logged with its block number, differing-byte count and offsets,
header details, and CRC details. The file is flushed after each error. No log
file is created on a clean run. To choose a path, add `--error-log /path/to/new.log`;
the directory must exist and the file must not already exist.

`--quiet` hides per-block success messages; it does not suppress the log path
or final totals. A completed run prints completed, verified, and mismatched
block counts. Exit status is 0 for a clean run and 1 after the full run if any
blocks mismatched. This failure status does not mean the run stopped early.

DMA timeouts, failed reads/writes, and other exceptions still stop the stream;
the link may no longer be synchronized. A mismatch means a full block returned
with incorrect bytes. Continuing does not correct those bytes, retransmit them,
or restore framing after lost stream data. If headers are displaced, subsequent
blocks may also mismatch.

Standalone HydraHarp streaming uses the same continuation behavior. Its
`--output` includes corrupt returned payloads, identified by the log; it is not
a separate copy of the original acquisition. The GUI's `capture_hh_qsfp` retains
its existing separate original/returned files and continues local acquisition
after a QSFP transport failure.

The RAM benchmark already transfers the dataset before checking it; its
reporting uses `--benchmark-json` rather than `--error-log`.

## BER mode

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --ber --pattern-blocks 500 --block-size 65536 --quiet
```

`--ber` generates independent random payloads for each block, rather than the
normal repeating byte pattern. It compares complete sent/returned packets,
counts differing bits using XOR/popcount, and reports `differing bits / compared
bits`. All packet bits are counted, including the HHQ1 header and padding.
Mismatch logs include each block's differing-bit count. A summary is printed
even with `--quiet` and is also appended to the error log when one exists.

This is an observed host-to-host packet BER, not an IBERT PRBS or raw optical
lane BER: encoding, idles, and incomplete transfers are excluded. Header
mismatches are counted separately because stream misalignment can inflate the
ratio. No completed blocks means BER is unavailable; zero differing bits means
zero observed errors over the reported sample, not a guarantee of zero BER.

Transport failures still stop the run, print a partial summary, and exit with
status 1. The summary separates completed blocks, transport failures, and
requested blocks not compared (which includes unattempted blocks). It does not
assign a guessed bit-error count to unreceived data or automatically reset DMA.
Use `--pattern-blocks` to set test length. No FPGA reprogramming is needed.
