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
                self.assertEqual(saved, {'env': 'second', 'port': '/dev/ttyUSB0', 'emotion': 'llm'})
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
