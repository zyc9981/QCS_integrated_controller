#!/usr/bin/env python3
"""Disk-backed raw HydraHarp T2 transport. Standard library; no hardware access.

Use receive on Linux and send-file on Windows. This is stream protocol v2,
separate from the v1 RAM/pattern benchmark QCS_HH_TX_internet.py.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import struct
import sys
import time
import uuid
import zlib

VERSION = 2
FORMAT = "hydraharp400_t2_raw_le_u32"
FRAME = struct.Struct("!QII")
LENGTH = struct.Struct("!I")
MAX_CONTROL = 65536
MAX_BLOCK = 1024 * 1024


class StreamError(Exception):
    pass


def exact(sock, count):
    buf = bytearray(count)
    view = memoryview(buf)
    while view:
        n = sock.recv_into(view)
        if not n:
            raise StreamError("connection closed with %d bytes still expected" % len(view))
        view = view[n:]
    return buf


def send_json(sock, obj):
    data = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > MAX_CONTROL:
        raise StreamError("control message exceeds limit")
    sock.sendall(LENGTH.pack(len(data)) + data)


def read_json(sock):
    count = LENGTH.unpack(exact(sock, LENGTH.size))[0]
    if not 2 <= count <= MAX_CONTROL:
        raise StreamError("invalid control length")
    try:
        obj = json.loads(exact(sock, count).decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise StreamError("invalid control JSON") from exc
    if not isinstance(obj, dict):
        raise StreamError("control must be a JSON object")
    return obj


def integer(obj, key, low, high):
    value = obj.get(key)
    if type(value) is not int or not low <= value <= high:
        raise StreamError("invalid %s (expected %d..%d)" % (key, low, high))
    return value


def check_message(obj, kind, session):
    if obj.get("type") == "ERROR":
        raise StreamError("receiver: %s" % obj.get("message", "unknown error"))
    if obj.get("type") != kind or obj.get("session") != session:
        raise StreamError("invalid %s response" % kind)


def write_manifest(path, info):
    # The manifest was exclusively reserved before accepting a session.
    with path.open("w", encoding="utf-8") as file:
        json.dump(info, file, indent=2, allow_nan=False)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())


def receive_connection(conn, output, *, timeout=30.0, max_bytes=16 * 1024**3,
                       max_block=MAX_BLOCK, quiet=False):
    """Receive exactly one stream. Return only after disk save and validation.

    Each nonzero-length frame carries an integral number of raw 4-byte records.
    A zero-length frame ends the data, followed by an END JSON digest/counts.
    EOF or a timeout is never interpreted as normal completion.
    """
    output = Path(output)
    part = output.with_name(output.name + ".part")
    manifest = output.with_name(output.name + ".json")
    conn.settimeout(timeout)
    reserved = False
    info = {"status": "incomplete", "version": VERSION, "format": FORMAT,
            "output": str(output), "bytes_saved": 0, "blocks_saved": 0,
            "records_saved": 0, "started_unix": time.time()}
    digest = hashlib.sha256()
    started = None
    try:
        req = read_json(conn)
        if req.get("type") != "HELLO" or req.get("version") != VERSION:
            raise StreamError("requires HH streaming protocol v2 (not the v1 pattern tester)")
        if req.get("format") != FORMAT or req.get("record_bytes") != 4:
            raise StreamError("requires raw little-endian 4-byte HydraHarp T2 records")
        block = integer(req, "block_size", 4, max_block)
        if block % 4:
            raise StreamError("block size must be a multiple of 4")
        if not isinstance(req.get("metadata", {}), dict):
            raise StreamError("metadata must be an object")
        if output.exists():
            raise StreamError("output already exists: %s" % output)
        # No filename from the peer is used for the destination path.
        with manifest.open("x", encoding="utf-8"):
            pass
        reserved = True
        info.update(session=uuid.uuid4().hex, metadata=req.get("metadata", {}),
                    block_size=block, peer=str(conn.getpeername()))
        with part.open("xb") as saved:
            write_manifest(manifest, info)
            send_json(conn, {"type": "READY", "version": VERSION,
                            "session": info["session"], "block_size": block})
            check_message(read_json(conn), "START", info["session"])
            started = time.perf_counter()
            while True:
                seq, size, crc = FRAME.unpack(exact(conn, FRAME.size))
                if seq != info["blocks_saved"]:
                    raise StreamError("sequence %d, expected %d" % (seq, info["blocks_saved"]))
                if size == 0:
                    if crc != 0:
                        raise StreamError("invalid end frame checksum")
                    break
                if size > block or size % 4:
                    raise StreamError("invalid record-aligned frame length %d" % size)
                if info["bytes_saved"] + size > max_bytes:
                    raise StreamError("receiver --max-bytes exceeded")
                data = exact(conn, size)
                actual = zlib.crc32(data) & 0xffffffff
                if actual != crc:
                    raise StreamError("CRC mismatch on block %d: expected %08x, got %08x" %
                                      (seq, crc, actual))
                saved.write(data)
                digest.update(data)
                info["bytes_saved"] += size
                info["blocks_saved"] += 1
                info["records_saved"] += size // 4
                if not quiet and info["blocks_saved"] % 1024 == 0:
                    print("Saved %d bytes (%d records)" %
                          (info["bytes_saved"], info["records_saved"]), flush=True)
            end = read_json(conn)
            check_message(end, "END", info["session"])
            for key, value in (("bytes", info["bytes_saved"]),
                               ("blocks", info["blocks_saved"]),
                               ("records", info["records_saved"])):
                if type(end.get(key)) is not int or end[key] != value:
                    raise StreamError("END %s does not match received stream" % key)
            if end.get("sha256") != digest.hexdigest():
                raise StreamError("END SHA-256 does not match received bytes")
            saved.flush()
            os.fsync(saved.fileno())
        # Atomic publication with no replacement of an existing final file.
        os.link(part, output)
        part.unlink()
        elapsed = time.perf_counter() - started
        info.update(status="complete", sha256=digest.hexdigest(),
                    finished_unix=time.time(), receiver_seconds=elapsed,
                    payload_MB_s=info["bytes_saved"] / elapsed / 1e6)
        write_manifest(manifest, info)
        # SAVED means complete application verification and disk flush occurred.
        send_json(conn, {"type": "SAVED", "session": info["session"],
                        "bytes": info["bytes_saved"], "blocks": info["blocks_saved"],
                        "records": info["records_saved"], "sha256": info["sha256"],
                        "receiver_seconds": elapsed})
        return info
    except BaseException as exc:
        if reserved:
            # A failed final acknowledgement does not invalidate a published file.
            if info["status"] != "complete":
                info.update(error="%s: %s" % (type(exc).__name__, exc),
                            sha256_validated_prefix=digest.hexdigest(), finished_unix=time.time())
            else:
                info["acknowledgement_error"] = str(exc)
            write_manifest(manifest, info)
        try:
            send_json(conn, {"type": "ERROR", "message": str(exc)})
        except OSError:
            pass
        raise


def send_chunks(conn, chunks, *, block_size=1024, metadata=None, timeout=30.0):
    """Source-neutral sender for already-owned immutable raw-record chunks.

    This function may block on the network. A future live capture adapter must
    drain HH to a local disk spool independently, then feed this sender.
    """
    if type(block_size) is not int or not 4 <= block_size <= MAX_BLOCK or block_size % 4:
        raise StreamError("block size must be a multiple of 4 within 4..1048576")
    conn.settimeout(timeout)
    send_json(conn, {"type": "HELLO", "version": VERSION, "format": FORMAT,
                    "record_bytes": 4, "block_size": block_size, "metadata": metadata or {}})
    ready = read_json(conn)
    session = ready.get("session")
    if (ready.get("type") != "READY" or ready.get("version") != VERSION or
            not isinstance(session, str) or len(session) != 32 or
            any(c not in "0123456789abcdef" for c in session) or
            ready.get("block_size") != block_size):
        raise StreamError("receiver did not accept stream: %s" % ready)
    print("Ready: session %s" % session, flush=True)
    send_json(conn, {"type": "START", "session": session})
    digest = hashlib.sha256()
    total = count = 0
    started = time.perf_counter()
    for chunk in chunks:
        data = memoryview(chunk).cast("B")
        if len(data) % 4:
            raise StreamError("source chunk has a partial 4-byte record")
        for offset in range(0, len(data), block_size):
            payload = data[offset:offset + block_size]
            digest.update(payload)
            conn.sendall(FRAME.pack(count, len(payload), zlib.crc32(payload) & 0xffffffff))
            conn.sendall(payload)
            count += 1
            total += len(payload)
    conn.sendall(FRAME.pack(count, 0, 0))
    send_json(conn, {"type": "END", "session": session, "bytes": total,
                    "blocks": count, "records": total // 4, "sha256": digest.hexdigest()})
    result = read_json(conn)
    check_message(result, "SAVED", session)
    for key, expected in (("bytes", total), ("blocks", count),
                          ("records", total // 4), ("sha256", digest.hexdigest())):
        if result.get(key) != expected:
            raise StreamError("invalid SAVED %s" % key)
    result["sender_seconds"] = time.perf_counter() - started
    result["payload_MB_s"] = total / result["sender_seconds"] / 1e6
    return result


def positive(text):
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="role", required=True)
    rx = sub.add_parser("receive", help="save one raw-record session to disk")
    rx.add_argument("--bind", default="0.0.0.0")
    rx.add_argument("--output", type=Path, required=True)
    rx.add_argument("--max-bytes", type=positive, default=16 * 1024**3)
    rx.add_argument("--max-block-size", type=positive, default=MAX_BLOCK)
    rx.add_argument("--quiet", action="store_true")
    tx = sub.add_parser("send-file", help="replay a completed raw T2 .bin; no acquisition")
    tx.add_argument("--host", default="158.130.30.167")
    tx.add_argument("--input", type=Path, required=True)
    tx.add_argument("--block-size", type=positive, default=1024)
    tx.add_argument("--metadata", type=Path, help="optional JSON device/capture metadata")
    for command in (rx, tx):
        command.add_argument("--port", type=positive, default=50050)
        command.add_argument("--timeout", type=float, default=30.0,
                             help="inactivity timeout per socket operation, not total session duration")
    args = parser.parse_args()
    if args.port > 65535 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("invalid port or timeout")
    if args.role == "receive" and not 4 <= args.max_block_size <= MAX_BLOCK:
        parser.error("invalid --max-block-size")
    try:
        if args.role == "receive":
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.settimeout(args.timeout)
                server.bind((args.bind, args.port))
                server.listen(1)
                print("Listening on %s:%d; destination %s" %
                      (args.bind, args.port, args.output), flush=True)
                conn, _ = server.accept()
                with conn:
                    result = receive_connection(conn, args.output, timeout=args.timeout,
                                                max_bytes=args.max_bytes,
                                                max_block=args.max_block_size, quiet=args.quiet)
        else:
            if args.input.suffix.lower() in (".ptu", ".ttbin", ".h5"):
                raise StreamError("input must contain raw T2 records, not PTU/TTBIN/H5 containers")
            metadata = {"source": "completed_raw_file_replay", "record_format": FORMAT,
                        "time_resolution_ps": None}
            if args.metadata:
                if args.metadata.stat().st_size > MAX_CONTROL // 2:
                    raise StreamError("metadata file too large")
                device_metadata = json.loads(args.metadata.read_text(encoding="utf-8-sig"))
                if not isinstance(device_metadata, dict):
                    raise StreamError("metadata file must contain a JSON object")
                metadata["capture_metadata"] = device_metadata
            with args.input.open("rb") as source:
                before = os.fstat(source.fileno())
                if before.st_size % 4:
                    raise StreamError("input file ends in a partial 4-byte record")
                def chunks():
                    remaining = before.st_size
                    while remaining:
                        data = source.read(min(64 * 1024, remaining))
                        if not data:
                            raise StreamError("source file shortened during transfer")
                        remaining -= len(data)
                        yield data
                    after = os.fstat(source.fileno())
                    if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
                        raise StreamError("source file changed; use a completed recording")
                with socket.create_connection((args.host, args.port), args.timeout) as conn:
                    result = send_chunks(conn, chunks(), block_size=args.block_size,
                                         metadata=metadata, timeout=args.timeout)
        print(json.dumps(result, indent=2), flush=True)
        return 0
    except (OSError, ValueError, StreamError, KeyboardInterrupt) as exc:
        print("INCOMPLETE: %s: %s" % (type(exc).__name__, exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
