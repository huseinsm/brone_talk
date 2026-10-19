"""Perintah BRONE Talk.

  brone-talk run            jalankan layanan (default, dipakai systemd)
  brone-talk self-test      validasi model dan mesin tanpa mic/speaker
  brone-talk list-devices   daftar perangkat audio
  brone-talk mic-test [N]   uji mic + skor confidence STT untuk N ucapan (hentikan service dulu)
  brone-talk ask "teks"     uji mesin jawaban lewat teks, tanpa mic dan speaker
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import signal
import subprocess
import sys
import time
from threading import Event

import numpy as np
import sounddevice as sd

from brone_talk.app import TalkService, engine_config
from brone_talk.audio.capture import Recorder
from brone_talk.audio.vad import SileroVad
from brone_talk.config import Settings
from brone_talk.engine.answer import AnswerEngine
from brone_talk.stt.transcriber import Transcriber
from brone_talk.telemetry import Telemetry


def list_devices() -> int:
    for index, device in enumerate(sd.query_devices()):
        print(f"{index}: {device['name']} | input={device['max_input_channels']} "
              f"output={device['max_output_channels']}")
    arecord = shutil.which("arecord")
    if arecord:
        print("\nALSA capture devices:")
        subprocess.run([arecord, "-l"], check=False)
    return 0


def self_test(settings: Settings) -> int:
    service: TalkService | None = None
    try:
        service = TalkService(settings)
        service.warmup()
        print("SELF_TEST=ok")
        return 0
    except Exception as exc:
        if service is not None:
            service.telemetry.status("error", str(exc)[:200])
        logging.getLogger("brone-talk").exception("Self-test gagal")
        return 1
    finally:
        if service is not None:
            service.telemetry.close()


def mic_test(settings: Settings, rounds: int) -> int:
    """Uji mic + skor confidence STT dengan pengaturan STT yang sama dengan service.

    Hentikan service dulu supaya mic tidak dipakai dua proses. Hasil ditambahkan ke
    runtime/mic_test.jsonl untuk kalibrasi ambang FAQ.
    """
    telemetry = Telemetry(settings.mqtt)
    runtime = settings.runtime_dir
    runtime.mkdir(parents=True, exist_ok=True)
    vad = SileroVad(settings.models_dir / "silero_vad.onnx")
    recorder = Recorder(settings.audio, telemetry, Event(), vad, runtime, doa_enabled=False)
    transcriber = Transcriber(settings.stt, settings.mai, telemetry)
    transcriber.load()
    out = runtime / "mic_test.jsonl"
    min_mean = settings.engine.faq_stt_min_mean
    min_seg = settings.engine.faq_stt_min_seg
    print(f"Uji mic: {rounds} ucapan. Bicara dengan jarak normal; Ctrl+C untuk berhenti.", flush=True)
    done = 0
    try:
        while done < rounds:
            capture = recorder.record()
            if capture is None:
                print("  (tidak ada ucapan terdeteksi, coba lagi)", flush=True)
                continue
            try:
                text = transcriber.transcribe(capture.path)
            finally:
                capture.path.unlink(missing_ok=True)
            stats = dict(transcriber.last_stats)
            utt_rms = float(np.sqrt(np.mean(np.square(capture.audio)))) if capture.audio is not None else None
            row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "text": text,
                   "duration_s": round(capture.duration_s, 2), "peak_rms": round(capture.peak_rms, 4),
                   "utt_rms": None if utt_rms is None else round(utt_rms, 4),
                   **{k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()}}
            ok = stats.get("stt_mean_prob", 0) >= min_mean and stats.get("stt_min_prob", 0) >= min_seg
            print(f"  [{done + 1}] {text!r}\n      utt_rms={row['utt_rms']} peak_rms={row['peak_rms']} stt_mean={row.get('stt_mean_prob')} "
                  f"stt_min={row.get('stt_min_prob')} -> {'FAQ boleh' if ok else 'FAQ dilewati'}", flush=True)
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            done += 1
    except KeyboardInterrupt:
        pass
    finally:
        telemetry.close()
    print(f"Selesai. Hasil tersimpan di {out}")
    return 0


def ask(settings: Settings, texts: list[str]) -> int:
    engine = AnswerEngine(engine_config(settings, settings.runtime_dir))
    engine.start()
    questions = texts or [line.strip() for line in sys.stdin if line.strip()]
    for question in questions:
        res = engine.answer(question, None)
        engine.reset()
        print(f"[{res['route']}] {res['response']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brone-talk", description="BRONE Talk untuk Intel NUC")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="jalankan layanan percakapan (default)")
    sub.add_parser("self-test", help="validasi model dan mesin tanpa mic/speaker")
    sub.add_parser("list-devices", help="daftar perangkat audio")
    mic = sub.add_parser("mic-test", help="uji mic + confidence STT")
    mic.add_argument("rounds", type=int, nargs="?", default=5)
    ask_cmd = sub.add_parser("ask", help="uji mesin jawaban lewat teks")
    ask_cmd.add_argument("texts", nargs="*", help="satu atau lebih pertanyaan; tanpa argumen, baca baris dari stdin")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    logging.basicConfig(level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    command = args.command or "run"
    if command == "list-devices":
        return list_devices()
    if command == "self-test":
        return self_test(settings)
    if command == "mic-test":
        return mic_test(settings, args.rounds)
    if command == "ask":
        return ask(settings, args.texts)

    service = TalkService(settings)
    signal.signal(signal.SIGTERM, service.stop)
    signal.signal(signal.SIGINT, service.stop)
    try:
        service.run()
    except Exception as exc:
        service.telemetry.status("error", str(exc)[:200])
        logging.getLogger("brone-talk").exception("Service tidak dapat berjalan")
        service.telemetry.close()
        return 1
    return 0
