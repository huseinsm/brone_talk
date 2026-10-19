"""Kunci penanya untuk Brone Talk: sidik suara + arah suara (12 Okt 2026).

Dipindah dari brone_lock.py (versi lama) tanpa perubahan logika; pengaturan dari config.LockConfig.

Saat seseorang memanggil "Brone", Brone mengunci dua ciri penanya itu:

  - sidik suara: embedding speaker CAM++ (3D-Speaker, zh+en "advanced") lewat
    sherpa-onnx. Dipilih dari benchmark di NUC (12 Okt 2026) melawan
    ERes2NetV2, WeSpeaker CAM++ dan WeSpeaker ResNet34: 24 ms per klip 3 s,
    dan satu-satunya yang skor orang-sama vs orang-beda tetap terpisah untuk
    klip 1 s seperti "Halo Brone". ERes2NetV2 lebih baik di klip panjang
    tapi 6x lebih lambat; kedua model WeSpeaker gagal (skor orang beda > sama).
  - arah suara: SRP-PHAT dari 4 mic mentah reSpeaker XVF3800 (node PipeWire
    brone-mic-raw4), diakumulasi sepanjang satu ucapan. Derau ditangani
    dengan bobot per-bin yang sama untuk semua pasangan mic (pita 300-4000 Hz
    + bobot SNR dari derau sebelum ucapan), bukan denoise per channel yang
    merusak selisih fase antar-mic. Arah dalam bingkai array yang belum
    dikalibrasi -- cukup untuk kunci, karena yang dibandingkan hanya arah
    ucapan sekarang vs arah saat dikunci.

Selama terkunci, hanya ucapan yang cocok yang diteruskan ke STT/LLM, dan
penanya boleh bertanya lanjutan tanpa menyebut nama lagi. Kunci lepas sendiri
setelah BRONE_LOCK_TIMEOUT_SECONDS tanpa suara penanya (dihitung dari ucapan
terakhirnya atau akhir jawaban Brone) -- tidak ada perintah "selesai".

Keputusan per ucapan. Ambang diukur 12 Okt 2026 dengan rekaman uji sherpa-onnx
(3 pembicara, profil dari klip 1,2 s): penanya terendah 0,30 (klip 1,5 s + derau
10 dB), orang lain tertinggi 0,39. Reject 0,30 = penanya tak pernah ditolak; zona
0,30-0,45 diserahkan ke arah. Kalibrasi ulang dengan suara pengunjung asli.
  - skor suara < BRONE_LOCK_VOICE_REJECT (0,30)     -> tolak (jelas orang lain)
  - skor suara >= BRONE_LOCK_VOICE_ACCEPT (0,45)    -> terima (arah ikut diperbarui,
                                                       penanya boleh pindah posisi)
  - di antaranya, atau ucapan terlalu pendek untuk sidik suara -> arah yang
    menentukan: terima kalau selisihnya <= BRONE_LOCK_DIR_TOLERANCE_DEG atau
    arahnya tidak terbaca jelas.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from brone_talk.audio.constants import SAMPLE_RATE
from brone_talk.config import LockConfig

LOG = logging.getLogger("brone-talk")


# Geometri XVF3800, sama dengan audio_gaze (config/real_audio_params.yaml):
# 4 kapsul di sudut persegi, diagonal 91 mm. brone-mic-raw4 ch0..ch3 = XVF
# ch2..ch5; pasangan berkorelasi derau terendah (diagonal) = ch0-ch2 dan
# ch1-ch3 (diukur 12 Okt 2026), jadi urutannya memang melingkar.
MIC_RADIUS_M = 0.0455
SPEED_OF_SOUND = 343.0
DOA_FRAME = 1024
DOA_BAND_HZ = (300.0, 4000.0)
DOA_GRID_DEG = np.arange(-180.0, 180.0, 2.0)


def angle_diff_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


class DirectionEstimator:
    """Arah satu ucapan dari 4 mic mentah, SRP-PHAT di domain frekuensi.

    Semua 6 pasangan mic dipakai. Spektrum silang ter-whitening (PHAT) dari
    semua frame ucapan dijumlahkan dulu, lalu dipindai sekali ke grid sudut:
    satu arah per ucapan, jauh lebih stabil daripada arah per frame 64 ms.
    """

    def __init__(self, fs: int = SAMPLE_RATE, frame: int = DOA_FRAME) -> None:
        self.fs = fs
        self.frame = frame
        self.n_fft = 2 * frame
        freqs = np.fft.rfftfreq(self.n_fft, d=1.0 / fs)
        self.band = (freqs >= DOA_BAND_HZ[0]) & (freqs <= DOA_BAND_HZ[1])
        self.freqs = freqs[self.band]
        ang = np.deg2rad(np.arange(4) * 90.0)
        pos = np.stack([MIC_RADIUS_M * np.cos(ang), MIC_RADIUS_M * np.sin(ang)], axis=1)
        self.pairs = [(i, j) for i in range(4) for j in range(i + 1, 4)]
        theta = np.deg2rad(DOA_GRID_DEG)
        unit = np.stack([np.cos(theta), np.sin(theta)], axis=1)  # (grid, 2)
        # Gelombang datar dari theta tiba di mic i pada -(p_i . u)/c.
        arrival = -(unit @ pos.T) / SPEED_OF_SOUND  # (grid, 4)
        tdoa = np.stack([arrival[:, i] - arrival[:, j] for i, j in self.pairs], axis=0)
        # (pairs, grid, bins): fase yang membatalkan TDOA prediksi tiap sudut.
        self.steer = np.exp(2j * np.pi * tdoa[:, :, None] * self.freqs[None, None, :]).astype(np.complex64)

    def _spectra(self, frames: np.ndarray) -> np.ndarray:
        """(n_frames, frame, 4) -> (n_frames, 4, band bins)."""
        spec = np.fft.rfft(frames, n=self.n_fft, axis=1)
        return np.transpose(spec[:, self.band, :], (0, 2, 1))

    def _framed(self, raw: np.ndarray) -> np.ndarray:
        n = raw.shape[0] // self.frame
        return raw[: n * self.frame].reshape(n, self.frame, raw.shape[1])

    def estimate(self, raw: np.ndarray, speech_start: int, speech_end: int) -> tuple[float | None, float]:
        """raw: (samples, 4) float, indeks sampel ucapan [speech_start, speech_end).

        Mengembalikan (arah_derajat, koherensi 0..1); arah None kalau audio
        tidak cukup. Koherensi = skor puncak / skor sumber tunggal sempurna.
        """
        if raw.ndim != 2 or raw.shape[1] != 4:
            return None, 0.0
        speech = self._framed(raw[max(0, speech_start):speech_end])
        if speech.shape[0] == 0:
            return None, 0.0
        spec = self._spectra(speech)
        power = np.mean(np.abs(spec) ** 2, axis=1)  # (frames, bins)
        # Derau dari audio sebelum ucapan (sisakan 0,1 s supaya awal kata tidak ikut).
        noise = self._framed(raw[: max(0, speech_start - self.fs // 10)])
        if noise.shape[0] >= 2:
            noise_psd = np.mean(np.mean(np.abs(self._spectra(noise)) ** 2, axis=1), axis=0)
            weight = np.clip(1.0 - 2.0 * noise_psd[None, :] / np.maximum(power, 1e-20), 0.0, 1.0)
        else:
            weight = np.ones_like(power)

        total = np.zeros((len(self.pairs), spec.shape[2]), dtype=np.complex128)
        for k, (i, j) in enumerate(self.pairs):
            cross = spec[:, i, :] * np.conj(spec[:, j, :])
            total[k] = np.sum(cross / np.maximum(np.abs(cross), 1e-20) * weight, axis=0)
        ideal = len(self.pairs) * float(np.sum(weight))
        if ideal <= 1e-9:
            return None, 0.0
        score = np.real(np.einsum("pb,pgb->g", total, self.steer))
        best = int(np.argmax(score))
        return float(DOA_GRID_DEG[best]), float(np.clip(score[best] / ideal, 0.0, 1.0))


class VoiceEmbedder:
    """Sidik suara CAM++ via sherpa-onnx (vektor ternormalisasi, skor = cosine)."""

    def __init__(self, model: Path, threads: int = 2) -> None:
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model), num_threads=threads, provider="cpu")
        self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def embed(self, audio: np.ndarray) -> np.ndarray:
        stream = self.extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, np.ascontiguousarray(audio, dtype=np.float32))
        stream.input_finished()
        vec = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        return vec / (np.linalg.norm(vec) + 1e-9)


@dataclass
class LockVerdict:
    accepted: bool
    reason: str
    voice_score: float | None = None
    angle_diff: float | None = None
    embedding: np.ndarray | None = None


class SpeakerLock:
    def __init__(self, telemetry, cfg: LockConfig) -> None:
        self.telemetry = telemetry
        self.enabled = cfg.enabled
        self.timeout_s = cfg.timeout_s
        self.voice_accept = cfg.voice_accept
        self.voice_reject = cfg.voice_reject
        self.min_voice_s = cfg.min_voice_s
        self.dir_tolerance = cfg.dir_tolerance_deg
        self.min_doa_conf = cfg.min_doa_confidence
        self.model = cfg.model
        self.embedder: VoiceEmbedder | None = None
        self.active = False
        self.profile: np.ndarray | None = None
        self.profile_weight = 0.0
        self.direction: float | None = None
        self.last_heard = 0.0

    def load(self) -> None:
        if not self.enabled:
            LOG.info("Kunci penanya nonaktif (BRONE_LOCK=0)")
            return
        if not self.model.is_file():
            LOG.warning("Model sidik suara tidak ada (%s): kunci hanya memakai arah", self.model)
            return
        try:
            self.embedder = VoiceEmbedder(self.model)
            self.embedder.embed(np.zeros(SAMPLE_RATE, dtype=np.float32))
            LOG.info("Kunci penanya siap: sidik suara %s, lepas setelah %.0fs tanpa suara",
                     self.model.name, self.timeout_s)
        except Exception as exc:
            self.embedder = None
            LOG.warning("Sidik suara gagal dimuat (%s): kunci hanya memakai arah", exc)

    def _usable_doa(self, capture) -> float | None:
        if capture.doa_deg is None or capture.doa_conf < self.min_doa_conf:
            return None
        return capture.doa_deg

    def _embed(self, capture) -> np.ndarray | None:
        if self.embedder is None or capture.audio is None or capture.duration_s < self.min_voice_s:
            return None
        try:
            return self.embedder.embed(capture.audio)
        except Exception as exc:
            LOG.warning("Sidik suara gagal dihitung: %s", exc)
            return None

    def engage(self, capture, now: float | None = None) -> bool:
        """Kunci ke pemanggil "Brone" pada capture ini. False kalau tidak ada ciri yang bisa dikunci."""
        if not self.enabled:
            return False
        emb = self._embed(capture)
        doa = self._usable_doa(capture)
        if emb is None and doa is None:
            return False
        self.active = True
        self.profile = emb
        self.profile_weight = min(capture.duration_s, 5.0) if emb is not None else 0.0
        self.direction = doa
        self.last_heard = time.monotonic() if now is None else now
        LOG.info("Kunci penanya: suara=%s arah=%s (konf %.2f), lepas setelah %.0fs tanpa suara",
                 "ya" if emb is not None else "tidak",
                 f"{doa:.0f}°" if doa is not None else "-", capture.doa_conf, self.timeout_s)
        self.telemetry.stage("lock", "engaged", voice=emb is not None,
                             direction=None if doa is None else round(doa, 1))
        return True

    def check(self, capture) -> LockVerdict:
        emb = self._embed(capture)
        score = float(emb @ self.profile) if emb is not None and self.profile is not None else None
        doa = self._usable_doa(capture)
        diff = angle_diff_deg(doa, self.direction) if doa is not None and self.direction is not None else None
        if score is not None and score < self.voice_reject:
            return LockVerdict(False, f"suara beda {score:.2f}", score, diff, emb)
        if score is not None and score >= self.voice_accept:
            return LockVerdict(True, f"suara cocok {score:.2f}", score, diff, emb)
        voice = "suara ragu %.2f" % score if score is not None else "suara tak terbaca"
        if diff is None:
            return LockVerdict(True, f"{voice}, arah tak terbaca", score, diff, emb)
        if diff <= self.dir_tolerance:
            return LockVerdict(True, f"{voice}, arah cocok {diff:.0f}°", score, diff, emb)
        return LockVerdict(False, f"{voice}, arah beda {diff:.0f}°", score, diff, emb)

    def accept(self, capture, verdict: LockVerdict | None, now: float | None = None) -> None:
        """Ucapan penanya diterima: perkuat profil suara dan ikuti arahnya."""
        emb = verdict.embedding if verdict is not None else None
        if emb is not None:
            w = min(capture.duration_s, 5.0)
            if self.profile is None:
                self.profile, self.profile_weight = emb, w
            else:
                merged = self.profile * self.profile_weight + emb * w
                self.profile = merged / (np.linalg.norm(merged) + 1e-9)
                self.profile_weight = min(self.profile_weight + w, 30.0)
        doa = self._usable_doa(capture)
        if doa is not None:
            if self.direction is None:
                self.direction = doa
            else:
                # Rata-rata sudut: geser setengah jalan ke arah baru.
                a, b = np.deg2rad(self.direction), np.deg2rad(doa)
                self.direction = float(np.rad2deg(np.arctan2(np.sin(a) + np.sin(b), np.cos(a) + np.cos(b))))
        self.touch(now)

    def touch(self, now: float | None = None) -> None:
        if self.active:
            self.last_heard = time.monotonic() if now is None else now

    def expire_if_idle(self, now: float | None = None) -> bool:
        """Lepas kunci kalau penanya tidak terdengar selama timeout. True kalau baru dilepas."""
        if not self.active:
            return False
        now = time.monotonic() if now is None else now
        if now - self.last_heard < self.timeout_s:
            return False
        LOG.info("Kunci penanya dilepas: tidak ada suara penanya %.0fs", now - self.last_heard)
        self.telemetry.stage("lock", "released", idle_s=round(now - self.last_heard, 1))
        self.active = False
        self.profile = None
        self.profile_weight = 0.0
        self.direction = None
        return True
