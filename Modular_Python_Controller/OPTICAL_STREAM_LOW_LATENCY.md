# Optional CPU low latency mode

Use `--low-latency` with optical_stream.py to request a maximum CPU idle exit
latency of 2 microseconds while streaming. It is off unless explicitly enabled.
An optional value, for example `--low-latency 1`, selects a different limit.

The request affects CPU idle policy system-wide while the descriptor is open.
It may increase power use. It does not set the CPU frequency governor. Normal
exit, stream failure and interruption remove this process's request when the
descriptor closes; Linux also closes it if the process is killed. Other active
latency requests remain in effect.

## Grant access on this machine

The device is root-only by default. Grant zyc access once for the current device
instance, then run the stream program as zyc:

```bash
sudo setfacl -m u:zyc:rw /dev/cpu_dma_latency
```

This ACL is normally lost at reboot when /dev is recreated. Reapply it if needed.
It grants permission to make a request; it does not itself activate low latency.
To remove the ACL manually, use `sudo setfacl -x u:zyc /dev/cpu_dma_latency`.

## Pattern verification

```bash
/home/zyc/QCS/Qchip_venv/bin/python \
  /home/zyc/QCS/QCS_integrated_controller/Modular_Python_Controller/optical_stream.py \
  --source pattern --pattern-blocks 100000 --profile --low-latency
```

This sends 6,552,000,000 payload bytes in 100,000 blocks, retains one block in
flight, and verifies every returned byte. The CLI stops on a mismatch and reports
the failed block. `--profile` prints aggregate timings instead of a line per block.
Omit `--low-latency` to run under the existing CPU idle policy. A permission error
is reported before opening XDMA or starting HH acquisition if the request fails.

## Integration scope

This option applies to the optical_stream.py CLI for pattern and HydraHarp
sources. `CpuIdleLatency` is also available as a context manager for future
controller integration. Existing callers of OpticalLink/capture_hh_qsfp do not
automatically request low latency. The controller can adopt the request after
longer verification.

Earlier six-run comparison on this machine: median normal 88.58 MB/s, median
low latency 182.03 MB/s, all 6,000 blocks verified. Performance varies with system
load; the idle request does not guarantee a particular throughput or eliminate
rare data corruption.
