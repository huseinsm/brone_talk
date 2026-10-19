"""Telemetri ke broker MQTT Jetson: status, tahap giliran, VAD, dan ekspresi wajah.

Kontrak topik (dibaca state_machine_node.py dan brone_talk_monitor.py) didokumentasikan di
docs/mqtt-contract.md. Dipindah dari brone_talk.py (v4).
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any

import paho.mqtt.client as mqtt

from brone_talk.config import MqttConfig

LOG = logging.getLogger("brone-talk")


class Telemetry:
    """Best-effort MQTT publisher. A broker outage must not stop a turn."""

    def __init__(self, cfg: MqttConfig) -> None:
        self.broker = cfg.broker
        self.port = cfg.port
        try:
            self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:  # Compatibility with older Paho releases.
            self.client = mqtt.Client()
        self.client.reconnect_delay_set(min_delay=1, max_delay=15)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.connected = False
        try:
            self.client.connect_async(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as exc:
            LOG.warning("MQTT tidak dapat dimulai: %s", exc)

    def _on_connect(self, _client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
        self.connected = str(reason_code) in {"0", "Success"} or reason_code == 0
        if self.connected:
            LOG.info("MQTT terhubung ke %s:%s", self.broker, self.port)
        else:
            LOG.warning("MQTT connect gagal: %s", reason_code)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: Any, _disconnect_flags: Any, reason_code: Any, _properties: Any = None) -> None:
        self.connected = False
        if reason_code not in (0, None):
            LOG.warning("MQTT terputus: %s", reason_code)

    def publish(self, topic: str, payload: dict[str, Any], qos: int = 0) -> None:
        try:
            self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=qos)
        except Exception as exc:
            LOG.debug("MQTT publish gagal untuk %s: %s", topic, exc)

    def status(self, status: str, detail: str = "") -> None:
        self.publish("robot/voice_status", {"status": status, "detail": detail}, qos=1)

    def stage(self, stage: str, state: str = "", **fields: Any) -> None:
        self.publish("robot/voice_stage", {"stage": stage, "state": state, "ts": time.time(), **fields})

    def vad(self, status: str, rms_float: float) -> None:
        self.publish("robot/vad_status", {"status": status, "rms": round(float(rms_float) * 32768, 1)})

    def expression(self, expression: str, duration: float | None = None) -> None:
        payload: dict[str, Any] = {"expression": expression}
        if duration is not None:
            payload["duration"] = max(1, math.ceil(duration))
        self.publish("robot/expression", payload)

    def close(self) -> None:
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
