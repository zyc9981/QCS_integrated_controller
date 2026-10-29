"""Real loopback TCP checks; no acquisition hardware or campus connections."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
import zlib

spec = importlib.util.spec_from_file_location(
    "hh_stream", Path(__file__).resolve().parents[1] / "QCS_HH_stream_internet.py")
stream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stream)


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "capture.bin"
        self.errors = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(3)
        self.addCleanup(self.listener.close)

    def start_receiver(self, **kwargs):
        def run():
            try:
                conn, _ = self.listener.accept()
                with conn:
                    stream.receive_connection(conn, self.output, timeout=2, quiet=True, **kwargs)
            except BaseException as exc:
                self.errors.append(exc)
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        self.conn = socket.create_connection(self.listener.getsockname(), timeout=2)
        self.addCleanup(self.conn.close)

    def finish_receiver(self):
        self.worker.join(4)
        self.assertFalse(self.worker.is_alive(), "receiver did not terminate")

    def begin(self):
        stream.send_json(self.conn, {"type": "HELLO", "version": 2,
            "format": stream.FORMAT, "record_bytes": 4, "block_size": 1024})
        ready = stream.read_json(self.conn)
        stream.send_json(self.conn, {"type": "START", "session": ready["session"]})
        return ready["session"]

    def assert_incomplete(self, saved_bytes):
        self.assertFalse(self.output.exists())
        self.assertEqual(self.output.with_suffix(".bin.part").read_bytes(), saved_bytes)
        info = json.loads(self.output.with_suffix(".bin.json").read_text())
        self.assertEqual(info["status"], "incomplete")
        self.assertEqual(info["bytes_saved"], len(saved_bytes))
        self.assertTrue(self.errors)

    def test_stream_unknown_length_mixed_chunks_final_short_and_hash(self):
        self.start_receiver()
        chunks = [b"", bytes(range(256)) * 8, struct.pack("<I", 123), b"x" * 8192]
        expected = b"".join(chunks)
        result = stream.send_chunks(self.conn, iter(chunks), block_size=1024, timeout=2)
        self.finish_receiver()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.output.read_bytes(), expected)
        self.assertFalse(self.output.with_suffix(".bin.part").exists())
        self.assertEqual(result["sha256"], hashlib.sha256(expected).hexdigest())
        info = json.loads(self.output.with_suffix(".bin.json").read_text())
        self.assertEqual(info["status"], "complete")
        self.assertEqual(info["records_saved"], len(expected) // 4)

    def test_fragmented_frame_and_disconnect_preserve_valid_prefix(self):
        self.start_receiver()
        self.begin()
        good = b"a" * 1024
        frame = stream.FRAME.pack(0, len(good), zlib.crc32(good)) + good
        for offset in range(0, len(frame), 7):
            self.conn.sendall(frame[offset:offset + 7])
        self.conn.sendall(stream.FRAME.pack(1, 1024, 0) + b"abc")
        self.conn.shutdown(socket.SHUT_WR)
        self.finish_receiver()
        self.assert_incomplete(good)

    def test_bad_crc_not_published(self):
        self.start_receiver()
        self.begin()
        self.conn.sendall(stream.FRAME.pack(0, 4, 0) + b"abcd")
        self.assertEqual(stream.read_json(self.conn)["type"], "ERROR")
        self.finish_receiver()
        self.assert_incomplete(b"")

    def test_duplicate_sequence_and_limit(self):
        for second_seq, cap in ((0, 4096), (1, 4)):
            with self.subTest(second_seq=second_seq, cap=cap):
                # Separate destination; create a new listening worker each time.
                self.output = Path(self.temp.name) / ("capture_%d.bin" % cap)
                self.start_receiver(max_bytes=cap)
                self.begin()
                payload = b"abcd"
                header = stream.FRAME.pack(0, 4, zlib.crc32(payload))
                self.conn.sendall(header + payload)
                self.conn.sendall(stream.FRAME.pack(second_seq, 4, zlib.crc32(payload)))
                self.assertEqual(stream.read_json(self.conn)["type"], "ERROR")
                self.finish_receiver()
                self.assert_incomplete(payload)
                self.conn.close()

    def test_bad_final_digest_not_published(self):
        self.start_receiver()
        session = self.begin()
        payload = b"abcd"
        self.conn.sendall(stream.FRAME.pack(0, 4, zlib.crc32(payload)) + payload)
        self.conn.sendall(stream.FRAME.pack(1, 0, 0))
        stream.send_json(self.conn, {"type": "END", "session": session, "bytes": 4,
                         "blocks": 1, "records": 1, "sha256": "0" * 64})
        self.assertEqual(stream.read_json(self.conn)["type"], "ERROR")
        self.finish_receiver()
        self.assert_incomplete(payload)

    def test_existing_output_not_overwritten(self):
        self.output.write_bytes(b"keep")
        self.start_receiver()
        stream.send_json(self.conn, {"type": "HELLO", "version": 2,
            "format": stream.FORMAT, "record_bytes": 4, "block_size": 1024})
        self.assertEqual(stream.read_json(self.conn)["type"], "ERROR")
        self.finish_receiver()
        self.assertEqual(self.output.read_bytes(), b"keep")
        self.assertFalse(self.output.with_suffix(".bin.json").exists())

    def test_timeout_not_normal_end(self):
        self.start_receiver()
        self.begin()
        self.finish_receiver()
        self.assert_incomplete(b"")


if __name__ == "__main__":
    unittest.main()
