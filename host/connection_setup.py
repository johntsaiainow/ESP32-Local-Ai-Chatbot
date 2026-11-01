"""Saved host connection wizard; standard library only, no shell evaluation."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / '.host-connection.json'


def defaults():
    python = ROOT / 'host/.venv/bin/python'
    return dict(mode='tools', transport='usb', port='/dev/ttyACM0',
                host='', tcp_port=8233, python=str(python) if python.exists() else 'python3',
                pi='pi', language='auto', whisper_model='small',
                models_dir=str(Path('~/aion-voice/models').expanduser()))


def validate(profile):
    for key in defaults():
        if key != 'tcp_port' and (not isinstance(profile.get(key), str) or '\x00' in profile[key]):
            raise ValueError(f'Invalid host setting: {key}')
    for key, choices in dict(mode=('tools', 'voice'), transport=('usb', 'wifi'),
                             language=('auto', 'en', 'zh')).items():
        if profile[key] not in choices:
            raise ValueError(f'Invalid {key}: {profile[key]}')
    if type(profile.get('tcp_port')) is not int or not 1 <= profile['tcp_port'] <= 65535:
        raise ValueError('TCP port must be between 1 and 65535')
    for key in ('python', 'pi', 'models_dir', 'whisper_model',
                'host' if profile['transport'] == 'wifi' else 'port'):
        if not profile[key].strip():
            raise ValueError(f'{key} cannot be empty')
    if profile['transport'] == 'wifi' and any(c in profile['host'] for c in '/: \t\n'):
        raise ValueError('Enter a Wi-Fi hostname or IPv4 address without scheme or port')


def load():
    profile = defaults()
    if PROFILE.exists():
        saved = json.loads(PROFILE.read_text())
        if not isinstance(saved, dict):
            raise ValueError('Host connection profile must be a JSON object')
        profile.update({k: v for k, v in saved.items() if k in profile})
        validate(profile)
    return profile


def setup(profile):
    print('Pi host connection / Pi 主機連線設定（Enter 保留原值）')
    fields = [('mode', 'Mode: tools = Pi display/listen/say tools; voice = voice conversation'),
              ('transport', 'Transport: usb / wifi'), ('port', 'USB device port'),
              ('host', 'ESP32 Wi-Fi IP / hostname'), ('tcp_port', 'ESP32 TCP port'),
              ('python', 'Host Python executable (speech dependencies installed here)'),
              ('pi', 'Pi CLI executable'), ('language', 'Voice language: auto / en / zh'),
              ('whisper_model', 'Whisper model'), ('models_dir', 'Piper / Vosk models directory')]
    for key, label in fields:
        value = input(f'{label} [{profile[key]}]: ').strip()
        if value:
            profile[key] = int(value) if key == 'tcp_port' else value
    validate(profile)
    temporary = PROFILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(PROFILE)
    print('Legacy Pi tools profile saved. For voice mode, use host/voice_agent.py --setup.')


def invocation(profile, check=False):
    validate(profile)
    endpoint = (f"socket://{profile['host']}:{profile['tcp_port']}"
                if profile['transport'] == 'wifi' else profile['port'])
    environment = dict(os.environ, BOX3_PORT=endpoint, BOX3_PYTHON=profile['python'],
                       BOX3_MODELS_DIR=str(Path(profile['models_dir']).expanduser()),
                       BOX3_WHISPER_MODEL=profile['whisper_model'])
    environment.pop('BOX3_HOST', None)
    if check:
        args = [profile['python'], str(ROOT / 'host/box3.py'), '--port', endpoint, 'status']
    elif profile['mode'] == 'tools':
        args = [profile['pi'], '-e', str(ROOT / 'pi/box3.ts')]
    else:
        # The voice agent starts Pi internally through PATH.
        pi = shutil.which(profile['pi'])
        if not pi or Path(pi).name != 'pi':
            raise ValueError('Voice mode requires a Pi executable named pi available on PATH or by absolute path')
        environment['PATH'] = str(Path(pi).absolute().parent) + os.pathsep + environment.get('PATH', '')
        args = [profile['python'], str(ROOT / 'host/voice_agent.py'), '--provider', 'pi',
                '--port', endpoint, '--language', profile['language'],
                '--whisper-model', profile['whisper_model']]
    return args, environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for name in ('setup', 'start', 'check'):
        actions.add_argument('--host-' + name, action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='show command without connecting')
    parser.add_argument('--language', choices=('auto', 'zh', 'en'), help='override host speech language for this invocation')
    args = parser.parse_args(argv)
    profile = load()
    if args.language is not None:
        profile['language'] = args.language
    if args.host_setup:
        if args.dry_run:
            parser.error('--dry-run applies to --host-start or --host-check')
        setup(profile)
        return 0
    if not PROFILE.exists():
        raise ValueError('Run python3 -m host.connection_setup --host-setup first')
    command, environment = invocation(profile, args.host_check)
    print(shlex.join(command), flush=True)
    if args.dry_run:
        return 0
    return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
