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
                self.assertEqual(saved, {'env': 'second', 'port': '/dev/ttyUSB0'})
                menu.save(saved)
                self.assertEqual(menu.configuration()[1], saved)
                state.write_text('broken JSON')
                self.assertEqual(menu.configuration()[1]['env'], 'second')

    def test_upload_port_is_a_single_argument_and_only_for_upload(self):
        state = {'env': 'cores3', 'port': '/dev/port with spaces;literal'}
        self.assertEqual(menu.command('pio', state, 'upload'),
                         ['pio', 'run', '-e', 'cores3', '--target', 'upload',
                          '--upload-port', state['port']])
        self.assertEqual(menu.command('pio', state, 'build'), ['pio', 'run', '-e', 'cores3'])
        self.assertEqual(menu.command('pio', state, 'clean')[-2:], ['--target', 'clean'])

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
