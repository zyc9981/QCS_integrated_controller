# RAM to RAM optical roundtrip benchmark

Run from any terminal, with the existing HH/QSFP bitstream and XDMA driver loaded:

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --memory-benchmark --pattern-blocks 4096 \
  --block-size 65536 --pipeline-depth 2 --low-latency
```

This sends a 256 MiB dataset and receives it into a separate 256 MiB RAM buffer.
Use `--pattern-blocks 16384` for a 1 GiB dataset (2 GiB of buffer memory).
`--benchmark-json /path/to/new-file.json` optionally saves the results and the
first ten mismatched-block details. The result file must not already exist.
Omit `--low-latency` for normal CPU idle policy. Device permissions are the
same as for the existing streaming mode.

## What is measured

1. Allocate and touch two complete page-aligned RAM datasets. Fill the source
   with independent random payloads and the existing HHQ1 header/sequence/CRC
   in every block. Preparation and worker/device setup are outside the timer.
2. Release two waiting workers. One writes from the source buffer directly to
   H2C; the other reads C2H directly into the destination buffer. There are no
   per-block packet copies, pattern generation, verification or success prints
   during this timed interval.
3. End timing at the later of the final H2C and C2H syscall returns. Thus the
   whole dataset has left the source and returned to destination RAM. Main
   thread reporting/join delay is excluded. Native syscall returns still
   include worker resumption after kernel completion.
4. Compare every returned packet byte with its source after transfer completes.
   Report all mismatched blocks and the total number of different bytes. A
   mismatch does not truncate the dataset transfer. Exit status is 1 if any
   mismatch is found, 0 if all bytes match. Transport failures/timeouts abort.

`packet_MB_s` counts full packets including the 16-byte header. `payload_MB_s`
counts useful bytes only. Each divides the dataset size by elapsed seconds and
counts the dataset **once**, despite traversing both directions. MB/s is decimal;
dataset allocation sizes displayed as MiB/GiB are binary. Verification time is
reported separately and is not included in throughput.

## Bounds and limits

The sender consumes a credit before submitting each block; C2H completion
returns the credit. `--pipeline-depth 1` permits one unreceived block, and `2`
permits two. Their total size must not exceed the 128 KiB FPGA RX FIFO, since
Aurora RX cannot apply backpressure. The receiver continuously drains the link.
Block sizes must be multiples of the system page size so all block addresses
remain page aligned. Each read/write syscall still requests one block; the
benchmark does not queue the entire dataset into FPGA memory.

This measures the host-to-host memory path including Python worker coordination,
driver submission/completion, PCIe and the optical path under these bounds. It
does not establish the maximum possible rate with a different driver or FPGA
buffering design. There is no FEC or retry. Treat throughput from a run containing
mismatches as a transfer-rate observation, not an error-free throughput result.

The benchmark is opt-in, pattern-only and separate from HydraHarp/controller
capture. Existing exchange/profile behavior is unchanged. No FPGA programming
or permanent CPU setting change is needed.
