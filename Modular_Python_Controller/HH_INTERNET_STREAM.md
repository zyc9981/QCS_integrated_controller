# Receiving HydraHarp records over TCP

The next stage is a disk-backed receiver and a raw-file replay sender:
`QCS_HH_stream_internet.py`. Both run with the Python standard library. They
do not import the controller, snAPI, XDMA, or Vivado, and do not open acquisition
devices. The current controller and `/home/zyc/QCS_HH_TX_internet.py` are unchanged.

## What the inspection found

The Linux pattern script is protocol v1, defaults to 65,536-byte blocks, requires
the entire transfer size in HELLO, and allocates the whole dataset before READY.
It validates generated patterns after receiving. It cannot accept arbitrary HH
records or a recording whose total size is initially unknown. Its SHA-256 at
inspection was `ebc1fcfba2c8b5f8e2a846149500f1b4d150fcf8311d74e0644808ca4cd6fcdd`.
The newer Windows copy was not available on Linux for comparison.

The new script uses protocol v2 and a different filename, so the working v1
benchmark can still be used. Use the **new script at both ends**. Its default
payload is 1,024 bytes (256 raw 4-byte records). Short, record-aligned frames
are permitted, including a final frame smaller than 1 KiB.

## First actual-data test: replay a completed raw file

This step validates reception and saving of actual recorded bytes. It does not
start a live acquisition or coordinate a second instrument's start time.

Copy the new script to Windows, from a Windows terminal in the repository root:

```powershell
scp zyc@158.130.30.167:/home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/QCS_HH_stream_internet.py .\Modular_Python_Controller\QCS_HH_stream_internet.py
```

On Linux, start a one-session receiver (choose a fresh output name every run):

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/QCS_HH_stream_internet.py \
  receive --bind 0.0.0.0 --port 50050 \
  --output /home/zyc/QCS/hh_network_trial01.bin --quiet
```

On Windows, replay a **completed raw T2 record file**:

```powershell
python .\Modular_Python_Controller\QCS_HH_stream_internet.py send-file `
  --host 158.130.30.167 --port 50050 `
  --input "C:\path\to\completed_HH_raw.bin" --block-size 1024
```

Use the Windows Python executable you normally use if `python` is not configured.
Do not run a pattern receiver concurrently on the same port. The new script exits
after one session. The default inactivity timeout is 30 seconds and can be set
with `--timeout` at each end; it is not a total recording-duration limit.

Raw input means little-endian 32-bit HH400 T2 records, including special/overflow
records, with no PTU header or network header. `.ptu`, `.ttbin`, and `.h5` inputs
are rejected. A different container renamed `.bin` is still invalid: transport
integrity cannot establish that bytes are meaningful HH records. Existing
QSFP `.source.bin` raw HH files can be used. Replaying an actively growing file
is rejected; a live capture adapter must use the separate streaming API.

Outputs:

- `hh_network_trial01.bin`: original concatenated record bytes; no TCP framing.
- `hh_network_trial01.bin.json`: session ID, declared format, metadata, counts,
  SHA-256, and completion/error status.
- On failure, `hh_network_trial01.bin.part`: only the completely received,
  CRC-validated prefix; no final `.bin` is published. A partial TCP frame is
  discarded. Retain the Windows original for retry under a fresh output name.

No existing output, partial output, or manifest is overwritten. An absent output
directory is an error. The receiver has a configurable `--max-bytes` cap
(default 16 GiB) and at most a 1 MiB block buffer; it does not reserve the entire
recording in RAM. Disk space must accommodate the recording. There is no resume
support yet. If the final acknowledgement is lost, the sender reports incomplete
confirmation even if the receiver has already completed its file; inspect the
Linux manifest before retrying.

## Integrity and timing

HELLO declares protocol v2, record layout, maximum block size, and optional
capture metadata. READY confirms that the receiver has reserved its destination.
START begins the transfer. Each binary frame has a network-order sequence
(`uint64`), payload length (`uint32`), and CRC-32 (`uint32`). The receiver checks
strict order, record alignment, limits, and CRC before writing. No per-block
roundtrip is required. A zero-length end frame is followed by END with total
blocks/bytes/records and SHA-256. EOF/timeouts are failures, not normal END.

The receiver validates END, flushes and fsyncs the data file, publishes the final
filename without replacing any existing file, updates the manifest, and replies
SAVED. The sender validates the acknowledgement's counts and digest. CRC/SHA
establish that transferred bytes match; they do not detect records already lost
inside the instrument/SDK before sending.

Reported stream rates include CRC, hashing, disk writes, and final file flush.
Sender timing also includes source-file reads and the final SAVED acknowledgement.
Receiver timing starts before its first frame read and ends after file publication,
before the final manifest write/acknowledgement. These are local monotonic-clock
intervals; no remote timestamps are subtracted. They are not directly equivalent
to the original RAM benchmark's verification-excluded timing or raw link speed.
For live data, the sender interval will include acquisition time as well.

Optional `send-file --metadata capture_metadata.json` preserves supplied device
configuration in the receiver sidecar. Include serial, T2 format/version, actual
base resolution, reference source, channel settings, capture times, and overflow
or loss reports when known. Resolution defaults to unknown, not an assumed value.

## Next implementation: Windows live HH capture

1. Validate this file replay on the real Windows-to-Linux link and compare
   complete file hashes. The prior 22–23 MB/s pattern result is a useful baseline,
   not a measurement of this disk-backed path or HH acquisition.
2. Build a standalone Windows adapter using the existing `picoquant_snapi.py`
   initialization and `raw.startBlock` / `raw.getBlock` APIs. Keep device ownership
   exclusive. Verify the installed Windows SDK and required HH configuration first.
3. A capture worker must drain the SDK into a local raw disk spool independently
   of networking. A sender worker can read only the committed, record-aligned
   prefix and feed `send_chunks(...)`. Keep a bounded memory buffer, preserve local
   bytes on disconnect, and expose pending bytes and acquisition/overflow errors.
   Do not call blocking socket sends directly from the SDK polling loop.
4. Signal producer completion only after the instrument finishes and its last
   block has been drained. Send END only after all committed records are sent.
   Record acquisition failure explicitly; do not silently declare a shortened
   recording complete. Implement interrupt/abort signalling in the adapter.
5. After live capture and transfer are validated, integrate readiness and a
   scheduled start with the Linux instrument. Millisecond start coordination
   and precise alignment of photon time tags are separate requirements.

`send_chunks` is source-neutral, but **does not itself implement this acquisition
worker or local spool**. There is no claim of live hardware capture support yet.
The existing SDK documentation warns that its block store can clear on overrun;
network delivery checks cannot recover that loss. Log and surface those events.

## Validation completed on Linux

Seven loopback tests passed: mixed/short chunks with a full-file hash, fragmented
TCP reads plus interrupted transfer, corrupt CRC, sequence/size-cap rejection,
bad final digest, existing-output protection, and inactivity timeout.

A separate command-line sender/receiver check transferred 2,097,156 bytes in
2,049 frames of up to 1 KiB. The saved file matched the source byte-for-byte,
including its final single record. See `HH_INTERNET_STREAM_VALIDATION.json`.
These tests used synthetic raw words, loopback TCP, and temporary files. No
campus-network transfer, Windows execution, or live HydraHarp recording was
performed in this Linux validation. No firewall/network/hardware settings changed.

```bash
/home/zyc/QCS/Qchip_venv/bin/python -m unittest discover \
  -s Modular_Python_Controller/tests -p test_hh_internet_stream.py -v
```
