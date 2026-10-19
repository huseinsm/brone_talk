"""Suara robot: sintesis Piper (ONNX) lalu playback lewat sounddevice.

Dipindah dari brone_talk.py (v4). Hanya Piper: Soniox TTS sudah dihapus di versi lama.
"""

from __future__ import annotations

import logging
import subprocess
import time
import uuid
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

from brone_talk.audio.devices import resolve_device
from brone_talk.config import AudioConfig, TtsConfig
from brone_talk.telemetry import Telemetry
from brone_talk.tts.normalize import clean_for_speech

LOG = logging.getLogger("brone-talk")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


class Speaker:
    def __init__(self, cfg: TtsConfig, audio: AudioConfig, telemetry: Telemetry, runtime_dir: Path) -> None:
        self.telemetry = telemetry
        self.runtime_dir = runtime_dir
        self.output_device = resolve_device(audio.output_device, input_device=False)
        self.playback_enabled = audio.playback
        self.backend = "piper"  # dibaca warmup (telemetri)
        self.piper_bin = Path(cfg.piper_bin)
        self.voice_model = cfg.voice_model
        self.voice_config = cfg.voice_config
        if not self.piper_bin.is_file():
            raise RuntimeError(f"Piper CLI tidak ditemukan: {self.piper_bin}")
        self.sample_rate = 22_050  # id_ID-news_tts-medium.onnx.json -> audio.sample_rate
        sd.check_output_settings(device=self.output_device, samplerate=self.sample_rate, channels=1, dtype="float32")

    def synthesize(self, text: str) -> tuple[Path, float, float]:
        text = clean_for_speech(text)
        if not text:
            raise ValueError("Tidak ada teks untuk disintesis")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        output = self.runtime_dir / f"reply-{uuid.uuid4().hex}.wav"
        started = time.perf_counter()
        try:
            self._synthesize_piper(text, output)
        except Exception:
            output.unlink(missing_ok=True)
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        return output, elapsed_ms, wav_duration(output)

    def _synthesize_piper(self, text: str, output: Path) -> None:
        command = [
            str(self.piper_bin),
            "--model", str(self.voice_model),
            "--config", str(self.voice_config),
            "--output-file", str(output),
        ]
        completed = subprocess.run(
            command,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file():
            error = completed.stderr.decode("utf-8", "replace")[-300:]
            raise RuntimeError(f"Piper gagal (rc={completed.returncode}): {error}")

    def play(self, path: Path) -> None:
        sample_rate, data = wavfile.read(path)
        if data.ndim == 1:
            data = data[:, np.newaxis]
        if np.issubdtype(data.dtype, np.integer):
            data = data.astype(np.float32) / np.iinfo(data.dtype).max
        else:
            data = data.astype(np.float32)
        sd.play(data, sample_rate, device=self.output_device, blocking=True)

    def say(self, text: str, expression: str) -> bool:
        self.telemetry.stage("tts", "start")
        path: Path | None = None
        try:
            path, synth_ms, duration_s = self.synthesize(text)
            self.telemetry.expression("speaking", duration_s)
            played = False
            if self.playback_enabled:
                self.play(path)
                played = True
            self.telemetry.stage(
                "tts",
                "done",
                ms=round(synth_ms),
                audio_s=round(duration_s, 2),
                played=played,
            )
            LOG.info("TTS %.2fs (audio=%.2fs, played=%s): %r", synth_ms / 1000, duration_s, played, text[:120])
            return played
        except Exception as exc:
            self.telemetry.stage("error", "tts", detail=str(exc)[:200])
            LOG.exception("TTS atau playback gagal")
            return False
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
            self.telemetry.expression(expression)
