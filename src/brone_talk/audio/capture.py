"""Perekaman audio: mic dipilih dari PipeWire (ALSA) atau sounddevice, lalu endpointing ucapan.

Dipindah dari brone_talk.py (v4). Dua jalur (ALSA dengan arah suara, dan sounddevice) memakai
satu Endpointer dan satu finalisasi. Perbedaan kecil: jalur sounddevice kini juga mengirim
field doa=None dan doa_conf=0.0 di telemetri "done" (sebelumnya tidak ada).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

from brone_talk.audio.constants import SAMPLE_RATE, VAD_WINDOW
from brone_talk.audio.devices import device_name, parse_card_nodes, resolve_device
from brone_talk.audio.endpointing import CaptureLost, Endpointer, StopCapture, Utterance
from brone_talk.audio.vad import SileroVad
from brone_talk.config import AudioConfig
from brone_talk.speaker_lock.lock import DirectionEstimator

LOG = logging.getLogger("brone-talk")


@dataclass
class Capture:
    path: Path
    duration_s: float
    peak_rms: float
    audio: np.ndarray | None = None  # mono float32 @ SAMPLE_RATE, untuk sidik suara
    doa_deg: float | None = None  # arah ucapan dari 4 mic mentah (bingkai array)
    doa_conf: float = 0.0  # koherensi arah 0..1


class Recorder:
    def __init__(self, cfg: AudioConfig, telemetry, stop_event: Event, vad: SileroVad,
                 runtime_dir: Path, doa_enabled: bool) -> None:
        self.cfg = cfg
        self.telemetry = telemetry
        self.stop_event = stop_event
        self.vad = vad
        self.runtime_dir = runtime_dir
        self.threshold = cfg.vad_threshold
        self.max_duration_s = cfg.max_utterance_s
        self.silence_s = cfg.end_silence_s
        self.min_speech_s = cfg.min_speech_s
        self.min_utterance_rms = cfg.min_utterance_rms  # gate energi (ambient ruangan ~0,01-0,05)
        self.backend = cfg.backend
        self.input_device: int | None = None
        self.alsa_device = ""
        self.arecord_bin = ""
        self.pw_node = ""
        self.noise_reduce_enabled = cfg.noise_reduce
        self.noise_reduce_prop = cfg.noise_prop_decrease
        self.noise_reduce_stationary = cfg.noise_stationary
        self.noise_reducer = None
        if self.noise_reduce_enabled:
            try:
                import noisereduce as _nr

                self.noise_reducer = _nr
                LOG.info("Denoise in-code aktif (prop_decrease=%.2f)", self.noise_reduce_prop)
            except Exception as exc:  # pragma: no cover
                LOG.warning("noisereduce tidak tersedia: %s", exc)
                self.noise_reduce_enabled = False
        if self.backend == "alsa":
            self.alsa_device = cfg.alsa_device
            # mic dipilih tiap rekaman dari kartu yang tersambung; urutan = prioritas.
            # pw_node hanya cadangan kalau tak ada yang cocok.
            self.pw_node = cfg.pw_node.strip()
            self.pw_nodes = parse_card_nodes(cfg.pw_nodes)
            self._active_pw_node = ""
            # arah ucapan untuk kunci penanya: 4 mic mentah XVF3800 direkam paralel
            self.doa_node = cfg.doa_node.strip()
            self.doa_card = cfg.doa_card.strip()
            self.doa = DirectionEstimator() if self.doa_node and doa_enabled else None
            self.arecord_bin = shutil.which("arecord") or ""
            if not self.arecord_bin:
                raise RuntimeError("arecord tidak tersedia untuk input ALSA")
            cards = Path("/proc/asound/cards").read_text(encoding="utf-8")
            if "BRIO" in self.alsa_device.upper() and "[BRIO" not in cards:
                raise RuntimeError(f"ALSA capture device tidak tersedia: {self.alsa_device}")
        elif self.backend == "sounddevice":
            self.input_device = resolve_device(cfg.input_device, input_device=True)
            sd.check_input_settings(device=self.input_device, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        else:
            raise RuntimeError("BRONE_AUDIO_INPUT_BACKEND harus 'alsa' atau 'sounddevice'")

    def _endpointer(self) -> tuple[Endpointer, int]:
        silence_limit = max(1, int(self.silence_s * SAMPLE_RATE / VAD_WINDOW))
        window_limit = max(1, int(self.max_duration_s * SAMPLE_RATE / VAD_WINDOW))
        return Endpointer(self.vad, self.telemetry, self.threshold, silence_limit, window_limit), window_limit

    def record(self) -> Capture | None:
        self.vad.reset()
        if self.backend == "alsa":
            return self._record_alsa()
        return self._record_sounddevice()

    # -- sumber audio ---------------------------------------------------------
    def _sounddevice_blocks(self, window_limit: int):
        with sd.InputStream(device=self.input_device, samplerate=SAMPLE_RATE, channels=1,
                            dtype="float32", blocksize=VAD_WINDOW) as stream:
            for _ in range(window_limit):
                if self.stop_event.is_set():
                    raise StopCapture()
                block, overflowed = stream.read(VAD_WINDOW)
                if overflowed:
                    LOG.warning("Input audio overflow")
                yield block[:, 0].copy()

    def _pipe_blocks(self, process: subprocess.Popen, window_limit: int):
        for _ in range(window_limit):
            if self.stop_event.is_set():
                raise StopCapture()
            raw = process.stdout.read(VAD_WINDOW * 2)
            if len(raw) != VAD_WINDOW * 2:
                raise CaptureLost()
            yield np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0

    # -- jalur perekaman --------------------------------------------------------
    def _record_sounddevice(self) -> Capture | None:
        endpointer, window_limit = self._endpointer()
        self.telemetry.stage("listening", "start", device=device_name(self.input_device), sample_rate=SAMPLE_RATE)
        LOG.info("Mendengarkan dari %s", device_name(self.input_device))
        try:
            utt = endpointer.run(self._sounddevice_blocks(window_limit))
        except StopCapture:
            return None
        return self._finish(utt, doa_raw=None)

    def _record_alsa(self) -> Capture | None:
        endpointer, window_limit = self._endpointer()
        cards = Path("/proc/asound/cards").read_text(encoding="utf-8")
        pw_node = self._select_pw_node(cards)
        command = [self.arecord_bin, "--quiet", "--device", self.alsa_device,
                   "--format=S16_LE", f"--rate={SAMPLE_RATE}", "--channels=1", "--file-type=raw"]
        self.telemetry.stage("listening", "start", device=self.alsa_device, sample_rate=SAMPLE_RATE)
        LOG.info("Mendengarkan dari ALSA %s", self.alsa_device)
        env = os.environ.copy()
        if pw_node:
            env["PIPEWIRE_NODE"] = pw_node
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env)
        doa_capture = self._start_doa_capture(cards)
        utt: Utterance | None = None
        stopped = lost = False
        try:
            utt = endpointer.run(self._pipe_blocks(process, window_limit))
        except StopCapture:
            stopped = True
        except CaptureLost:
            lost = True
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            doa_raw = self._stop_doa_capture(doa_capture)
        if stopped:
            return None
        if lost:
            device = self._next_capture_device()
            if device:
                LOG.warning("Capture %s gagal, coba %s", self.alsa_device, device)
                self.alsa_device = device
                return self._record_alsa()
            raise RuntimeError("arecord berhenti sebelum satu window audio diterima")
        return self._finish(utt, doa_raw=doa_raw)

    # -- finalisasi bersama -------------------------------------------------------
    def _finish(self, utt: Utterance, doa_raw: np.ndarray | None) -> Capture | None:
        if not utt.frames:
            self.telemetry.vad("silence", utt.peak_rms)
            self.telemetry.stage("listening", "timeout", peak_rms=round(utt.peak_rms * 32768, 1))
            LOG.info("Tidak ada suara terdeteksi dalam %.0fs (peak_rms=%.4f) — cek mic/gain jika ini terus terjadi",
                     self.max_duration_s, utt.peak_rms)
            return None
        audio = self._denoise(np.concatenate(utt.frames))
        duration_s = len(audio) / SAMPLE_RATE
        if duration_s < self.min_speech_s:
            self.telemetry.stage("listening", "too_short", audio_s=round(duration_s, 2))
            return None
        # buang klip tanpa energi bicara nyata (sisa derau ruangan)
        utterance_rms = float(np.sqrt(np.mean(np.square(audio))))
        if utterance_rms < self.min_utterance_rms:
            self.telemetry.stage("listening", "low_energy", rms=round(utterance_rms, 4))
            LOG.info("Klip energi rendah (rms=%.4f) diabaikan", utterance_rms)
            return None

        doa_deg, doa_conf = None, 0.0
        if doa_raw is not None and self.doa is not None:
            try:
                doa_deg, doa_conf = self.doa.estimate(doa_raw, utt.speech_start, utt.speech_end)
            except Exception as exc:
                LOG.warning("Arah suara gagal dihitung: %s", exc)
            if doa_deg is not None:
                LOG.info("Arah ucapan %.0f° (koherensi %.2f)", doa_deg, doa_conf)

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        path = self.runtime_dir / f"input-{uuid.uuid4().hex}.wav"
        wavfile.write(path, SAMPLE_RATE, (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16))
        self.telemetry.vad("stopped", utt.peak_rms)
        self.telemetry.stage(
            "listening", "done",
            audio_s=round(duration_s, 2),
            peak_rms=round(utt.peak_rms * 32768, 1),
            doa=None if doa_deg is None else round(doa_deg, 1),
            doa_conf=round(doa_conf, 2),
        )
        return Capture(path=path, duration_s=duration_s, peak_rms=utt.peak_rms,
                       audio=audio, doa_deg=doa_deg, doa_conf=doa_conf)

    # -- helper (disalin apa adanya dari brone_talk.py v4) --------------------------
    def _next_capture_device(self) -> str:
        """Kandidat device berikutnya kalau arecord gagal membuka device."""
        # hw:Array (XVF3800) dipegang PipeWire, jadi fallback plughw langsung
        # pasti "busy"; "default" tetap lewat PipeWire ke default source.
        order = ["pipewire", "default"]
        tried = getattr(self, "_tried_devices", set())
        tried.add(self.alsa_device)
        self._tried_devices = tried
        for cand in order:
            if cand not in tried:
                return cand
        return ""

    def _select_pw_node(self, cards: str) -> str:
        node = next((n for card, n in self.pw_nodes if card in cards), self.pw_node)
        if node != self._active_pw_node:
            LOG.info("Mic aktif: PipeWire node %s", node)
            self.telemetry.stage("listening", "mic", node=node)
            self._active_pw_node = node
        return node

    def _start_doa_capture(self, cards: str) -> tuple[subprocess.Popen, Thread, bytearray] | None:
        """Rekam 4 mic mentah paralel dengan mic utama (hanya kalau XVF3800 tersambung)."""
        if self.doa is None or self.doa_card not in cards:
            return None
        env = os.environ.copy()
        env["PIPEWIRE_NODE"] = self.doa_node
        process = subprocess.Popen(
            [self.arecord_bin, "--quiet", "--device", "pipewire", "--format=S16_LE",
             f"--rate={SAMPLE_RATE}", "--channels=4", "--file-type=raw"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        )
        buf = bytearray()

        def pump() -> None:
            assert process.stdout is not None
            while chunk := process.stdout.read(8192):
                buf.extend(chunk)

        thread = Thread(target=pump, daemon=True)
        thread.start()
        return process, thread, buf

    @staticmethod
    def _stop_doa_capture(handle: tuple[subprocess.Popen, Thread, bytearray] | None) -> np.ndarray | None:
        if handle is None:
            return None
        process, thread, buf = handle
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        thread.join(timeout=2)
        usable = len(buf) // 8 * 8  # 4 channel x int16
        if usable == 0:
            return None
        return np.frombuffer(bytes(buf[:usable]), dtype="<i2").reshape(-1, 4).astype(np.float32) / 32768.0

    def _denoise(self, audio: "np.ndarray") -> "np.ndarray":
        if not self.noise_reduce_enabled or self.noise_reducer is None:
            return audio
        try:
            return self.noise_reducer.reduce_noise(
                y=audio, sr=SAMPLE_RATE,
                prop_decrease=self.noise_reduce_prop,
                stationary=self.noise_reduce_stationary,
            )
        except Exception as exc:  # pragma: no cover
            LOG.warning("Denoise gagal, pakai audio asli: %s", exc)
            return audio
