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
