import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from host import connection_setup as setup


class ConnectionSetupTests(unittest.TestCase):
    def test_wizard_roundtrip_and_start_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'profile.json'
            values = ['tools', 'wifi', '', '192.168.1.50', '9000',
                      '/tmp/python with spaces', '', 'zh', '', '']
            with patch.object(setup, 'PROFILE', profile), \
                 patch('builtins.input', side_effect=values):
                setup.setup(setup.defaults())
                saved = setup.load()
                with patch.dict(setup.os.environ, {'BOX3_HOST': 'stale-host'}):
                    command, environment = setup.invocation(saved)
                self.assertEqual(command[-2:], ['-e', str(setup.ROOT / 'pi/box3.ts')])
                self.assertEqual(environment['BOX3_PORT'], 'socket://192.168.1.50:9000')
                self.assertNotIn('BOX3_HOST', environment)
                self.assertEqual(environment['BOX3_PYTHON'], '/tmp/python with spaces')
                with patch.object(setup.subprocess, 'run') as run:
                    self.assertEqual(setup.main(['--host-check', '--dry-run']), 0)
                    run.assert_not_called()

    def test_invalid_profile_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'profile.json'
            profile.write_text('{broken')
            with patch.object(setup, 'PROFILE', profile), self.assertRaises(ValueError):
                setup.load()
            self.assertEqual(profile.read_text(), '{broken')

    def test_voice_and_check_arguments(self):
        profile = dict(setup.defaults(), mode='voice', port='/dev/ttyUSB1')
        with patch.object(setup.shutil, 'which', return_value='/custom/bin/pi'):
            command, environment = setup.invocation(profile)
        self.assertIn('--provider', command)
        self.assertEqual(command[command.index('--port') + 1], '/dev/ttyUSB1')
        self.assertTrue(environment['PATH'].startswith('/custom/bin:'))
        command, _ = setup.invocation(profile, check=True)
        self.assertEqual(command[-3:], ['--port', '/dev/ttyUSB1', 'status'])

    def test_reject_invalid_endpoint_and_tcp_port(self):
        for updates in ({'tcp_port': True}, {'tcp_port': 70000},
                        {'transport': 'wifi', 'host': 'http://example.com'}, {'port': ''}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                setup.validate(dict(setup.defaults(), **updates))
