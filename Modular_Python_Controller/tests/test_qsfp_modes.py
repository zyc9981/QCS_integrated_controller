"""Mode ownership, acquisition ordering, and failure preservation without devices."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optical_stream as stream
from qsfp_mode_control import guard_ticks


class Control:
    def __init__(self):
        self.events = []

    def idle(self, mode):
        self.events.append(("idle", mode))


class CaptureModes(unittest.TestCase):
    def run_capture(self, mode, fail=None):
        control = Control()
        payloads = [b"a" * stream.PAYLOAD_SIZE, b"b" * stream.PAYLOAD_SIZE, b"ccdd"]
        events = control.events

        def source(*args, **kwargs):
            for payload in payloads:
                events.append(("acquire", payload[:1]))
                yield payload
            events.append(("acquisition_end",))

        class Link:
            def __init__(self, *args, **kwargs):
                self.index = 0
            def __enter__(self):
                events.append(("link_open",))
                return self
            def exchange(self, payload):
                index, self.index = self.index, self.index + 1
                events.append(("send", payload[:1]))
                if index == 0 and fail == "mismatch":
                    raise stream.OpticalDataMismatch("injected", b"!" * len(payload))
                if index == 0 and fail == "transport":
                    raise TimeoutError("injected transport failure")
                return payload
            def __exit__(self, *args):
                events.append(("link_close",))

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(stream, "hydraharp_blocks", source), \
             patch.object(stream, "OpticalLink", Link), \
             patch.object(stream, "ModeOpticalLink", Link):
            output = Path(tmp) / "returned.bin"
            result = stream.capture_hh_qsfp(None, 100, output, threading.Event(),
                                            mode=mode, control=control)
            original = output.with_name(output.name + ".source.bin").read_bytes()
            returned = output.read_bytes()
            log = output.with_name(output.name + ".error.txt").read_text()
        self.assertEqual(original, b"".join(payloads))
        return events, result, returned, log

    def test_burst_defers_all_transfers_until_acquisition_finishes(self):
        events, result, returned, _ = self.run_capture("burst")
        self.assertLess(events.index(("acquisition_end",)), events.index(("link_open",)))
        self.assertEqual(result["blocks"], 3)
        self.assertEqual(len(returned), result["captured_bytes"])

    def test_continuous_sends_while_acquiring(self):
        events, result, _, _ = self.run_capture("continuous")
        self.assertLess(events.index(("send", b"a")), events.index(("acquisition_end",)))
        self.assertEqual(result["blocks"], 3)

    def test_mismatch_does_not_stop_capture_or_later_transfers(self):
        for mode in ("continuous", "burst"):
            with self.subTest(mode=mode):
                events, result, returned, log = self.run_capture(mode, "mismatch")
                self.assertEqual(result["blocks"], 2)
                self.assertEqual(result["mismatches"], 1)
                self.assertEqual(len(returned), result["captured_bytes"])
                self.assertIn("source offset 0", log)
                self.assertEqual(sum(e[0] == "send" for e in events), 3)

    def test_transport_failure_preserves_entire_capture(self):
        for mode in ("continuous", "burst"):
            with self.subTest(mode=mode):
                events, result, returned, log = self.run_capture(mode, "transport")
                self.assertEqual(result["captured_bytes"], 2 * stream.PAYLOAD_SIZE + 4)
                self.assertEqual(returned, b"")
                self.assertEqual(sum(e[0] == "send" for e in events), 1)
                self.assertIn("transport failure", log)

    def test_guard_validation(self):
        self.assertEqual(guard_ticks(15), 3_000_000)
        self.assertEqual(guard_ticks(0.01), 2000)
        for invalid in (float("nan"), float("inf"), -1, 1001):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                guard_ticks(invalid)

    def test_burst_control_failure_still_drains_hh(self):
        control = Control()
        payloads = [b"1234", b"5678"]
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(control, "idle", side_effect=RuntimeError("control unavailable")), \
             patch.object(stream, "hydraharp_blocks", return_value=(p for p in payloads)):
            output = Path(tmp) / "returned.bin"
            result = stream.capture_hh_qsfp(None, 100, output, threading.Event(),
                                            mode="burst", control=control)
            self.assertEqual(result["captured_bytes"], 8)
            self.assertEqual(result["blocks"], 0)
            self.assertEqual(Path(result["source_path"]).read_bytes(), b"12345678")
            self.assertIn("control unavailable", result["error"])


@unittest.skipUnless(os.environ.get("DISPLAY"), "Tk display unavailable")
class ModeUI(unittest.TestCase):
    def test_shared_controls_lock_and_persist_settings(self):
        import tkinter as tk
        from types import SimpleNamespace
        import qsfp_mode_ui as ui
        root = tk.Tk()
        root.withdraw()
        app = SimpleNamespace(root=root, ui={"text": "white", "surface": "black"},
                              tx_log_print=lambda message: None)

        class Backend:
            def idle(self, mode):
                pass
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ui, "SETTINGS", Path(tmp) / "settings.json"), \
             patch.object(ui, "QSFPModeControl", Backend):
            modes = ui.get_qsfp_modes(app)
            frames = [tk.Frame(root), tk.Frame(root)]
            for frame in frames:
                modes.add_panel(frame)
            self.assertEqual(modes.guard.get(), "15.0")
            self.assertEqual(modes.panels[0][2].cget("state"), "disabled")
            modes.mode.set("Burst")
            modes.enabled.set(True)
            modes.apply()
            deadline = time.monotonic() + 2
            while modes.applying and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            self.assertEqual(modes.capture_options()["mode"], "burst")
            self.assertEqual(modes.panels[1][2].cget("state"), "normal")
            app.qutag_timestamp_qsfp_active = True
            modes.refresh()
            for checkbox, mode, guard in modes.panels:
                self.assertEqual(checkbox.cget("state"), "disabled")
                self.assertEqual(str(mode.cget("state")), "disabled")
                self.assertEqual(guard.cget("state"), "disabled")
            self.assertEqual(json.loads(ui.SETTINGS.read_text()), {"mode": "Burst", "guard_ms": 15.0})
            modes.close()
        root.destroy()


if __name__ == "__main__":
    unittest.main()
