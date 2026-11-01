"""Apply menu options without replacing board-specific PlatformIO build flags."""
import json
import os
from pathlib import Path

Import('env')

state_path = Path(env.subst('$PROJECT_DIR')) / '.build-menu.json'
try:
    saved = json.loads(state_path.read_text())
except (OSError, ValueError):
    saved = {}
mode = os.environ.get('OSIRIS_EMOTION_MODE', saved.get('emotion', 'llm') if isinstance(saved, dict) else 'llm')
if mode not in ('legacy', 'llm'):
    raise ValueError('OSIRIS_EMOTION_MODE must be legacy or llm')
env.Append(CPPDEFINES=[('OSIRIS_LLM_EMOTION', int(mode == 'llm'))])
print('Osiris expressions: ' + mode)

wifi = os.environ.get('OSIRIS_WIFI_ENABLED')
if wifi is None:
    enabled = saved.get('wifi', True) if isinstance(saved, dict) else True
    wifi = 'off' if enabled is False else 'on'
if wifi not in ('on', 'off'):
    raise ValueError('OSIRIS_WIFI_ENABLED must be on or off')
env.Append(CPPDEFINES=[('OSIRIS_WIFI_ENABLED', int(wifi == 'on'))])
print('Osiris Wi-Fi: ' + wifi + (' (USB only)' if wifi == 'off' else ''))

repeater = os.environ.get('OSIRIS_WIFI_REPEATER')
if repeater is None:
    enabled = saved.get('wifi_repeater', False) if isinstance(saved, dict) else False
    repeater = 'on' if enabled is True else 'off'
if repeater not in ('on', 'off'):
    raise ValueError('OSIRIS_WIFI_REPEATER must be on or off')
if wifi == 'off':
    repeater = 'off'
env.Append(CPPDEFINES=[('OSIRIS_WIFI_REPEATER', int(repeater == 'on'))])
print('Osiris Wi-Fi repeater: ' + repeater)

sensor = os.environ.get('OSIRIS_BOX3_ENVIRONMENT')
if sensor is None:
    enabled = (isinstance(saved, dict) and saved.get('env') == 'esp32s3box3'
               and saved.get('sensor_dock') is True and saved.get('environment_sensor') is True)
    sensor = 'on' if enabled else 'off'
if sensor not in ('on', 'off'):
    raise ValueError('OSIRIS_BOX3_ENVIRONMENT must be on or off')
env.Append(CPPDEFINES=[('OSIRIS_BOX3_ENVIRONMENT', int(sensor == 'on'))])
print('Osiris BOX-3 temperature/humidity: ' + sensor)

battery = os.environ.get('OSIRIS_BOX3_BATTERY')
if battery is None:
    enabled = (isinstance(saved, dict) and saved.get('env') == 'esp32s3box3'
               and saved.get('sensor_dock') is True and saved.get('battery_sensor') is True)
    battery = 'on' if enabled else 'off'
if battery not in ('on', 'off'):
    raise ValueError('OSIRIS_BOX3_BATTERY must be on or off')
env.Append(CPPDEFINES=[('OSIRIS_BOX3_BATTERY', int(battery == 'on'))])
print('Osiris BOX-3 battery voltage/estimate: ' + battery)
