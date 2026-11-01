import argparse
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
import voice_agent
import voice_settings


class VoiceSettingsTests(unittest.TestCase):
    def test_legacy_profiles_migrate_and_new_profile_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_host = dict(transport='wifi', host='192.168.1.8', tcp_port=9000,
                               language='en', whisper_model='base', models_dir='/tmp/models',
                               pi='/custom/bin/pi')
            legacy_build = dict(language='zh', ruview=False, ruview_mqtt_host='broker',
                                ruview_presence_topic='room/presence')
            (root / '.host-connection.json').write_text(json.dumps(legacy_host))
            (root / '.build-menu.json').write_text(json.dumps(legacy_build))
            settings = root / '.voice-agent.json'
            with patch.object(voice_settings, 'SETTINGS', settings), \
                 patch.object(sys, 'argv', ['voice_agent.py', '--save-config']), \
                 patch('sys.stdout', io.StringIO()):
                voice_agent.main()
            saved = json.loads(settings.read_text())
            self.assertEqual(saved['language'], 'zh')
            self.assertEqual(saved['host'], '192.168.1.8')
            self.assertEqual(saved['tcp_port'], 9000)
            self.assertEqual(saved['pi_executable'], '/custom/bin/pi')
            self.assertEqual(saved['models_dir'], '/tmp/models')
            self.assertEqual(saved['ruview_mqtt_host'], 'broker')
            self.assertFalse(saved['ruview_enabled'])
            self.assertEqual(json.loads((root / '.build-menu.json').read_text()), legacy_build)
            with patch.object(voice_settings, 'SETTINGS', settings), \
                 patch.object(sys, 'argv', ['voice_agent.py', '--port', '/dev/new', '--save-config']), \
                 patch('sys.stdout', io.StringIO()):
                voice_agent.main()
            saved = json.loads(settings.read_text())
            self.assertEqual(saved['port'], '/dev/new')
            self.assertIsNone(saved['host'])

    def test_interactive_setup_saves_without_loading_models(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'voice.json'
            with patch.object(voice_settings, 'SETTINGS', settings), \
                 patch.object(sys, 'argv', ['voice_agent.py', '--ignore-config', '--setup']), \
                 patch('builtins.input', side_effect=lambda prompt: '/dev/setup' if prompt.startswith('port ') else 'zh' if prompt.startswith('language ') else ''), \
                 patch.object(voice_agent, 'create_recognizer') as recognizer, \
                 patch('sys.stdout', io.StringIO()):
                voice_agent.main()
            recognizer.assert_not_called()
            saved = json.loads(settings.read_text())
            self.assertEqual(saved['port'], '/dev/setup')
            self.assertEqual(saved['language'], 'zh')
            self.assertNotIn('setup', saved)

    def test_console_saves_current_transport_volume_and_microphone(self):
        box = Mock(status='BOX1 OK', endpoints={'usb': '/dev/test',
                   'wifi': 'socket://192.168.1.5:9000'}, active='wifi', playback_volume=30)
        commands = Mock()
        commands.get.side_effect = ['/config save', '/quit']
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'voice.json'
            with patch.object(voice_settings, 'SETTINGS', settings), \
                 patch.object(sys, 'argv', ['voice_agent.py', '--ignore-config', '--port', '/dev/test', '--keyboard-only']), \
                 patch.object(voice_agent.queue, 'Queue', return_value=commands), \
                 patch.object(voice_agent.threading, 'Thread'), \
                 patch.object(voice_agent, 'PiRPC'), \
                 patch.object(voice_agent, 'Box3Connection', return_value=box), \
                 patch('sys.stdout', io.StringIO()):
                voice_agent.main()
            saved = json.loads(settings.read_text())
            self.assertEqual(saved['transport'], 'wifi')
            self.assertEqual(saved['tcp_port'], 9000)
            self.assertEqual(saved['host'], '192.168.1.5')
            self.assertEqual(saved['port'], '/dev/test')
            self.assertEqual(saved['volume'], 30)
            self.assertTrue(saved['mic_off'])

    def test_save_config_exits_without_models_or_device_and_reloads(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'voice.json'
            with patch.object(voice_settings, 'SETTINGS', settings), \
                 patch.object(voice_agent, 'create_recognizer') as recognizer, \
                 patch.object(voice_agent, 'Box3Connection') as connection, \
                 patch.object(voice_agent, 'CloudChat') as cloud, \
                 patch('sys.stdout', io.StringIO()), \
                 patch.object(sys, 'argv', ['voice_agent.py', '--ignore-config', '--save-config',
                                          '--port', '/dev/test', '--language', 'zh', '--volume', '40']):
                voice_agent.main()
                recognizer.assert_not_called()
                connection.assert_not_called()
                cloud.assert_not_called()
            saved = json.loads(settings.read_text())
            self.assertEqual(saved['port'], '/dev/test')
            self.assertEqual(saved['language'], 'zh')
            self.assertNotIn('save_config', saved)
            with patch.object(voice_settings, 'SETTINGS', settings), \
                 patch.object(voice_agent, 'create_recognizer'), \
                 patch.object(sys, 'argv', ['voice_agent.py', '--save-config', '--volume', '60']), \
                 patch('sys.stdout', io.StringIO()):
                voice_agent.main()
            self.assertEqual(json.loads(settings.read_text())['volume'], 60)

    def test_endpoint_override_and_mutually_exclusive_options(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--port')
        parser.add_argument('--host')
        parser.add_argument('--transport')
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--ruview', dest='ruview_enabled', action='store_true', default=None)
        group.add_argument('--no-ruview', dest='ruview_enabled', action='store_false')
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'voice.json'
            settings.write_text(json.dumps(dict(host='old', transport='wifi', ruview_enabled=True)))
            with patch.object(voice_settings, 'SETTINGS', settings):
                args = voice_settings.parse_arguments(parser, ['--port', '/dev/new', '--no-ruview'])
                self.assertEqual(args.port, '/dev/new')
                self.assertIsNone(args.host)
                self.assertIsNone(args.transport)
                self.assertFalse(args.ruview_enabled)

    def test_corrupt_config_can_be_bypassed(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--ignore-config', action='store_true')
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'voice.json'
            settings.write_text('bad json')
            with patch.object(voice_settings, 'SETTINGS', settings):
                with self.assertRaises(ValueError):
                    voice_settings.parse_arguments(parser, [])
                self.assertTrue(voice_settings.parse_arguments(parser, ['--ignore-config']).ignore_config)
