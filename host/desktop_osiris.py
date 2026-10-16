#!/usr/bin/env python3
"""PyQt desktop port of Osiris. Run with host/.venv/bin/python host/desktop_osiris.py."""
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QSettings, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QTextCursor
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QPlainTextEdit, QPushButton, QSpinBox,
                             QScrollArea, QSplitter, QVBoxLayout, QWidget)
from desktop_core import DesktopEngine, Settings

EMOJI = dict(happy='1F600', listening='1F442', thinking='1F914', speaking='1F603',
             music='1F60E', sad='1F622', error='1F635', sleeping='1F634',
             waiting='231B', surprised='1F62E', love='1F970', success='1F389', warning='26A0')


class EngineThread(QThread):
    event = pyqtSignal(str, str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.engine = DesktopEngine(cfg, self.event.emit)

    def run(self):
        self.engine.run()


class OsirisWindow(QMainWindow):
    audio_devices = pyqtSignal(object, str)

    def __init__(self, store=None, worker_factory=EngineThread):
        super().__init__()
        self.store = store if store is not None else QSettings('Osiris', 'Desktop')
        self.worker_factory = worker_factory
        self.worker = None
        self.closing = False
        self.turn_open = False
        self.audio_devices.connect(self.populate_devices)
        self.setWindowTitle('Osiris Desktop')
        self.resize(1040, 740)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        title = QLabel('OSIRIS  /  Desktop voice companion')
        title.setStyleSheet('font-size: 23px; font-weight: 600; color: #79dfd2; padding: 8px;')
        outer.addWidget(title)
        split = QSplitter()
        outer.addWidget(split, 1)
        panel = QWidget()
        left = QVBoxLayout(panel)
        self.avatar = QLabel()
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setMinimumHeight(170)
        left.addWidget(self.avatar)
        self.state = QLabel('Ready to start')
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.state)
        self.countdown = QLabel('')
        self.countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.countdown)
        self.options = QGroupBox('Settings')
        form = QFormLayout(self.options)
        self.provider = QComboBox()
        self.provider.addItems(['pi', 'openai', 'gemini', 'openclaw'])
        self.provider.setCurrentText(self.store.value('provider', 'pi'))
        form.addRow('Provider', self.provider)
        self.model = QLineEdit(self.store.value('model', ''))
        self.model.setPlaceholderText('Provider model (Pi uses its CLI config)')
        form.addRow('Model', self.model)
        self.wake = QLineEdit(self.store.value('wake_phrase', 'Osiris'))
        form.addRow('Wake phrase', self.wake)
        self.language = QComboBox()
        self.language.addItems(['auto', 'en', 'zh-TW', 'zh'])
        self.language.setCurrentText(self.store.value('language', 'auto'))
        form.addRow('Speech language', self.language)
        self.whisper = QComboBox()
        self.whisper.setEditable(True)
        self.whisper.addItems(['tiny', 'base', 'small', 'medium', 'large-v3', 'turbo'])
        self.whisper.setCurrentText(self.store.value('whisper_model', 'small'))
        form.addRow('Whisper model', self.whisper)
        self.microphone = QCheckBox('Listen for wake phrase')
        self.microphone.setChecked(self.store.value('microphone', True, type=bool))
        form.addRow(self.microphone)
        self.speech = QCheckBox('Speak replies')
        self.speech.setChecked(self.store.value('speech', True, type=bool))
        form.addRow(self.speech)
        self.input = QComboBox()
        self.output = QComboBox()
        self.refresh = QPushButton('Refresh audio devices')
        self.refresh.clicked.connect(self.refresh_devices)
        form.addRow('Microphone', self.input)
        form.addRow('Speaker', self.output)
        form.addRow(self.refresh)
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 32000)
        self.threshold.setValue(self.store.value('threshold', 500, type=int))
        form.addRow('Voice threshold', self.threshold)
        self.silence = QDoubleSpinBox()
        self.silence.setRange(0.2, 2.0)
        self.silence.setSingleStep(0.1)
        self.silence.setSuffix(' s')
        self.silence.setValue(self.store.value('silence', 0.6, type=float))
        form.addRow('Pause to send', self.silence)
        left.addWidget(self.options)
        note = QLabel('API keys / Gateway token: environment variables.\nPi: uses the installed pi command.\nAudio: this computer’s microphone and speaker.')
        note.setWordWrap(True)
        note.setStyleSheet('color: #a8b5c7; font-size: 11px;')
        left.addWidget(note)
        left.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(340)
        split.addWidget(scroll)
        conversation = QWidget()
        right = QVBoxLayout(conversation)
        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText('Start Osiris, then speak or type a message. No ESP32 connection is needed.')
        self.chat.document().setMaximumBlockCount(2000)
        right.addWidget(self.chat, 1)
        self.heard = QLabel('')
        self.heard.setWordWrap(True)
        right.addWidget(self.heard)
        row = QHBoxLayout()
        self.message = QLineEdit()
        self.message.setPlaceholderText('Type a message — no wake phrase needed')
        self.message.setMaxLength(8192)
        self.message.returnPressed.connect(self.send)
        self.send_button = QPushButton('Send')
        self.send_button.clicked.connect(self.send)
        self.send_button.setEnabled(False)
        row.addWidget(self.message, 1)
        row.addWidget(self.send_button)
        right.addLayout(row)
        split.addWidget(conversation)
        split.setSizes([350, 690])
        controls = QHBoxLayout()
        self.start_button = QPushButton('Start Osiris')
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton('Stop')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.info = QLabel('Microphone stays off until you press Start.')
        self.info.setWordWrap(True)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.info, 1)
        outer.addLayout(controls)
        self.setStyleSheet('''
            QMainWindow, QWidget { background: #111c2c; color: #e6edf7; font-size: 13px; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
                background: #1b2c42; border: 1px solid #354b66; border-radius: 5px; padding: 6px; }
            QPlainTextEdit { font-size: 16px; }
            QPushButton { background: #254958; border: 1px solid #407e88; border-radius: 5px; padding: 9px; }
            QPushButton:disabled { color: #718096; background: #202d3e; }
            QGroupBox { border: 1px solid #354b66; border-radius: 7px; margin-top: 12px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; }
        ''')
        self.show_state('sleeping')
        self.refresh_devices()

    def refresh_devices(self):
        for widget in (self.input, self.output):
            widget.clear()
            widget.addItem('System default', None)
        self.refresh.setEnabled(False)
        def enumerate_audio():
            try:
                import sounddevice as sd
                devices, error = list(sd.query_devices()), ''
            except Exception as exc:
                devices, error = [], str(exc)
            try:
                self.audio_devices.emit(devices, error)
            except RuntimeError:
                pass  # Window was destroyed while the OS enumerated devices.
        threading.Thread(target=enumerate_audio, daemon=True).start()

    def populate_devices(self, devices, error):
        self.refresh.setEnabled(True)
        if error:
            self.info.setText(f'Audio unavailable: {error}. Disable listening and speech for text chat.')
            return
        for index, dev in enumerate(devices):
            label = f'{dev["name"]} [{index}]'
            if dev['max_input_channels']:
                self.input.addItem(label, index)
            if dev['max_output_channels']:
                self.output.addItem(label, index)
        for widget, name in ((self.input, 'input_name'), (self.output, 'output_name')):
            match = widget.findText(self.store.value(name, ''))
            if match >= 0:
                widget.setCurrentIndex(match)

    def configuration(self):
        return Settings(provider=self.provider.currentText(), model=self.model.text().strip(),
                        wake_phrase=self.wake.text(), language=self.language.currentText(),
                        whisper_model=self.whisper.currentText().strip(),
                        microphone=self.microphone.isChecked(), speech=self.speech.isChecked(),
                        input_device=self.input.currentData(), output_device=self.output.currentData(),
                        threshold=self.threshold.value(), silence=self.silence.value())

    def start(self):
        if self.worker is not None:
            return
        try:
            cfg = self.configuration()
            worker = self.worker_factory(cfg, self)
        except Exception as exc:
            self.handle_event('error', str(exc))
            return
        for key in ('provider', 'model', 'wake_phrase', 'language', 'whisper_model',
                    'microphone', 'speech', 'threshold', 'silence'):
            self.store.setValue(key, getattr(cfg, key))
        self.store.setValue('input_name', self.input.currentText())
        self.store.setValue('output_name', self.output.currentText())
        self.worker = worker
        worker.event.connect(self.handle_event)
        worker.finished.connect(self.worker_finished)
        self.options.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        worker.start()

    def stop(self):
        if self.worker:
            self.worker.engine.stop()
            self.stop_button.setEnabled(False)
            self.send_button.setEnabled(False)
            self.info.setText('Stopping… waiting for active speech/model work to finish.')

    def worker_finished(self):
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        self.turn_open = False
        self.send_button.setEnabled(False)
        self.options.setEnabled(True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.countdown.clear()
        if self.state.text() != 'Error':
            self.show_state('sleeping')
            self.info.setText('Stopped. Microphone is off.')
        if self.closing:
            QTimer.singleShot(0, self.close)

    def send(self):
        if not self.worker or not self.send_button.isEnabled():
            return
        try:
            self.worker.engine.submit(self.message.text())
        except ValueError as exc:
            self.info.setText(str(exc))
            return
        self.message.clear()
        self.send_button.setEnabled(False)

    def append(self, text):
        cursor = self.chat.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.chat.setTextCursor(cursor)
        self.chat.ensureCursorVisible()

    def show_state(self, state):
        path = Path(__file__).parent / 'desktop_assets' / f'u{EMOJI.get(state, "1F600")}.png'
        pix = QPixmap(str(path))
        self.avatar.setPixmap(pix.scaled(144, 144, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
        self.state.setText(state.capitalize())

    def handle_event(self, kind, value):
        if kind == 'state':
            self.show_state(value)
        elif kind == 'info':
            self.info.setText(value)
        elif kind == 'countdown':
            self.countdown.setText(f'Listening window: {value}s' if value else '')
        elif kind == 'heard':
            self.heard.setText(f'Heard: {value}' if value else 'No speech recognized.')
        elif kind == 'user':
            self.turn_open = True
            self.send_button.setEnabled(False)
            self.append(f'\nYou: {value}\n\nOsiris: ')
        elif kind == 'delta':
            self.append(value)
        elif kind == 'error':
            self.turn_open = False
            self.show_state('error')
            self.append(f'\n[Error] {value}\n')
            self.info.setText(value)
            if self.worker and not self.worker.engine.stopping.is_set():
                self.send_button.setEnabled(True)
        elif kind in ('ready', 'complete'):
            self.turn_open = False
            self.send_button.setEnabled(bool(self.worker and not self.worker.engine.stopping.is_set()))

    def closeEvent(self, event):
        if self.worker is not None:
            self.closing = True
            self.stop()
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Osiris Desktop')
    window = OsirisWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
