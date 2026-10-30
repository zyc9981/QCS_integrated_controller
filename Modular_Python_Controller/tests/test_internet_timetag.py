"""Real TCP coordinator/service checks without HydraHarp or Tk."""
import hashlib
import json
from pathlib import Path
import queue
import socket
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import QCS_HH_TRX as trx
from internet_timetag import InternetCoordinator


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class InternetTests(unittest.TestCase):
    def wait_for(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail('timed out; coordinator: %s' % self.coordinator.snapshot())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        control, data = free_port(), free_port()
        while data == control:
            data = free_port()
        self.coordinator = InternetCoordinator('127.0.0.1', control, data, timeout=1)
        self.addCleanup(self.coordinator.close)
        args = SimpleNamespace(host='127.0.0.1', control_port=control, data_port=data,
                               timeout=1, block_size=1024, shutdown_timeout=2,
                               spool_dir=self.temp.name)
        self.service = trx.Service(args, trx.Simulated())
        self.console = queue.Queue()
        self.console_patch = patch.object(trx, 'start_console', return_value=self.console)
        self.console_patch.start()
        self.addCleanup(self.console_patch.stop)
        self.worker = threading.Thread(target=self.service.run, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_service)
        self.wait_for(lambda: self.coordinator.snapshot()['ready'])

    def stop_service(self):
        self.service.stop.set()
        self.worker.join(4)
        self.coordinator.close()
        self.coordinator.thread.join(2)
        self.assertFalse(self.worker.is_alive(), 'service did not stop')
        self.assertFalse(self.coordinator.thread.is_alive(), 'coordinator did not stop')

    def check_capture(self, output):
        self.wait_for(lambda: not self.coordinator.snapshot()['active'])
        result = self.coordinator.snapshot()['result']
        self.assertEqual(result['status'], 'complete', result)
        saved = output.read_bytes()
        self.assertGreater(len(saved), 0)
        self.assertEqual(result['sha256'], hashlib.sha256(saved).hexdigest())
        self.assertEqual(self.coordinator.snapshot()['bytes'], len(saved))
        self.assertEqual(result['block_size'], 1024)
        self.assertFalse(Path(str(output)+'.part').exists())
        self.wait_for(lambda: self.coordinator.snapshot()['ready'])
        manifests = [json.loads(p.read_text()) for p in Path(self.temp.name).glob('*.bin.json')
                     if not p.name.startswith('capture')]
        match = next(m for m in manifests if m['id'] == result['request_id'])
        self.assertEqual(match['local_sha256'], result['sha256'])
        self.assertEqual(match['linux_saved'], 'verified')
        return match

    def test_timed_capture_then_operator_stop_without_reconnecting(self):
        first = Path(self.temp.name) / 'capture1.bin'
        self.coordinator.record(first, duration=0.15)
        self.check_capture(first)
        second = Path(self.temp.name) / 'capture2.bin'
        self.coordinator.record(second, duration=60)
        self.wait_for(lambda: self.coordinator.snapshot()['bytes'] >= 1024)
        self.coordinator.stop_recording()
        match = self.check_capture(second)
        self.assertEqual(match['capture'], 'stopped_by_operator')
        third = Path(self.temp.name) / 'capture3.bin'
        self.coordinator.record(third, duration=0.1)
        self.check_capture(third)

    def test_existing_file_and_invalid_duration_rejected(self):
        output = Path(self.temp.name) / 'capture.bin'
        output.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            self.coordinator.record(output)
        self.assertEqual(output.read_bytes(), b'keep')
        for duration in (float('nan'), 0, 3601):
            with self.assertRaises(ValueError):
                self.coordinator.record(Path(self.temp.name) / 'new.bin', duration)
        self.assertFalse(self.coordinator.snapshot()['active'])

    def test_disconnect_is_incomplete_and_keeps_partial(self):
        output = Path(self.temp.name) / 'capture_failure.bin'
        self.coordinator.record(output, duration=60)
        self.wait_for(lambda: self.coordinator.snapshot()['bytes'] >= 1024)
        self.coordinator.close()
        self.wait_for(lambda: not self.coordinator.snapshot()['active'])
        self.assertEqual(self.coordinator.snapshot()['result']['status'], 'incomplete')
        self.assertFalse(output.exists())
        self.assertTrue(Path(str(output)+'.part').exists())
        self.service.capture_stop.set()

    def test_receive_limit_failure_keeps_partial(self):
        output = Path(self.temp.name) / 'capture_limit.bin'
        self.coordinator.record(output, duration=0.1, max_bytes=1024)
        self.wait_for(lambda: not self.coordinator.snapshot()['active'])
        result = self.coordinator.snapshot()['result']
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('maximum file size', result['error'])
        self.assertFalse(output.exists())
        self.assertEqual(Path(str(output)+'.part').stat().st_size, 1024)


class OfflineInternetTests(unittest.TestCase):
    """Exercise the real decoder against scripted bytes, without opening sockets."""
    def coordinator(self):
        with patch('internet_timetag.threading.Thread.start'):
            coordinator = InternetCoordinator(timeout=1)
        coordinator.ready = True
        return coordinator

    def transfer(self, corrupt=False, maximum=4096):
        import io
        import struct
        import zlib
        from unittest.mock import MagicMock
        sid, stream_id = 'a' * 32, 'b' * 32
        payload = b'abcd' * 256
        def message(obj):
            data = json.dumps(obj).encode()
            return struct.pack('!I', len(data)) + data
        wire = message(dict(type='HELLO', version=2, format=trx.FORMAT,
                            record_bytes=4, block_size=1024, metadata=dict(request_id=sid)))
        wire += message(dict(type='START', session=stream_id))
        wire += trx.FRAME.pack(0, len(payload), 0 if corrupt else zlib.crc32(payload)) + payload
        wire += trx.FRAME.pack(1, 0, 0)
        wire += message(dict(type='END', session=stream_id, bytes=len(payload),
                             blocks=1, records=len(payload)//4,
                             sha256=hashlib.sha256(payload).hexdigest()))
        source = io.BytesIO(wire)
        conn = MagicMock()
        # Fragment reads to exercise exact() rather than feeding whole messages.
        conn.recv_into.side_effect = lambda view: source.readinto(view[:min(len(view), 7)])
        listener = MagicMock()
        listener.accept.return_value = (conn, ('127.0.0.1', 12345))
        coordinator = self.coordinator()
        coordinator.active, coordinator.session = True, sid
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'capture.bin'
            manifest = Path(str(output)+'.json')
            manifest.touch()
            file = Path(str(output)+'.part').open('xb')
            with patch.object(trx.uuid, 'uuid4', return_value=SimpleNamespace(hex=stream_id)):
                coordinator._receive(listener, output, file, manifest, sid, 1, maximum)
            state = coordinator.snapshot()
            info = json.loads(manifest.read_text())
            if corrupt or maximum < len(payload):
                self.assertEqual(info['status'], 'incomplete')
                self.assertFalse(output.exists())
                self.assertTrue(Path(str(output)+'.part').exists())
                self.assertEqual(coordinator.commands.get_nowait(), ('stop', sid))
            else:
                self.assertEqual(output.read_bytes(), payload)
                self.assertEqual(info['status'], 'complete')
                self.assertEqual(info['sha256'], hashlib.sha256(payload).hexdigest())
                self.assertEqual(state['bytes'], len(payload))
                self.assertEqual(state['blocks'], 1)
                self.assertGreaterEqual(state['finished'], state['started'])
                self.assertIn('SHA-256 verified', state['status'])
            self.assertFalse(state['active'])
            self.assertIsNotNone(state['result'])

    def test_valid_transfer_and_metrics(self):
        self.transfer()

    def test_bad_crc_stays_incomplete(self):
        self.transfer(corrupt=True)

    def test_size_limit_stays_incomplete(self):
        self.transfer(maximum=4)

    def test_stop_is_session_specific_and_does_not_exit_service(self):
        service = trx.Service(SimpleNamespace(), trx.Simulated())
        service.active = 'first'
        self.assertFalse(service.stop_capture('old'))
        self.assertFalse(service.capture_stop.is_set())
        self.assertTrue(service.stop_capture('first'))
        self.assertTrue(service.capture_stop.is_set())
        self.assertFalse(service.stop.is_set())

    def test_new_request_clears_previous_stop(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as directory:
            service = trx.Service(SimpleNamespace(spool_dir=directory), trx.Simulated())
            service.capture_stop.set()
            service.notify = MagicMock()
            # Do not acquire hardware or start a worker in this offline check.
            with patch.object(trx.threading, 'Thread') as worker:
                service.request(dict(id='a'*32, duration=1))
                self.assertFalse(service.capture_stop.is_set())
                self.assertEqual(service.active, 'a'*32)
                file = worker.call_args.kwargs['args'][-1]
                file.close()

    def test_requests_require_ready_and_respect_existing_files(self):
        coordinator = self.coordinator()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'capture.bin'
            coordinator.ready = False
            with self.assertRaises(RuntimeError):
                coordinator.record(output)
            coordinator.ready = True
            output.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                coordinator.record(output)
            self.assertEqual(output.read_bytes(), b'keep')
            output.unlink()
            coordinator.record(output, 10)
            self.assertTrue(coordinator.snapshot()['active'])
            coordinator.stop_recording()
            kind, values = coordinator.commands.get_nowait()
            self.assertEqual(kind, 'record')
            self.assertEqual(values[1], output)
            self.assertEqual(coordinator.commands.get_nowait(), ('stop', values[0]))


class OfflinePanelTests(unittest.TestCase):
    """Run the actual panel and recording functions with Tk/hardware stand-ins."""
    def setUp(self):
        import ast
        import collections
        from unittest.mock import MagicMock
        source = Path(__file__).resolve().parents[1] / 'qutag_timestamp_helper.py'
        tree = ast.parse(source.read_text())
        tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
        self.ns = dict(collections=collections, math=__import__('math'), os=__import__('os'), threading=threading,
                       time=time, Path=Path, InternetCoordinator=MagicMock(),
                       messagebox=MagicMock(), filedialog=MagicMock())
        class Var:
            def __init__(self, value=None, **kwargs):
                self.value = value
            def get(self):
                return self.value
            def set(self, value):
                self.value = value
        self.Var = Var
        self.widgets = []
        def widget(*args, **kwargs):
            item = MagicMock()
            item.winfo_exists.return_value = True
            item.cget.return_value = '#000000'
            self.widgets.append((kwargs, item))
            return item
        for name in ('Toplevel', 'Frame', 'Label', 'Entry', 'Button', 'Checkbutton', 'Radiobutton'):
            self.ns[name] = widget
        self.ns.update(StringVar=Var, BooleanVar=Var)
        figure = MagicMock()
        figure.add_subplot.return_value.plot.return_value = (MagicMock(),)
        self.ns['Figure'] = MagicMock(return_value=figure)
        self.ns['FigureCanvasTkAgg'] = MagicMock()
        modes = MagicMock()
        modes.enabled = Var(False)
        self.ns['get_qsfp_modes'] = lambda app: modes
        exec(compile(tree, str(source), 'exec'), self.ns)
        self.ns['_poll_qutag_counts'] = MagicMock()
        self.app = SimpleNamespace(root=widget(), tx_win=widget(), time_tagger=object(),
                                   ui=self.ns['TIMETAG_UI'], hydraharp=None)
        self.app.create_time_tagger_file_writer = MagicMock(return_value=MagicMock())
        self.app.tx_log_print = MagicMock()
        self.ns['open_qutag_timestamp_window'](self.app)
        self.coordinator = MagicMock()
        self.state = dict(ready=True, active=False, result=None, bytes=0,
                          blocks=0, started=None, finished=None, status='ready')
        self.coordinator.snapshot.side_effect = lambda: dict(self.state)
        self.app.timestamp_internet = self.coordinator
        self.app.qutag_timestamp_internet_var.set(True)
        self.ns['_poll_timestamp_file_size'] = MagicMock()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app.qutag_timestamp_file_var.set(str(Path(self.temp.name)/'capture.ttbin'))

    def test_panel_start_stop_and_metrics(self):
        self.assertTrue(any(options.get('text') == 'Internet' for options, _ in self.widgets))
        self.ns['_start_timestamp_writing'](self.app)
        self.app.create_time_tagger_file_writer.assert_called_once()
        self.coordinator.record.assert_called_once_with(
            Path(self.temp.name)/'capture.internet.bin', duration=3600)
        self.assertTrue(self.app.qutag_timestamp_writing)
        self.state.update(active=True, bytes=2048, blocks=2, started=time.monotonic()-1)
        self.ns['_poll_timestamp_internet'](self.app)
        self.assertIn('2.00 KB', self.app.qutag_timestamp_internet_size_var.get())
        self.assertIn('MB/s', self.app.qutag_timestamp_internet_speed_var.get())
        writer = self.app.time_tagger_file_writer
        self.ns['_stop_timestamp_writing'](self.app)
        writer.stop.assert_called_once()
        self.coordinator.stop_recording.assert_called_once()
        self.state.update(active=False, result=dict(status='complete'), finished=time.monotonic())
        self.ns['_stop_timestamp_writing'](self.app)
        self.assertFalse(self.app.qutag_timestamp_writing)
        self.ns['messagebox'].showerror.assert_not_called()

    def test_unready_service_does_not_start_local_writer(self):
        self.state['ready'] = False
        self.ns['_start_timestamp_writing'](self.app)
        self.app.create_time_tagger_file_writer.assert_not_called()
        self.coordinator.record.assert_not_called()
        self.ns['messagebox'].showerror.assert_called_once()

    def test_disabled_internet_keeps_local_recording(self):
        self.app.qutag_timestamp_internet_var.set(False)
        self.ns['_start_timestamp_writing'](self.app)
        self.app.create_time_tagger_file_writer.assert_called_once()
        self.coordinator.record.assert_not_called()
        self.ns['_stop_timestamp_writing'](self.app)
        self.assertFalse(self.app.qutag_timestamp_writing)

    def test_window_close_waits_for_transfer_then_closes_listener(self):
        self.ns['_start_timestamp_writing'](self.app)
        self.state['active'] = True
        self.ns['_close_timestamp_window'](self.app)
        self.assertTrue(self.app.qutag_timestamp_close_pending)
        self.app.qutag_timestamp_win.destroy.assert_not_called()
        self.state.update(active=False, result=dict(status='complete'))
        self.ns['_stop_timestamp_writing'](self.app)
        self.coordinator.close.assert_called_once()
        self.app.qutag_timestamp_win.destroy.assert_called_once()

    def timed_clock(self):
        """Execute Tk callbacks at controlled times, without sleeping or Tk."""
        from unittest.mock import MagicMock
        self.now = 100.0
        self.pending = {}
        self.timer_number = 0
        self.ns['time'] = SimpleNamespace(monotonic=lambda: self.now)
        def after(milliseconds, callback):
            self.timer_number += 1
            key = str(self.timer_number)
            self.pending[key] = (self.now + milliseconds / 1000, callback)
            return key
        for window in (self.app.root, self.app.qutag_timestamp_win):
            window.after.side_effect = after
            window.after_cancel.side_effect = lambda key: self.pending.pop(key, None)
        self.app.tx_trigger = MagicMock()
        self.coordinator.record.side_effect = lambda *args, **kwargs: self.state.update(active=True)

    def advance(self, seconds):
        target = self.now + seconds
        while self.pending:
            key, (deadline, callback) = min(self.pending.items(), key=lambda entry: entry[1][0])
            if deadline > target:
                break
            del self.pending[key]
            self.now = deadline
            callback()
        self.now = target

    def test_timed_finish_stops_both_and_waits_for_verified_drain(self):
        self.timed_clock()
        self.app.qutag_timestamp_time_auto_stop_var.set(True)
        self.app.qutag_timestamp_duration_limit_var.set('10')
        self.ns['_start_timestamp_writing'](self.app)
        writer = self.app.time_tagger_file_writer
        self.coordinator.record.assert_called_once_with(
            Path(self.temp.name)/'capture.internet.bin', duration=10.0)
        self.advance(2)
        self.assertTrue(self.app.qutag_timestamp_trigger_repeating)
        self.advance(7)
        self.assertFalse(self.app.qutag_timestamp_trigger_repeating)
        writer.stop.assert_not_called()
        self.advance(1)
        writer.stop.assert_called_once()
        self.coordinator.stop_recording.assert_called_once()
        self.assertEqual(self.app.qutag_timestamp_recording_var.get(), '[REC] OFF')
        self.assertIn('Waiting', self.app.qutag_timestamp_status_var.get())
        self.advance(2)
        self.assertEqual(self.ns['_update_timestamp_elapsed'](self.app), 10.0)
        self.coordinator.stop_recording.assert_called_once()
        self.state.update(active=False, result=dict(status='complete'))
        self.advance(0.2)
        self.assertFalse(self.app.qutag_timestamp_writing)
        self.assertEqual(self.app.qutag_timestamp_elapsed_s, 10.0)
        self.assertIsNone(self.app.qutag_timestamp_finish_after_id)
        self.ns['messagebox'].showerror.assert_not_called()

    def test_manual_stop_cancels_old_deadline_before_next_recording(self):
        self.timed_clock()
        self.app.qutag_timestamp_time_auto_stop_var.set(True)
        self.app.qutag_timestamp_duration_limit_var.set('10')
        self.ns['_start_timestamp_writing'](self.app)
        first_deadline = self.app.qutag_timestamp_finish_after_id
        self.advance(3)
        self.state.update(active=False, result=dict(status='complete'))
        self.ns['_stop_timestamp_writing'](self.app)
        self.assertNotIn(first_deadline, self.pending)
        self.state.update(result=None)
        from unittest.mock import MagicMock
        self.app.create_time_tagger_file_writer.return_value = MagicMock()
        self.app.qutag_timestamp_duration_limit_var.set('20')
        self.ns['_start_timestamp_writing'](self.app)
        second_writer = self.app.time_tagger_file_writer
        self.advance(7)  # Original recording's deadline.
        second_writer.stop.assert_not_called()
        self.assertTrue(self.app.qutag_timestamp_writing)
        self.advance(13)  # New recording's deadline.
        second_writer.stop.assert_called_once()

    def test_short_timed_capture_does_not_enable_trigger_late(self):
        self.timed_clock()
        self.app.qutag_timestamp_time_auto_stop_var.set(True)
        self.app.qutag_timestamp_duration_limit_var.set('0.5')
        self.ns['_start_timestamp_writing'](self.app)
        writer = self.app.time_tagger_file_writer
        self.advance(3)
        writer.stop.assert_called_once()
        self.coordinator.stop_recording.assert_called_once()
        self.app.tx_trigger.assert_not_called()

    def test_timed_finish_still_works_without_internet(self):
        self.timed_clock()
        self.app.qutag_timestamp_internet_var.set(False)
        self.app.qutag_timestamp_time_auto_stop_var.set(True)
        self.app.qutag_timestamp_duration_limit_var.set('5')
        self.ns['_start_timestamp_writing'](self.app)
        writer = self.app.time_tagger_file_writer
        self.advance(5)
        writer.stop.assert_called_once()
        self.coordinator.record.assert_not_called()
        self.assertFalse(self.app.qutag_timestamp_writing)

    def test_nonfinite_duration_is_rejected_before_recording(self):
        self.app.qutag_timestamp_time_auto_stop_var.set(True)
        for duration in ('nan', 'inf', '-inf'):
            with self.subTest(duration=duration):
                self.app.qutag_timestamp_duration_limit_var.set(duration)
                self.ns['_start_timestamp_writing'](self.app)
        self.app.create_time_tagger_file_writer.assert_not_called()
        self.coordinator.record.assert_not_called()


if __name__ == '__main__':
    unittest.main()
