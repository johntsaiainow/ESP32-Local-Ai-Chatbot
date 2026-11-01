"""Persist voice-agent arguments, keeping argparse validation on reload."""
import argparse
import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / '.voice-agent.json'
CONTROL = {'help', 'save_config', 'ignore_config', 'setup'}


def read_legacy(name):
    try:
        value = json.loads((SETTINGS.parent / name).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def load_arguments(parser):
    # Legacy files remain intact. Saving in the voice agent consolidates these values.
    host = read_legacy('.host-connection.json')
    saved = {key: host[key] for key in ('language', 'whisper_model', 'models_dir') if key in host}
    if host.get('pi'):
        saved['pi_executable'] = host['pi']
    if host.get('transport') == 'wifi' and host.get('host'):
        saved.update(host=host['host'], tcp_port=host.get('tcp_port', 8233), transport='wifi')
    elif host.get('port'):
        saved.update(port=host['port'], transport='usb')
    build = read_legacy('.build-menu.json')
    if build.get('language') in ('auto', 'zh', 'en'):
        saved['language'] = build['language']
    if isinstance(build.get('ruview'), bool):
        saved['ruview_enabled'] = build['ruview']
    for key in ('ruview_mqtt_host', 'ruview_presence_topic'):
        if build.get(key):
            saved[key] = build[key]
    if SETTINGS.exists():
        current = json.loads(SETTINGS.read_text())
        if not isinstance(current, dict):
            raise ValueError('Voice configuration must be a JSON object')
        # A saved voice profile is complete; do not reintroduce legacy endpoints.
        saved = current
    result = []
    for action in parser._actions:
        if action.dest in CONTROL or action.dest not in saved:
            continue
        value = saved[action.dest]
        if value is None:
            continue
        if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
            if type(value) is not bool:
                raise ValueError(f'Invalid saved boolean: {action.dest}')
            if value == action.const:
                result.append(action.option_strings[0])
        else:
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise ValueError(f'Invalid saved option: {action.dest}')
            result.append(action.option_strings[0] + '=' + str(value))
    return result


def save_arguments(args):
    saved = {key: str(value) if isinstance(value, Path) else value
             for key, value in vars(args).items() if key not in CONTROL}
    temporary = SETTINGS.with_suffix('.tmp')
    temporary.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(SETTINGS)


def parse_arguments(parser, argv):
    # Help and an explicit opt-out remain usable if the saved JSON is damaged.
    saved = [] if any(flag in argv for flag in ('--ignore-config', '--help', '-h')) else load_arguments(parser)
    destinations = {option: action.dest for action in parser._actions for option in action.option_strings}
    overrides = {destinations[arg.split('=', 1)[0]] for arg in argv if arg.split('=', 1)[0] in destinations}
    saved = [arg for arg in saved if destinations.get(arg.split('=', 1)[0]) not in overrides]
    # A newly selected endpoint must win over a previously saved transport.
    if any(arg == '--host' or arg.startswith('--host=') or arg == '--port' or arg.startswith('--port=') for arg in argv):
        saved = [arg for arg in saved if not arg.startswith(('--host=', '--port=', '--transport='))]
    return parser.parse_args(saved + argv)


def setup_arguments(parser, args):
    print('Voice agent settings / 主機設定 (Enter keeps; - clears optional values)')
    fields = ('port', 'host', 'transport', 'tcp_port', 'language', 'provider', 'model', 'pi_executable',
              'whisper_model', 'models_dir', 'wake_word', 'wake_aliases', 'threshold', 'silence',
              'capture_mode', 'volume', 'followup_timeout', 'ruview_mqtt_host', 'ruview_presence_topic')
    actions = {action.dest: action for action in parser._actions}
    for key in fields:
        action = actions[key]
        choices = ' (' + '/'.join(map(str, action.choices)) + ')' if action.choices else ''
        value = input(f'{key}{choices} [{getattr(args, key) or ""}]: ').strip()
        if value == '-':
            if key not in ('port', 'host', 'transport', 'model', 'wake_word', 'wake_aliases', 'ruview_mqtt_host', 'ruview_presence_topic'):
                parser.error(f'{key} cannot be cleared')
            setattr(args, key, None)
        elif value:
            args = parser.parse_args([action.option_strings[0] + '=' + value], namespace=args)
    current = args.ruview_enabled
    if current is None:
        current = bool(args.ruview_mqtt_host and args.ruview_presence_topic)
    switch = input(f'RuView on/off [{"on" if current else "off"}]: ').strip().lower()
    if switch not in ('', 'on', 'off'):
        parser.error('RuView must be on or off')
    args.ruview_enabled = (switch == 'on') if switch else current
    args.save_config = True
    return args
