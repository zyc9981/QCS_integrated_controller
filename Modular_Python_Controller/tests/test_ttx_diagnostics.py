"""Exercise the real App constructor and __main__ with hardware/UI substitutes."""
import ast
import collections
from datetime import datetime
import logging
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock


class DiagnosticsTests(unittest.TestCase):
    def test_normal_startup_and_threaded_sdk_messages(self):
        source = Path(__file__).resolve().parents[1] / 'python_controller.py'
        tree = ast.parse(source.read_text())
        app_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        # Keep the actual constructor, diagnostic/device methods and main block.
        # Avoid importing the GUI, serial and laser libraries on a test machine.
        app_node.bases = []
        main = tree.body[-1]
        module = ast.fix_missing_locations(ast.Module(body=[app_node, main], type_ignores=[]))
        sdk = Mock()
        registered = []
        sdk.setLogger.side_effect = registered.append

        def opening():
            self.assertEqual(len(registered), 1)
            registered[0](0, 'opening message\ncomplete second line')
            return Mock()

        sdk.createTimeTagger.side_effect = opening
        sdk.freeTimeTagger.side_effect = lambda device: registered[0](99, 'closing message')
        with tempfile.TemporaryDirectory() as directory:
            scope = dict(__name__='test', __file__=str(source), logging=logging, os=os, datetime=datetime,
                         Path=Path, threading=threading, queue=queue,
                         collections=collections, PROJECT_ROOT=Path(directory),
                         TimeTagger=sdk, UI={}, TX_PORT='TX', RX_PORT='RX',
                         ENABLE_TTX_DIAGNOSTICS=True,
                         DEFAULT_VOLTAGES_PATH=Path('defaults.json'),
                         RX_BACKGROUND_OFFSETS_PATH=Path('offsets.json'),
                         RefSource=None, LASER_HOST='test', Tk=Mock,
                         Button=Mock(return_value=Mock()), open_arduino=Mock(),
                         readline_str=lambda serial: 'TX Ready.' if serial is tx else 'RX Ready.',
                         DLCProSimple=Mock())
            tx, rx = object(), object()
            scope['open_arduino'].side_effect = [tx, rx]
            exec(compile(module, str(source), 'exec'), scope)
            cls = scope['App']
            for name in ('load_rx_background_offsets', 'load_hydraharp_time_trace_settings',
                         'init_hydraharp', 'build_rx_panel', 'tx_log_print', 'tx_init_voltages'):
                setattr(cls, name, Mock(return_value={}))
            def build_tx(instance):
                instance.tx_win = Mock()
                instance.rx_win = Mock()
            cls.build_tx_panel = build_tx
            # Execute the unchanged normal entry point: App(); app.root.mainloop().
            entry = dict(scope, __name__='__main__')
            scope['open_arduino'].side_effect = [tx, rx]
            registered.clear()
            exec(compile(ast.fix_missing_locations(ast.Module(body=[main], type_ignores=[])),
                         str(source), 'exec'), entry)
            app = entry['app']
            callback = app.time_tagger_sdk_callback
            app._start_time_tagger_log()
            self.assertIs(app.time_tagger_sdk_callback, callback)
            self.assertEqual(sdk.setLogger.call_count, 1)
            app.root.mainloop.assert_called_once()
            workers = [threading.Thread(target=registered[0], args=(level, f'worker {level}'))
                       for level in (-1, 0, 1, 2, 3, 100)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            app.time_tagger_marker('CH3 LED observed red; no SDK event required')
            app.create_time_tagger_file_writer('test.ttbin', [3])
            app.shutdown_time_tagger()
            registered[0](0, 'late callback')
            text = app.time_tagger_log_path.read_text()
            self.assertLess(text.index('SDK logger registered'), text.index('Device opening'))
            self.assertIn('opening message\ncomplete second line', text)
            for level in (-1, 0, 1, 2, 3, 100):
                self.assertIn(f'SDK level={level} message=worker {level}', text)
            for message in ('CH3 LED observed red', 'Timestamp acquisition started',
                            'device closing', 'closing message', 'late callback'):
                self.assertIn(message, text)
            self.assertIn('Acquisition started: live Counter', text)
            # Explicit test cleanup; production keeps the callback alive to exit.
            for handler in app.time_tagger_logger.handlers:
                handler.close()


if __name__ == '__main__':
    unittest.main()
