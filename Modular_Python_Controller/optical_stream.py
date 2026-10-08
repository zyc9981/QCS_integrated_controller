#!/usr/bin/env python3
"""Send fixed blocks through XDMA -> QSFP3 -> QSFP4 -> XDMA.

This program needs a loaded hh_qsfp bitstream and Xilinx's XDMA Linux driver.
It owns the HydraHarp during --source hydraharp; close other HH applications.
The output file contains raw little-endian 32-bit T2 records, not PTU headers.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import statistics
import struct
import threading
import time
import zlib

BLOCK_SIZE = 65536
HEADER = struct.Struct("<4sIII")
MAGIC = b"HHQ1"
PAYLOAD_SIZE = BLOCK_SIZE - HEADER.size


def _read_exact(fd: int, count: int) -> bytes:
    chunks = []
    remaining = count
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            raise EOFError(f"XDMA C2H returned EOF with {remaining} bytes missing")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            raise OSError("XDMA H2C made no progress")
        view = view[count:]


def _packet(sequence: int, payload: bytes) -> bytes:
    if len(payload) > PAYLOAD_SIZE or len(payload) % 4:
        raise ValueError("payload must be 32-bit records and fit in one block")
    header = HEADER.pack(MAGIC, sequence, len(payload), zlib.crc32(payload))
    return (header + payload).ljust(BLOCK_SIZE, b"\0")


def _benchmark_thread_pair(iterations: int) -> None:
    """Measure Python thread-pair creation/start/join with no device I/O."""
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        threads = [threading.Thread(target=lambda: None) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        samples.append(time.perf_counter() - started)

    print(f"No-I/O thread-pair benchmark ({iterations} iterations):")
    print(f"  median: {statistics.median(samples) * 1000:.3f} ms per pair")
    print(f"  mean:   {statistics.mean(samples) * 1000:.3f} ms per pair")
    print(f"  min/max: {min(samples) * 1000:.3f} / {max(samples) * 1000:.3f} ms per pair")


class OpticalLink:
    """One 64 KiB transaction at a time, with C2H posted before H2C."""

    def __init__(self, h2c: Path, c2h: Path, timeout: float):
        self.h2c_path = h2c
        self.c2h_path = c2h
        self.timeout = timeout
        self.h2c_fd: int | None = None
        self.c2h_fd: int | None = None
        self.sequence = 0

    def __enter__(self):
        self.c2h_fd = os.open(self.c2h_path, os.O_RDONLY)
        try:
            self.h2c_fd = os.open(self.h2c_path, os.O_WRONLY)
        except BaseException:
            os.close(self.c2h_fd)
            raise
        return self

    def __exit__(self, *_):
        if self.h2c_fd is not None:
            os.close(self.h2c_fd)
        if self.c2h_fd is not None:
            os.close(self.c2h_fd)

    def exchange(self, payload: bytes) -> bytes:
        if self.h2c_fd is None or self.c2h_fd is None:
            raise RuntimeError("XDMA devices are not open")
        expected = _packet(self.sequence, payload)
        result: dict[str, bytes | BaseException] = {}
        ready = threading.Event()
        deadline = time.monotonic() + self.timeout

        def receiver():
            ready.set()
            try:
                result["data"] = _read_exact(self.c2h_fd, BLOCK_SIZE)
            except BaseException as exc:
                result["error"] = exc

        reader = threading.Thread(target=receiver, daemon=True)
        reader.start()
        ready.wait()
        # One complete block fits in the RX FIFO even if the kernel has not
        # submitted the C2H descriptor by the time H2C starts.

        def sender():
            try:
                _write_all(self.h2c_fd, expected)
            except BaseException as exc:
                result["write_error"] = exc

        writer = threading.Thread(target=sender, daemon=True)
        writer.start()
        writer.join(max(0, deadline - time.monotonic()))
        if writer.is_alive():
            raise TimeoutError("H2C write stalled; check PCIe and both Aurora links")
        if "write_error" in result:
            raise RuntimeError("XDMA H2C write failed") from result["write_error"]
        reader.join(max(0, deadline - time.monotonic()))
        if reader.is_alive():
            raise TimeoutError("No C2H block returned; check PCIe and both Aurora links")
        if "error" in result:
            raise RuntimeError("XDMA C2H read failed") from result["error"]
        received = result["data"]
        if not isinstance(received, bytes) or len(received) != BLOCK_SIZE:
            raise RuntimeError("C2H returned an incomplete block")
        magic, sequence, length, checksum = HEADER.unpack_from(received)
        actual_payload = received[HEADER.size : HEADER.size + length]
        if (magic, sequence, length, checksum) != (
            MAGIC,
            self.sequence,
            len(payload),
            zlib.crc32(actual_payload),
        ) or actual_payload != payload or received != expected:
            raise ValueError(f"Optical data mismatch on block {self.sequence}")
        self.sequence += 1
        return actual_payload


def hydraharp_blocks(
    hh, duration_ms, buffer_records=1048576, poll_ms=10,
    stop_event=None, *, started=False,
):
    """Yield raw T2 records from an already initialized HydraHarp."""
    if not started and not hh.raw.startBlock(duration_ms, buffer_records, savePTU=False):
        raise RuntimeError("HydraHarp startBlock failed")

    pending = bytearray()
    stopped = False
    stop_deadline = None
    try:
        while True:
            if stop_event is not None and stop_event.is_set() and not stopped:
                hh.raw.stopMeasure()
                stopped = True
                stop_deadline = time.monotonic() + 10
            records = hh.raw.getBlock()
            if len(records):
                pending.extend(records.tobytes())
            while len(pending) >= PAYLOAD_SIZE:
                yield bytes(pending[:PAYLOAD_SIZE])
                del pending[:PAYLOAD_SIZE]
            if hh.raw.isFinished():
                # snAPI may still hold a final block when isFinished turns true.
                last_records = hh.raw.getBlock()
                if len(last_records):
                    pending.extend(last_records.tobytes())
                while len(pending) >= PAYLOAD_SIZE:
                    yield bytes(pending[:PAYLOAD_SIZE])
                    del pending[:PAYLOAD_SIZE]
                break
            if stopped and time.monotonic() >= stop_deadline:
                raise TimeoutError("HydraHarp did not finish after stopMeasure")
            time.sleep(poll_ms / 1000)
        if pending:
            yield bytes(pending)
    finally:
        if not stopped:
            hh.raw.stopMeasure()


def _hydraharp_blocks(args):
    from picoquant_snapi import MeasMode, RefSource, create_hydraharp_api

    hh = create_hydraharp_api()
    try:
        if not hh.getDevice():
            raise RuntimeError("HydraHarp not found or already in use")
        ref_source = (
            RefSource.External_10MHZ if args.ref_source == "external" else RefSource.Internal
        )
        if not hh.initDevice(MeasMode.T2, refSrc=ref_source):
            raise RuntimeError("HydraHarp T2 initialization failed")
        if args.ini and args.ini.is_file() and not hh.loadIniConfig(str(args.ini)):
            raise RuntimeError(f"Could not load {args.ini}")
        if not hh.device.setSyncCFD(300, 10):
            raise RuntimeError("Could not set HydraHarp sync CFD")
        for channel, threshold in ((0, 300), (1, 150)):
            if channel < int(hh.deviceConfig.get("NumChans", 0)):
                if not hh.device.setInputCFD(channel, threshold, 10):
                    raise RuntimeError(f"Could not set input CFD for channel {channel}")
                if not hh.device.setInputChannelOffset(channel, 0):
                    raise RuntimeError(f"Could not set input offset for channel {channel}")
        yield from hydraharp_blocks(hh, args.duration_ms, args.buffer_records, args.poll_ms)
    finally:
        hh.closeDevice()
        # snAPI.__del__ calls exitAPI() when this object is released. Calling
        # exitAPI() here as well makes some Linux snAPI builds free the native
        # API state twice during interpreter shutdown.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("pattern", "hydraharp"))
    parser.add_argument(
        "--thread-overhead-benchmark",
        type=int,
        metavar="N",
        help="benchmark N no-I/O reader/writer thread pairs, then exit",
    )
    parser.add_argument("--h2c", type=Path, default=Path("/dev/xdma0_h2c_0"))
    parser.add_argument("--c2h", type=Path, default=Path("/dev/xdma0_c2h_0"))
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--output", type=Path, help="write returned HH T2 records here")
    parser.add_argument("--duration-ms", type=int, default=10000)
    parser.add_argument("--poll-ms", type=int, default=10)
    parser.add_argument("--buffer-records", type=int, default=1048576)
    parser.add_argument("--ref-source", choices=("external", "internal"), default="external")
    parser.add_argument(
        "--ini", type=Path,
        default=Path(__file__).with_name("HH.ini"),
    )
    args = parser.parse_args()
    if args.thread_overhead_benchmark is not None:
        if args.thread_overhead_benchmark <= 0:
            parser.error("--thread-overhead-benchmark must be positive")
        if args.source is not None:
            parser.error("omit --source when running --thread-overhead-benchmark")
        _benchmark_thread_pair(args.thread_overhead_benchmark)
        return
    if args.source is None:
        parser.error("--source is required unless running --thread-overhead-benchmark")
    if args.source == "hydraharp" and args.output is None:
        parser.error("--source hydraharp requires --output")
    if (
        args.duration_ms <= 0
        or args.poll_ms <= 0
        or args.buffer_records <= 0
        or args.timeout <= 0
    ):
        parser.error("duration, poll interval, buffer size, and timeout must be positive")

    blocks = (
        [(bytes(range(256)) * ((PAYLOAD_SIZE + 255) // 256))[:PAYLOAD_SIZE]]
        if args.source == "pattern"
        else _hydraharp_blocks(args)
    )
    with OpticalLink(args.h2c, args.c2h, args.timeout) as link:
        if args.output is None:
            for block in blocks:
                started = time.perf_counter()
                link.exchange(block)
                elapsed = time.perf_counter() - started
                rate = len(block) / elapsed / 1_000_000
                print(
                    f"Block {link.sequence - 1}: {len(block)} bytes returned intact; "
                    f"exchange={elapsed * 1000:.3f} ms, payload_rate={rate:.2f} MB/s"
                )
        else:
            with args.output.open("wb") as output:
                for block in blocks:
                    started = time.perf_counter()
                    returned = link.exchange(block)
                    elapsed = time.perf_counter() - started
                    output.write(returned)
                    rate = len(block) / elapsed / 1_000_000
                    print(
                        f"Block {link.sequence - 1}: {len(block)} bytes returned intact; "
                        f"exchange={elapsed * 1000:.3f} ms, payload_rate={rate:.2f} MB/s"
                    )
    print(f"Finished: {link.sequence} blocks")


if __name__ == "__main__":
    main()
