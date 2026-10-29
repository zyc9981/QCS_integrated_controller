#!/usr/bin/env python3
r"""Standalone TCP pattern link test (Python standard library only).

Copy to Linux (from PowerShell, in the repository root):
  scp .\Modular_Python_Controller\QCS_HH_TX_internet.py zyc@158.130.30.167:~/QCS_HH_TX_internet.py

On Linux, start one receiver per test:
  python3 ~/QCS_HH_TX_internet.py receive --bind 0.0.0.0 --port 50050
On Windows, from the repository root:
  & 'C:\ProgramData\anaconda3\python.exe' .\Modular_Python_Controller\QCS_HH_TX_internet.py send --host 158.130.30.167 --port 50050 --mode correctness --quiet
  & 'C:\ProgramData\anaconda3\python.exe' .\Modular_Python_Controller\QCS_HH_TX_internet.py send --host 158.130.30.167 --port 50050 --mode benchmark --quiet

The receiver handles one session and exits. Benchmark defaults to 256 MiB;
correctness defaults to 500 blocks of 1024 bytes (1 KiB). Run either role with
--help for limits, timeout, and test options. The receiver must permit the
requested total allocation. No files are written by this program.

Control messages are a 4-byte network-order length followed by UTF-8 JSON.
Each data frame has network-order uint64 sequence, uint32 length, uint32
CRC-32, then the payload. Payloads are deterministic per session and sequence.
The receiver sends RECEIVED after the final byte, then verifies and sends RESULT.
Benchmark sender timing runs from the first frame send through receiving the
complete RECEIVED message; receiver timing runs from before reading the first
frame through reading the last payload byte. Both use local monotonic clocks.
Payload throughput counts the dataset once, in decimal MB/s and Gb/s. These
are application payload rates, not raw Ethernet bandwidth or physical-link BER.
"""
import argparse
import hashlib
import json
import math
import socket
import struct
import sys
import time
import uuid
import zlib

VERSION = 1
HEADER = struct.Struct('!QII')
LENGTH = struct.Struct('!I')
MAX_CONTROL = 65536
DEFAULT_BLOCK = 1024
DEFAULT_TOTAL = 256 * 1024 * 1024
HARD_BLOCK = 16 * 1024 * 1024
HARD_RAM = 4 * 1024 * 1024 * 1024


class ProtocolError(Exception):
    pass


def recv_exact(sock, count):
    buf = bytearray(count)
    view = memoryview(buf)
    while view:
        n = sock.recv_into(view)
        if not n:
            raise ProtocolError('connection closed with %d bytes still expected' % len(view))
        view = view[n:]
    return buf


def recv_into_exact(sock, view):
    while view:
        n = sock.recv_into(view)
        if not n:
            raise ProtocolError('connection closed with %d payload bytes still expected' % len(view))
        view = view[n:]


def send_control(sock, obj):
    data = json.dumps(obj, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(data) > MAX_CONTROL:
        raise ProtocolError('control message too large')
    sock.sendall(LENGTH.pack(len(data)) + data)


def recv_control(sock):
    size = LENGTH.unpack(recv_exact(sock, LENGTH.size))[0]
    if size < 2 or size > MAX_CONTROL:
        raise ProtocolError('invalid control message length %d' % size)
    try:
        obj = json.loads(recv_exact(sock, size).decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise ProtocolError('invalid control JSON: %s' % exc) from exc
    if not isinstance(obj, dict):
        raise ProtocolError('control message must be an object')
    return obj


def pattern(session, seq, size):
    seed = hashlib.sha256(('%s:%d' % (session, seq)).encode('ascii')).digest()
    return (seed * ((size + len(seed) - 1) // len(seed)))[:size]


def integer(obj, key, minimum, maximum):
    value = obj.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolError('invalid %s (expected integer %d..%d)' % (key, minimum, maximum))
    return value


def validate_request(req, args):
    if req.get('type') != 'HELLO' or req.get('version') != VERSION:
        raise ProtocolError('unsupported handshake or protocol version')
    mode = req.get('mode')
    if mode not in ('correctness', 'benchmark'):
        raise ProtocolError('invalid mode')
    block = integer(req, 'block_size', 1, args.max_block_size)
    total = integer(req, 'total_bytes', 1, args.max_ram)
    count = integer(req, 'blocks', 1, args.max_ram)
    if count != (total + block - 1) // block:
        raise ProtocolError('block count does not match total and block size')
    if count > 1000000 or total + count * 160 > args.max_ram:
        raise ProtocolError('payload and estimated metadata exceed receiver RAM limit')
    return mode, block, total, count


def rate(total, elapsed):
    if elapsed <= 0:
        return 'unavailable'
    return '%.3f MB/s, %.3f Gb/s' % (total / elapsed / 1e6, total * 8 / elapsed / 1e9)


def receive(args):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(args.timeout)
        server.bind((args.bind, args.port))
        server.listen(1)
        print('Listening on %s:%d' % (args.bind, args.port), flush=True)
        conn, address = server.accept()
        with conn:
            conn.settimeout(args.timeout)
            print('Connected from %s:%d' % address, flush=True)
            try:
                req = recv_control(conn)
                mode, block, total, count = validate_request(req, args)
                session = uuid.uuid4().hex
                # Allocate all payload and fixed-size metadata before READY/timing.
                data = bytearray(total)
                headers = bytearray(count * HEADER.size)
                send_control(conn, {'type': 'READY', 'version': VERSION, 'session': session,
                                    'mode': mode, 'block_size': block, 'total_bytes': total,
                                    'blocks': count})
                print('Connection ready: session %s, %s, %d blocks, %d payload bytes' %
                      (session, mode, count, total), flush=True)
                start_msg = recv_control(conn)
                if start_msg.get('type') != 'START' or start_msg.get('session') != session:
                    raise ProtocolError('invalid START message')
                offset = 0
                started = time.perf_counter()
                for i in range(count):
                    raw = recv_exact(conn, HEADER.size)
                    headers[i * HEADER.size:(i + 1) * HEADER.size] = raw
                    seq, size, checksum = HEADER.unpack(raw)
                    expected_size = min(block, total - offset)
                    if size != expected_size:
                        raise ProtocolError('frame %d sequence %d: length %d, expected %d' %
                                            (i, seq, size, expected_size))
                    recv_into_exact(conn, memoryview(data)[offset:offset + size])
                    offset += size
                elapsed = time.perf_counter() - started
                send_control(conn, {'type': 'RECEIVED', 'session': session, 'bytes': offset})
                intact = mismatches = 0
                seen = set()
                for i in range(count):
                    seq, size, checksum = HEADER.unpack_from(headers, i * HEADER.size)
                    start = i * block
                    payload = memoryview(data)[start:start + size]
                    actual_crc = zlib.crc32(payload) & 0xffffffff
                    problems = []
                    if seq >= count:
                        problems.append('sequence out of range')
                    else:
                        if seq in seen:
                            problems.append('duplicate sequence')
                        seen.add(seq)
                    if seq != i:
                        problems.append('expected sequence %d' % i)
                    if actual_crc != checksum:
                        problems.append('CRC expected %08x got %08x' % (checksum, actual_crc))
                    if seq >= count or payload != pattern(session, seq, size):
                        problems.append('pattern differs')
                    if problems:
                        mismatches += 1
                        print('ERROR frame %d sequence %d: %s' % (i, seq, '; '.join(problems)), flush=True)
                    else:
                        intact += 1
                        if not args.quiet and mode == 'correctness':
                            print('Block %d intact (%d bytes)' % (seq, size), flush=True)
                missing = count - len(seen)
                ok = mismatches == 0 and missing == 0
                result = {'type': 'RESULT', 'session': session, 'ok': ok, 'blocks_received': count,
                          'intact_blocks': intact, 'mismatches': mismatches, 'missing_blocks': missing,
                          'payload_bytes': offset, 'receiver_seconds': elapsed}
                send_control(conn, result)
                print('Result: %s; blocks received=%d, intact=%d, mismatches=%d, missing=%d, payload bytes=%d' %
                      ('PASS' if ok else 'FAIL', count, intact, mismatches, missing, offset), flush=True)
                print('Receiver transfer: %.6f s, %s (first frame read through final payload byte)' %
                      (elapsed, rate(offset, elapsed)), flush=True)
                return 0 if ok else 1
            except (ProtocolError, MemoryError) as exc:
                try:
                    send_control(conn, {'type': 'ERROR', 'message': str(exc)})
                except OSError:
                    pass
                raise


def send(args):
    total = args.blocks * args.block_size if args.mode == 'correctness' else args.bytes
    if total > args.max_ram:
        raise ProtocolError('dataset exceeds sender --max-ram')
    count = (total + args.block_size - 1) // args.block_size
    if count > 1000000 or total + count * 160 > args.max_ram:
        raise ProtocolError('payload and estimated metadata exceed sender RAM limit')
    with socket.create_connection((args.host, args.port), args.timeout) as conn:
        conn.settimeout(args.timeout)
        send_control(conn, {'type': 'HELLO', 'version': VERSION, 'mode': args.mode,
                            'block_size': args.block_size, 'total_bytes': total, 'blocks': count})
        ready = recv_control(conn)
        if ready.get('type') == 'ERROR':
            raise ProtocolError('receiver rejected test: ' + str(ready.get('message')))
        session = ready.get('session')
        if (ready.get('type') != 'READY' or ready.get('version') != VERSION or
            not isinstance(session, str) or len(session) != 32 or
            any(c not in '0123456789abcdef' for c in session) or
            any(ready.get(k) != v for k, v in [('mode', args.mode), ('block_size', args.block_size),
                                                 ('total_bytes', total), ('blocks', count)])):
            raise ProtocolError('invalid READY response')
        print('Connection ready: session %s, %s, %d blocks, %d payload bytes' %
              (session, args.mode, count, total), flush=True)
        # Prepare every frame and checksum before starting the transfer clock.
        frames = []
        for i in range(count):
            payload = pattern(session, i, min(args.block_size, total - i * args.block_size))
            frames.append((HEADER.pack(i, len(payload), zlib.crc32(payload) & 0xffffffff), payload))
        send_control(conn, {'type': 'START', 'session': session})
        started = time.perf_counter()
        for header, payload in frames:
            conn.sendall(header)
            conn.sendall(payload)
        ack = recv_control(conn)
        elapsed = time.perf_counter() - started
        if ack.get('type') != 'RECEIVED' or ack.get('session') != session or ack.get('bytes') != total:
            raise ProtocolError('invalid or missing RECEIVED acknowledgement: %s' % ack)
        result = recv_control(conn)
        if (result.get('type') != 'RESULT' or result.get('session') != session or
            type(result.get('ok')) is not bool):
            raise ProtocolError('invalid verification result: %s' % result)
        print('Sender transfer: %.6f s, %s (first frame send through complete RECEIVED acknowledgement)' %
              (elapsed, rate(total, elapsed)), flush=True)
        print('Receiver verification: %s; blocks received=%s, intact=%s, mismatches=%s, missing=%s, payload bytes=%s' %
              ('PASS' if result['ok'] else 'FAIL', result.get('blocks_received'), result.get('intact_blocks'),
               result.get('mismatches'), result.get('missing_blocks'), result.get('payload_bytes')), flush=True)
        print('Receiver transfer: %.6f s, %s (first frame read through final payload byte)' %
              (result['receiver_seconds'], rate(total, result['receiver_seconds'])), flush=True)
        return 0 if result['ok'] else 1


def positive(text):
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError('must be positive')
    return value


def port_number(text):
    value = positive(text)
    if value > 65535:
        raise argparse.ArgumentTypeError('port must be 1..65535')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='role', required=True)
    rx = sub.add_parser('receive', help='listen for one test')
    rx.add_argument('--bind', default='0.0.0.0')
    tx = sub.add_parser('send', help='send one test')
    tx.add_argument('--host', default='158.130.30.167')
    tx.add_argument('--mode', choices=('correctness', 'benchmark'), default='correctness')
    tx.add_argument('--blocks', type=positive, default=500, help='correctness block count')
    tx.add_argument('--block-size', type=positive, default=DEFAULT_BLOCK, help='payload bytes per block')
    tx.add_argument('--bytes', type=positive, default=DEFAULT_TOTAL, help='benchmark total payload bytes')
    for p in (rx, tx):
        p.add_argument('--port', type=port_number, default=50050)
        p.add_argument('--timeout', type=float, default=120.0, help='socket operation timeout in seconds')
        p.add_argument('--max-ram', type=positive, default=512 * 1024 * 1024, help='maximum payload bytes')
        p.add_argument('--quiet', action='store_true', help='suppress individual block messages')
    rx.add_argument('--max-block-size', type=positive, default=1024 * 1024)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be a finite positive number')
    if args.max_ram > HARD_RAM:
        parser.error('--max-ram exceeds hard limit of %d' % HARD_RAM)
    if args.role == 'receive' and args.max_block_size > HARD_BLOCK:
        parser.error('--max-block-size exceeds hard limit of %d' % HARD_BLOCK)
    if args.role == 'send' and args.block_size > HARD_BLOCK:
        parser.error('--block-size exceeds hard limit of %d' % HARD_BLOCK)
    try:
        return receive(args) if args.role == 'receive' else send(args)
    except KeyboardInterrupt:
        print('INCOMPLETE: interrupted by user', file=sys.stderr, flush=True)
    except (OSError, ProtocolError, MemoryError, OverflowError) as exc:
        print('INCOMPLETE: %s' % exc, file=sys.stderr, flush=True)
    return 1


if __name__ == '__main__':
    sys.exit(main())