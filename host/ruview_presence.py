"""Optional RuView MQTT presence input; callbacks never touch the device."""
import json
from pathlib import Path
import threading
import time


class PresenceTrigger:
    """One wake per arrival, with absence hysteresis and expiring events."""
    def __init__(self, clock=time.monotonic, absence_seconds=5, max_age=10):
        self.clock = clock
        self.absence_seconds = absence_seconds
        self.max_age = max_age
        self.lock = threading.Lock()
        self.occupied = False
        self.absent_since = None
        self.pending = None

    def update(self, present, retained=False):
        if retained:
            return  # Old broker state is not evidence of a new arrival.
        with self.lock:
            now = self.clock()
            if not present:
                if self.absent_since is None:
                    self.absent_since = now
                self.pending = None
                return
            if self.absent_since is not None and now - self.absent_since >= self.absence_seconds:
                self.occupied = False
            self.absent_since = None
            if not self.occupied:
                self.pending = now
                self.occupied = True

    def consume(self):
        with self.lock:
            event, self.pending = self.pending, None
            return event is not None and self.clock() - event <= self.max_age

    def disconnect(self):
        with self.lock:
            self.pending = None
            # Preserve occupancy: reconnecting must not create another arrival.


class RuViewPresence:
    def __init__(self, host, port, topic, username=None, password=None,
                 on_payload='ON', off_payload='OFF', tls=False):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise ValueError('RuView requires: pip install -r host/requirements-ruview.txt') from exc
        self.trigger = PresenceTrigger()
        self.topic = topic
        self.on_payload = on_payload.encode()
        self.off_payload = off_payload.encode()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self.client.username_pw_set(username, password)
        if tls:
            self.client.tls_set()
        self.client.on_connect = self._connect
        self.client.on_message = self._message
        self.client.on_disconnect = lambda *args: self.trigger.disconnect()
        self.client.connect_async(host, port, keepalive=30)
        self.client.loop_start()

    def _connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(self.topic, qos=1)

    def _message(self, client, userdata, message):
        if message.topic != self.topic:
            return
        if message.payload == self.on_payload:
            self.trigger.update(True, message.retain)
        elif message.payload == self.off_payload:
            self.trigger.update(False, message.retain)

    def consume(self):
        return self.trigger.consume()

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()


def saved_configuration(path=None):
    """Read configure.py's optional host defaults without requiring a valid file."""
    path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / '.build-menu.json'
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict):
        return {}
    result = {}
    if isinstance(state.get('ruview'), bool):
        result['enabled'] = state['ruview']
    for field in ('ruview_mqtt_host', 'ruview_presence_topic'):
        if isinstance(state.get(field), str):
            result[field] = state[field]
    return result
