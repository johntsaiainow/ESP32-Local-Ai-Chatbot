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
    def test_battery_menu_and_dock_dependency(self):
        from unittest.mock import Mock
        screen = Mock()
        screen.getmaxyx.return_value = (24, 100)
        state = dict(env='esp32s3box3', emotion='llm', port='', sensor_dock=False)
        screen.getch.side_effect = [menu.curses.KEY_DOWN] * 10 + [10, ord('q')]
        with patch.object(menu.curses, 'curs_set'):
            menu.menu(screen, ['esp32s3box3'], state)
        self.assertFalse(state['battery_sensor'])
        state['sensor_dock'] = True
        screen.getch.side_effect = [menu.curses.KEY_DOWN] * 10 + [10, ord('q')]
        with patch.object(menu.curses, 'curs_set'):
            menu.menu(screen, ['esp32s3box3'], state)
        self.assertTrue(state['battery_sensor'])
        self.assertEqual(menu.build_environment(state)['OSIRIS_BOX3_BATTERY'], 'on')
        state['sensor_dock'] = False
        menu.normalize_sensors(state)
        self.assertFalse(state['battery_sensor'])

    def test_hidden_legacy_host_settings_survive_firmware_save(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            legacy = dict(language='zh', ruview=True, ruview_mqtt_host='broker',
                          ruview_presence_topic='room/presence')
            path.write_text(json.dumps(legacy))
            with patch.object(menu, 'STATE', path):
                _, state = menu.configuration()
                self.assertNotIn('language', state)
                self.assertNotIn('ruview', state)
                menu.save(state)
            saved = json.loads(path.read_text())
            for key, value in legacy.items():
                self.assertEqual(saved[key], value)

    def test_sensor_build_flag_requires_both_saved_options(self):
        import json
        import runpy
        from unittest.mock import Mock, call
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for dock, feature, expected in ((False, True, 0), (True, False, 0), (True, True, 1)):
                (root / '.build-menu.json').write_text(json.dumps(dict(
                    env='esp32s3box3', sensor_dock=dock, environment_sensor=feature, battery_sensor=feature)))
                build = Mock()
                build.subst.return_value = directory
                with patch.dict(menu.os.environ, {}, clear=True):
                    runpy.run_path(str(Path(__file__).parents[1] / 'scripts/build_options.py'),
                                   init_globals={'env': build, 'Import': lambda name: None})
                self.assertIn(call(CPPDEFINES=[('OSIRIS_BOX3_ENVIRONMENT', expected)]),
                              build.Append.call_args_list)
                self.assertIn(call(CPPDEFINES=[('OSIRIS_BOX3_BATTERY', expected)]),
                              build.Append.call_args_list)

    def test_sensor_dependency_and_cli(self):
        state = dict(env='esp32s3box3', sensor_dock=True, environment_sensor=True)
        self.assertEqual(menu.build_environment(state)['OSIRIS_BOX3_ENVIRONMENT'], 'on')
        state['sensor_dock'] = False
        menu.normalize_sensors(state)
        self.assertFalse(state['environment_sensor'])
        state.update(env='cores3', sensor_dock=True, environment_sensor=True)
        menu.normalize_sensors(state)
        self.assertFalse(state['sensor_dock'])
        self.assertFalse(state['environment_sensor'])
        with patch.object(menu, 'configuration', return_value=(['esp32s3box3'],
                         dict(env='esp32s3box3', sensor_dock=False))), \
             patch('sys.argv', ['configure.py', '--environment-sensor', 'on', '--save']), \
             self.assertRaises(SystemExit) as raised:
            menu.main()
        self.assertEqual(raised.exception.code, 2)

    def test_sensor_menu_requires_dock(self):
        from unittest.mock import Mock
        state = dict(env='esp32s3box3', sensor_dock=False, environment_sensor=False,
                     port='', emotion='llm')
        screen = Mock()
        screen.getmaxyx.return_value = (24, 100)
        screen.getch.side_effect = [menu.curses.KEY_DOWN] * 9 + [10, ord('q')]
        with patch.object(menu.curses, 'curs_set'):
            menu.menu(screen, ['esp32s3box3'], state)
        self.assertFalse(state['environment_sensor'])
        screen.getch.side_effect = ([menu.curses.KEY_DOWN] * 8 + [10, menu.curses.KEY_DOWN, 10]
                                    + [menu.curses.KEY_DOWN] * 2 + [10, ord('q')])
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(menu, 'STATE', Path(directory) / 'state.json'), \
             patch.object(menu.curses, 'curs_set'):
            menu.menu(screen, ['esp32s3box3'], state)
            self.assertTrue(state['sensor_dock'])
            self.assertTrue(state['environment_sensor'])
            self.assertTrue(__import__('json').loads(menu.STATE.read_text())['environment_sensor'])

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
                                         'wifi': True, 'wifi_repeater': False,
                                         'sensor_dock': False, 'environment_sensor': False, 'battery_sensor': False})
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
        screen.getch.side_effect = [menu.curses.KEY_DOWN] * 6 + [menu.curses.KEY_RIGHT] + [menu.curses.KEY_DOWN] * 5 + [10, ord('q')]
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
        screen.getch.side_effect = [menu.curses.KEY_DOWN] * 7 + [10, menu.curses.KEY_UP, 10] + [menu.curses.KEY_DOWN] * 5 + [10, ord('q')]
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
