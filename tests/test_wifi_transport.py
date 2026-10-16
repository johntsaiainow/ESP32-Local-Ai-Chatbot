"""Exercise the real pyserial TCP adapter against a local BOX1 peer."""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import wave

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
from box3 import Box3, Box3Connection
from voice_agent import connection_options
from test_box3 import FakeSerial


class EndpointTests(unittest.TestCase):
    def test_both_endpoints_and_explicit_transport(self):
        with patch.dict(os.environ, {}, clear=True):
            endpoints, active = connection_options('/dev/usb', 'box', preferred='wifi')
            self.assertEqual(endpoints, {'usb': '/dev/usb', 'wifi': 'socket://box:8233'})
            self.assertEqual(active, 'wifi')
            self.assertEqual(connection_options('/dev/usb', 'box', preferred='usb')[1], 'usb')
            with self.assertRaises(ValueError):
                connection_options(host='box', preferred='usb')

    def test_explicit_selection_overrides_environment(self):
        with patch.dict(os.environ, {'BOX3_HOST': 'box', 'BOX3_PORT': '/dev/old'}, clear=True):
            self.assertEqual(connection_options('/dev/new')[1], 'usb')
            self.assertEqual(connection_options(host='new-box')[1], 'wifi')
            self.assertEqual(connection_options()[1], 'wifi')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(connection_options()[0], {})


class SwitchingTests(unittest.TestCase):
    def setUp(self):
        self.devices = []
        def factory(endpoint):
            device = Mock(status='BOX1 OK link=1 face=1')
            device.command.return_value = (b'', 'BOX1 OK requested=usb')
            self.devices.append(device)
            return device
        self.factory = Mock(side_effect=factory)
        self.connection = Box3Connection({'usb': '/dev/usb', 'wifi': 'socket://box:8233'},
                                         'usb', factory=self.factory)

    @patch('box3.time.sleep')
    def test_screen_request_switches_and_closes_previous_controller(self, sleep):
        first = self.devices[0]
        first.command.return_value = (b'', 'BOX1 OK requested=wifi')
        self.connection.poll_transport()
        self.assertEqual(self.connection.active, 'wifi')
        first.close.assert_called_once()
        self.devices[1].command.assert_any_call('LINK SET WIFI')
        self.devices[1].command.assert_any_call('LINK OPTIONS 1 1')
        self.connection.display('hello')
        self.devices[1].display.assert_called_once_with('hello')

    @patch('box3.time.sleep')
    def test_failed_switch_restores_previous_transport(self, sleep):
        restored = Mock(status='BOX1 OK link=1')
        self.factory.side_effect = [OSError('network unavailable'), restored]
        with self.assertRaisesRegex(RuntimeError, 'restored USB'):
            self.connection.switch('wifi')
        self.assertEqual(self.connection.active, 'usb')
        restored.command.assert_any_call('LINK SET USB')
        self.assertIs(self.connection.device, restored)

    def test_same_transport_does_not_reopen_device(self):
        self.connection.switch('usb')
        self.assertEqual(self.factory.call_count, 1)
        self.devices[0].close.assert_not_called()

    def test_missing_endpoint_does_not_close_current_controller(self):
        del self.connection.endpoints['wifi']
        with self.assertRaises(ValueError):
            self.connection.switch('wifi')
        self.devices[0].close.assert_not_called()

    def test_dual_transport_rejects_old_firmware_and_closes_it(self):
        old = Mock(status='BOX1 OK mic=1')
        with self.assertRaisesRegex(RuntimeError, 'link=1'):
            Box3Connection({'usb': 'usb', 'wifi': 'wifi'}, 'usb', factory=lambda _: old)
        old.close.assert_called_once()


@unittest.skipUnless(importlib.util.find_spec('serial'), 'pyserial is required')
class WiFiTransportTests(unittest.TestCase):
    def test_socket_handshake_display_recording_and_playback(self):
        peer = FakeSerial()
        peer.recording = b'\x10\x00' * 16000
        errors = []
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(5)

            def serve():
                try:
                    client, _ = listener.accept()
                    with client:
                        client.settimeout(5)
                        while True:
                            packet = client.recv(4096)
                            if not packet:
                                break
                            peer.write(packet)
                            if peer.response:
                                # Split replies to cover TCP framing across reads.
                                response = bytes(peer.response)
                                peer.response.clear()
                                client.sendall(response[:3])
                                client.sendall(response[3:])
                except Exception as exc:
                    errors.append(exc)

            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            box = Box3(f'socket://127.0.0.1:{listener.getsockname()[1]}', timeout=3)
            try:
                import socket as socket_module
                self.assertEqual(box.serial._socket.getsockopt(
                    socket_module.IPPROTO_TCP, socket_module.TCP_NODELAY), 1)
                box.status += ' netchunk=8192 netread=4096 upload=checked1 rx=4096'
                box.display('Wi-Fi 中文', 'zh-TW')
                self.assertEqual(box.capture(1), peer.recording)
                reads = [cmd for cmd in peer.commands if cmd.startswith('BOX1 READ ')]
                self.assertEqual(len(reads), 8)
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / 'reply.wav'
                    with wave.open(str(path), 'wb') as wav:
                        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                        wav.writeframes(peer.recording)
                    box.play(path)
                self.assertEqual(bytes(peer.played), peer.recording)
                chunks = [cmd for cmd in peer.commands if cmd.startswith('BOX1 CHUNK ')]
                self.assertEqual(len(chunks), 4)
                self.assertEqual(len(bytes.fromhex(chunks[0].split()[-1])), 8192)
            finally:
                box.close()
                worker.join(timeout=6)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
