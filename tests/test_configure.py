"""Build menu checks without compiling firmware or touching connected devices."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('build_menu', Path(__file__).resolve().parents[1] / 'configure.py')
menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu)


class ConfigureTests(unittest.TestCase):
    def test_targets_and_stale_saved_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'platformio.ini').write_text(
                '[platformio]\ndefault_envs = second\n[env]\n'
                '[env:first]\n[env:second]\n[helper]\n')
            state = root / '.build-menu.json'
            state.write_text('{"env":"removed", "port":"/dev/ttyUSB0"}')
            with patch.object(menu, 'ROOT', root), patch.object(menu, 'STATE', state):
                targets, saved = menu.configuration()
                self.assertEqual(targets, ['first', 'second'])
                self.assertEqual(saved, {'env': 'second', 'port': '/dev/ttyUSB0', 'emotion': 'llm',
                                         'wifi': True, 'wifi_repeater': False, 'ruview': False, 'ruview_mqtt_host': '', 'ruview_presence_topic': ''})
                menu.save(saved)
                self.assertEqual(menu.configuration()[1], saved)
                state.write_text('broken JSON')
                self.assertEqual(menu.configuration()[1]['env'], 'second')

    def test_emotion_choice_is_saved_and_passed_to_build_without_replacing_board_flags(self):
        state = {'env': 'cores3', 'port': '', 'emotion': 'llm'}
        with patch.dict(menu.os.environ, {'PLATFORMIO_BUILD_FLAGS': '-DKEEP_ME'}):
            environment = menu.build_environment(state)
        self.assertEqual(environment['OSIRIS_EMOTION_MODE'], 'llm')
        self.assertEqual(environment['PLATFORMIO_BUILD_FLAGS'], '-DKEEP_ME')
        with tempfile.TemporaryDirectory() as directory, patch.object(menu, 'STATE', Path(directory) / 'menu.json'):
            menu.save(state)
            self.assertEqual(menu.configuration()[1]['emotion'], 'llm')

    def test_menu_ruview_toggle_is_saved(self):
        from unittest.mock import Mock
        screen = Mock()
        screen.getmaxyx.return_value = (24, 100)
        screen.getch.side_effect = [menu.curses.KEY_DOWN] * 6 + [10] + [menu.curses.KEY_DOWN] * 4 + [10, ord('q')]
        state = {'env': 'cores3', 'port': '', 'emotion': 'llm', 'ruview': False}
        with patch.object(menu.curses, 'curs_set'), patch.object(menu, 'save') as save:
            menu.menu(screen, ['cores3'], state)
        self.assertTrue(state['ruview'])
        save.assert_called_once_with(state)

    def test_repeater_build_script_saved_setting_and_override(self):
        import json
        import runpy
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / '.build-menu.json'
            state.write_text(json.dumps({'wifi_repeater': True}))
            for override, expected in ((None, 1), ('off', 0), ('on', 1)):
                environment = Mock()
                environment.subst.return_value = directory
                variables = {} if override is None else {'OSIRIS_WIFI_REPEATER': override}
                with patch.dict(menu.os.environ, variables, clear=True):
                    runpy.run_path(str(menu.ROOT / 'scripts/build_options.py'),
                                   init_globals={'env': environment, 'Import': lambda name: None})
                self.assertIn(unittest.mock.call(CPPDEFINES=[('OSIRIS_WIFI_REPEATER', expected)]),
                              environment.Append.call_args_list)
            with patch.dict(menu.os.environ, {'OSIRIS_WIFI_REPEATER': 'bad'}, clear=True):
                with self.assertRaises(ValueError):
                    runpy.run_path(str(menu.ROOT / 'scripts/build_options.py'),
                                   init_globals={'env': environment, 'Import': lambda name: None})

    def test_repeater_menu_toggle_and_build_flags(self):
        from unittest.mock import Mock
        screen = Mock()
        screen.getmaxyx.return_value = (24, 100)
        screen.getch.side_effect = [menu.curses.KEY_DOWN] * 8 + [menu.curses.KEY_RIGHT, menu.curses.KEY_DOWN, menu.curses.KEY_DOWN, 10, ord('q')]
        state = {'env': 'cores3', 'port': '', 'emotion': 'llm'}
        with patch.object(menu.curses, 'curs_set'), patch.object(menu, 'save') as save:
            menu.menu(screen, ['cores3'], state)
        self.assertTrue(state['wifi_repeater'])
        save.assert_called_once_with(state)
        self.assertEqual(menu.build_environment(state)['OSIRIS_WIFI_REPEATER'], 'on')
        self.assertEqual(menu.build_environment({})['OSIRIS_WIFI_REPEATER'], 'off')
        with tempfile.TemporaryDirectory() as directory, patch.object(menu, 'STATE', Path(directory) / 'menu.json'), \
             patch('sys.argv', ['configure.py', '--wifi-repeater', 'on', '--save']):
            self.assertEqual(menu.main(), 0)
            self.assertTrue(menu.configuration()[1]['wifi_repeater'])
        with patch.object(menu, 'platformio', return_value='pio'), patch.object(menu, 'save') as save, \
             patch.object(menu.subprocess, 'run') as run, \
             patch('sys.argv', ['configure.py', '--wifi-repeater', 'off', '--dry-run']):
            self.assertEqual(menu.main(), 0)
            save.assert_not_called()
            run.assert_not_called()

    def test_wifi_off_menu_and_save_preserve_repeater_preference(self):
        from unittest.mock import Mock
        screen = Mock()
        screen.getmaxyx.return_value = (24, 100)
        screen.getch.side_effect = [menu.curses.KEY_DOWN] * 9 + [10, menu.curses.KEY_UP, 10,
                                  menu.curses.KEY_DOWN, menu.curses.KEY_DOWN, 10, ord('q')]
        state = {'env': 'cores3', 'port': '', 'emotion': 'llm', 'wifi_repeater': True}
        with patch.object(menu.curses, 'curs_set'), patch.object(menu, 'save') as save:
            menu.menu(screen, ['cores3'], state)
        self.assertFalse(state['wifi'])
        self.assertTrue(state['wifi_repeater'])
        save.assert_called_once_with(state)
        environment = menu.build_environment(state)
        self.assertEqual(environment['OSIRIS_WIFI_ENABLED'], 'off')
        self.assertEqual(environment['OSIRIS_WIFI_REPEATER'], 'off')
        with tempfile.TemporaryDirectory() as directory, patch.object(menu, 'STATE', Path(directory) / 'settings.json'), \
             patch('sys.argv', ['configure.py', '--wifi', 'off', '--save']):
            self.assertEqual(menu.main(), 0)
            self.assertFalse(menu.configuration()[1]['wifi'])

    def test_wifi_build_script_overrides_repeater_and_reenables_wifi(self):
        import json
        import runpy
        from unittest.mock import Mock, call
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / '.build-menu.json').write_text(json.dumps({'wifi': False, 'wifi_repeater': True}))
            for variables, wifi, repeater in (({}, 0, 0), ({'OSIRIS_WIFI_REPEATER': 'on'}, 0, 0),
                                              ({'OSIRIS_WIFI_ENABLED': 'on'}, 1, 1)):
                environment = Mock()
                environment.subst.return_value = directory
                with patch.dict(menu.os.environ, variables, clear=True):
                    runpy.run_path(str(menu.ROOT / 'scripts/build_options.py'),
                                   init_globals={'env': environment, 'Import': lambda name: None})
                self.assertIn(call(CPPDEFINES=[('OSIRIS_WIFI_ENABLED', wifi)]), environment.Append.call_args_list)
                self.assertIn(call(CPPDEFINES=[('OSIRIS_WIFI_REPEATER', repeater)]), environment.Append.call_args_list)
            with patch.dict(menu.os.environ, {'OSIRIS_WIFI_ENABLED': 'bad'}, clear=True):
                with self.assertRaises(ValueError):
                    runpy.run_path(str(menu.ROOT / 'scripts/build_options.py'),
                                   init_globals={'env': environment, 'Import': lambda name: None})

    def test_ruview_save_without_build_and_host_reads_it(self):
        import sys
        sys.path.insert(0, str(menu.ROOT / 'host'))
        from ruview_presence import saved_configuration
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            with patch.object(menu, 'STATE', path), patch.object(menu, 'platformio') as pio, \
                 patch('sys.argv', ['configure.py', '--ruview', 'on', '--ruview-mqtt-host', 'broker',
                                    '--ruview-presence-topic', 'room/presence', '--save']):
                self.assertEqual(menu.main(), 0)
                pio.assert_not_called()
                self.assertTrue(menu.configuration()[1]['ruview'])
                self.assertEqual(saved_configuration(path), {'enabled': True, 'ruview_mqtt_host': 'broker',
                                                            'ruview_presence_topic': 'room/presence'})
            path.write_text('[]')
            self.assertEqual(saved_configuration(path), {})

    def test_upload_port_is_a_single_argument_and_only_for_upload(self):
        state = {'env': 'cores3', 'port': '/dev/port with spaces;literal'}
        self.assertEqual(menu.command('pio', state, 'upload'),
                         ['pio', 'run', '-e', 'cores3', '--target', 'upload',
                          '--upload-port', state['port']])
        self.assertEqual(menu.command('pio', state, 'build'), ['pio', 'run', '-e', 'cores3'])
        self.assertEqual(menu.command('pio', state, 'clean')[-2:], ['--target', 'clean'])

    def test_menu_toggle_then_build_uses_selected_mode(self):
        from unittest.mock import Mock
        screen = Mock()
        screen.getmaxyx.return_value = (24, 100)
        screen.getch.side_effect = [menu.curses.KEY_DOWN, 10, menu.curses.KEY_DOWN, 10, ord('q')]
        state = {'env': 'cores3', 'port': '', 'emotion': 'legacy'}
        with patch.object(menu.curses, 'curs_set'), patch.object(menu.curses, 'def_prog_mode'), \
             patch.object(menu.curses, 'endwin'), patch.object(menu.curses, 'reset_prog_mode'), \
             patch.object(menu, 'platformio', return_value='pio'), patch.object(menu, 'save') as save, \
             patch.object(menu.subprocess, 'run') as run, patch('builtins.input', return_value=''):
            run.return_value.returncode = 0
            menu.menu(screen, ['cores3'], state)
        self.assertEqual(state['emotion'], 'llm')
        save.assert_called_once_with(state)
        self.assertEqual(run.call_args.args[0], ['pio', 'run', '-e', 'cores3'])
        self.assertEqual(run.call_args.kwargs['env']['OSIRIS_EMOTION_MODE'], 'llm')

    def test_dry_run_never_runs_or_saves_and_action_propagates_failure(self):
        with patch.object(menu, 'platformio', return_value='pio'), \
             patch.object(menu, 'save') as save, \
             patch.object(menu.subprocess, 'run') as run:
            with patch('sys.argv', ['configure.py', '--env', 'cores3', '--dry-run']):
                self.assertEqual(menu.main(), 0)
            save.assert_not_called()
            run.assert_not_called()
            run.return_value.returncode = 7
            with patch('sys.argv', ['configure.py', '--env', 'cores3', '--action', 'build']):
                self.assertEqual(menu.main(), 7)
            self.assertEqual(run.call_args.args[0], ['pio', 'run', '-e', 'cores3'])
            self.assertEqual(run.call_args.kwargs['cwd'], menu.ROOT)


if __name__ == '__main__':
    unittest.main()
