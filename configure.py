#!/usr/bin/env python3
"""Terminal menu for the PlatformIO firmware targets (Python standard library)."""

import argparse
import configparser
import curses
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.build-menu.json'
LABELS = {
    'esp32s3box3': 'Espressif ESP32-S3-BOX-3',
    'lichuang_s3': 'LiChuang SZPI ESP32-S3',
    'cores3': 'M5Stack CoreS3',
    'crowpanel7_inmp441': 'CrowPanel 7-inch + INMP441 (4 MB)',
    'atoms3r_echo': 'AtomS3R + Atomic Echo Base (8 MB)',
}


def configuration():
    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT / 'platformio.ini')
    targets = [s[4:] for s in config.sections() if s.startswith('env:')]
    if not targets:
        raise ValueError('No board environments found in platformio.ini')
    default = config.get('platformio', 'default_envs', fallback=targets[0])
    default = default.replace(',', ' ').split()[0]
    state = {'env': default if default in targets else targets[0], 'port': '', 'emotion': 'llm',
             'wifi': True, 'wifi_repeater': False, 'ruview': False, 'ruview_mqtt_host': '', 'ruview_presence_topic': ''}
    try:
        saved = json.loads(STATE.read_text())
        if isinstance(saved, dict):
            if saved.get('env') in targets:
                state['env'] = saved['env']
            if isinstance(saved.get('port'), str):
                state['port'] = saved['port']
            if isinstance(saved.get('wifi'), bool):
                state['wifi'] = saved['wifi']
            if isinstance(saved.get('wifi_repeater'), bool):
                state['wifi_repeater'] = saved['wifi_repeater']
            if isinstance(saved.get('ruview'), bool):
                state['ruview'] = saved['ruview']
            for key in ('ruview_mqtt_host', 'ruview_presence_topic'):
                if isinstance(saved.get(key), str):
                    state[key] = saved[key]
            if saved.get('emotion') in ('legacy', 'llm'):
                state['emotion'] = saved['emotion']
    except (OSError, ValueError):
        pass
    return targets, state


def save(state):
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(STATE)


def platformio():
    for name in ('pio', 'platformio'):
        executable = shutil.which(name)
        if executable:
            return executable
    executable = Path.home() / '.platformio/penv/bin/pio'
    if executable.is_file():
        return str(executable)
    raise ValueError('PlatformIO Core was not found. Install it or add pio to PATH.')


def command(executable, state, action):
    args = [executable, 'run', '-e', state['env']]
    if action in ('upload', 'clean'):
        args += ['--target', action]
    if action == 'upload' and state['port']:
        args += ['--upload-port', state['port']]
    return args


def build_environment(state):
    return dict(os.environ, OSIRIS_EMOTION_MODE=state.get('emotion', 'llm'),
                OSIRIS_WIFI_ENABLED='on' if state.get('wifi', True) else 'off',
                OSIRIS_WIFI_REPEATER='on' if state.get('wifi', True) and state.get('wifi_repeater', False) else 'off')


def describe_command(args, state):
    return ('OSIRIS_EMOTION_MODE=' + state.get('emotion', 'llm') +
            ' OSIRIS_WIFI_ENABLED=' + ('on' if state.get('wifi', True) else 'off') +
            ' OSIRIS_WIFI_REPEATER=' + ('on' if state.get('wifi', True) and state.get('wifi_repeater', False) else 'off') +
            ' ' + shlex.join(args))


def menu(screen, targets, state):
    curses.curs_set(0)
    selected = 0
    status = ''
    actions = ['Build firmware', 'Build and upload', 'Clean build files',
               'Upload port', 'RuView presence wake', 'RuView MQTT settings', 'Wi-Fi repeater', 'Wi-Fi', 'Save configuration', 'Exit']
    while True:
        emotion = 'Legacy state expressions' if state['emotion'] == 'legacy' else 'LLM emoji prefix (21 moods)'
        rows = [f"PCB: {LABELS.get(state['env'], state['env'])}", f'Expressions: {emotion}'] + actions
        rows[6] = 'RuView presence wake (host): ' + ('ON' if state.get('ruview', False) else 'OFF')
        rows[8] = 'Wi-Fi repeater (firmware): ' + ('ON' if state.get('wifi_repeater', False) else 'OFF')
        rows[9] = 'Wi-Fi (firmware): ' + ('ON' if state.get('wifi', True) else 'OFF - USB only')
        if not state.get('wifi', True):
            rows[8] = 'Wi-Fi repeater (firmware): unavailable - Wi-Fi OFF'
        screen.erase()
        height, width = screen.getmaxyx()

        def line(y, value, attr=0):
            if y < height - 1 and width > 1:
                screen.addnstr(y, 0, value, width - 1, attr)

        line(0, 'Osiris firmware configuration', curses.A_BOLD)
        line(1, 'Up/Down: move | Left/Right: change | Enter: select | q: exit')
        line(3, f"Environment: {state['env']}   Port: {state['port'] or 'auto-detect'}")
        for index, row in enumerate(rows):
            line(5 + index, ('> ' if index == selected else '  ') + row,
                 curses.A_REVERSE if index == selected else 0)
        line(18, status)
        if height < 20 or width < 50:
            line(0, 'Resize terminal to at least 50 columns x 20 rows.')
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'), 27):
            return
        if key == curses.KEY_UP:
            selected = (selected - 1) % len(rows)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(rows)
        elif selected == 0 and key in (curses.KEY_LEFT, curses.KEY_RIGHT, 10, 13):
            step = -1 if key == curses.KEY_LEFT else 1
            state['env'] = targets[(targets.index(state['env']) + step) % len(targets)]
        elif selected == 1 and key in (curses.KEY_LEFT, curses.KEY_RIGHT, 10, 13, curses.KEY_ENTER):
            state['emotion'] = 'llm' if state['emotion'] == 'legacy' else 'legacy'
        elif selected == 8 and key in (curses.KEY_LEFT, curses.KEY_RIGHT, 10, 13, curses.KEY_ENTER):
            if state.get('wifi', True):
                state['wifi_repeater'] = not state.get('wifi_repeater', False)
        elif selected == 9 and key in (curses.KEY_LEFT, curses.KEY_RIGHT, 10, 13, curses.KEY_ENTER):
            state['wifi'] = not state.get('wifi', True)
        elif selected == 6 and key in (curses.KEY_LEFT, curses.KEY_RIGHT, 10, 13, curses.KEY_ENTER):
            state['ruview'] = not state.get('ruview', False)
        elif key in (10, 13, curses.KEY_ENTER):
            if selected == 11:
                return
            if selected == 10:
                save(state)
                status = 'Configuration saved.'
                continue
            if selected == 7:
                curses.def_prog_mode()
                curses.endwin()
                try:
                    for field, label in (('ruview_mqtt_host', 'MQTT broker hostname'),
                                         ('ruview_presence_topic', 'Presence state topic')):
                        current = state.get(field, '')
                        value = input(f'{label} [{current}] (Enter keeps, - clears): ').strip()
                        if value:
                            state[field] = '' if value == '-' else value
                finally:
                    curses.reset_prog_mode()
                    screen.clear()
                continue
            if selected == 5:
                curses.def_prog_mode()
                curses.endwin()
                try:
                    state['port'] = input('Upload port (blank = auto-detect): ').strip()
                finally:
                    curses.reset_prog_mode()
                    screen.clear()
                continue
            if selected in (2, 3, 4):
                action = ('build', 'upload', 'clean')[selected - 2]
                args = command(platformio(), state, action)
                save(state)
                curses.def_prog_mode()
                curses.endwin()
                try:
                    print('\n' + describe_command(args, state), flush=True)
                    try:
                        result = subprocess.run(args, cwd=ROOT, env=build_environment(state), check=False)
                        status = f'{action}: exit code {result.returncode}'
                    except KeyboardInterrupt:
                        status = f'{action}: interrupted'
                    print(status)
                    input('Press Enter to return to menu...')
                finally:
                    curses.reset_prog_mode()
                    screen.clear()


def main():
    targets, state = configuration()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='list available PCB environments')
    parser.add_argument('--env', choices=targets)
    parser.add_argument('--port', help='upload port; default is auto-detect or saved port')
    parser.add_argument('--emotion', choices=('legacy', 'llm'), help='legacy state expressions or LLM emoji prefix')
    parser.add_argument('--wifi', choices=('on', 'off'), help='enable Wi-Fi or compile USB-only firmware')
    parser.add_argument('--wifi-repeater', choices=('on', 'off'), help='compile firmware with/without Wi-Fi NAT repeater')
    parser.add_argument('--ruview', choices=('on', 'off'), help='enable/disable host RuView presence wake')
    parser.add_argument('--ruview-mqtt-host', help='MQTT broker hostname for the host voice agent')
    parser.add_argument('--ruview-presence-topic', help='exact RuView presence state topic')
    parser.add_argument('--save', action='store_true', help='save configuration without building or opening menu')
    parser.add_argument('--action', choices=('build', 'upload', 'clean'))
    parser.add_argument('--dry-run', action='store_true', help='print command without running or saving')
    args = parser.parse_args()
    if args.list:
        for target in targets:
            print(f'{target:24} {LABELS.get(target, target)}')
        return 0
    if args.env:
        state['env'] = args.env
    if args.port is not None:
        state['port'] = args.port
    if args.emotion:
        state['emotion'] = args.emotion
    if args.wifi is not None:
        state['wifi'] = args.wifi == 'on'
    if args.wifi_repeater is not None:
        state['wifi_repeater'] = args.wifi_repeater == 'on'
    if args.ruview is not None:
        state['ruview'] = args.ruview == 'on'
    for field in ('ruview_mqtt_host', 'ruview_presence_topic'):
        if getattr(args, field) is not None:
            state[field] = getattr(args, field)
    if args.save and not args.action and not args.dry_run:
        save(state)
        print('Configuration saved. RuView host presence wake: ' + ('ON' if state['ruview'] else 'OFF'))
        print('Wi-Fi firmware option: ' + ('ON' if state['wifi'] else 'OFF - USB only') + '; rebuild/upload to apply')
        print('Wi-Fi repeater firmware option: ' + ('ON' if state['wifi'] and state['wifi_repeater'] else 'OFF') + '; rebuild/upload to apply')
        return 0
    if args.action or args.dry_run:
        invocation = command(platformio(), state, args.action or 'build')
        print(describe_command(invocation, state), flush=True)
        if args.dry_run:
            return 0
        save(state)
        return subprocess.run(invocation, cwd=ROOT, env=build_environment(state), check=False).returncode
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('TUI requires a terminal; use --action build --env ENV for scripts.')
    if os.environ.get('TERM', '') in ('', 'dumb'):
        parser.error('Set TERM to a supported terminal type to use the TUI.')
    curses.wrapper(menu, targets, state)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, curses.error) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        sys.exit(130)
