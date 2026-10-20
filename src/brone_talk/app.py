"""Layanan BRONE Talk: wiring komponen, warmup, dan loop percakapan.

Urutan per ucapan (sama dengan brone_talk.py v4):
  rekam -> kunci penanya -> STT -> filter sampah -> keputusan (session.decide)
  -> jawaban jam (tanpa LLM) atau mesin jawaban -> TTS.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Event
from typing import Any

from brone_talk import messages
from brone_talk.audio.capture import Recorder
from brone_talk.audio.vad import SileroVad
from brone_talk.config import Settings
from brone_talk.engine.answer import AnswerEngine, EngineConfig
from brone_talk.nlu.wake import call_text, clock_answer, collapse_repeats, _NAME_RE
from brone_talk.session import Decision, Session, decide
from brone_talk.stt.filters import stt_garbage_reason, stt_strip_prompt_sentence
from brone_talk.stt.transcriber import Transcriber
from brone_talk.telemetry import Telemetry
from brone_talk.text import _stt_tokens
from brone_talk.tts.speaker import Speaker

LOG = logging.getLogger("brone-talk")
ENGINE_LABEL = "faq+rag"
# rute yang tidak diucapkan untuk tanggapan di jendela tanya-balik (biasanya obrolan tim)
_SILENT_ON_REPLY = ("tolak", "tidak_dimengerti", "gagal", "gerakan")


def engine_config(settings: Settings, runtime_dir: Path) -> EngineConfig:
    e = settings.engine
    return EngineConfig(
        kb_dir=settings.kb_dir,
        runtime_dir=runtime_dir,
        embed_url=e.embed_url,
        rerank_url=e.rerank_url,
        local_url=e.local_url,
        local_model=e.local_model,
        cloud_url=e.cloud_url,
        cloud_model=e.cloud_model,
        cloud_key=e.cloud_key,
        mode=e.mode,
        cloud_timeout_s=e.cloud_timeout_s,
        local_timeout_s=e.local_timeout_s,
        max_tokens=e.max_tokens,
        faq_min_sim=e.faq_min_sim,
        faq_min_margin=e.faq_min_margin,
        stt_min_mean=e.faq_stt_min_mean,
        stt_min_seg=e.faq_stt_min_seg,
        faq_low_stt_min_sim=e.faq_low_stt_min_sim,
        rerank_min=e.rerank_min,
        rerank_top=e.rerank_top,
        rerank_doc_chars=e.rerank_doc_chars,
        rerank_timeout_s=e.rerank_timeout_s,
        context_chars=e.context_chars,
        context_chunks=e.context_chunks,
        grounding=e.grounding,
        chat_llm=e.chat_llm,
        startup_wait_s=e.server_wait_s,
    )


class TalkService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._check_assets()
        self.runtime_dir = settings.runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.stop_event = Event()
        self.telemetry = Telemetry(settings.mqtt)
        vad = SileroVad(settings.models_dir / "silero_vad.onnx")
        self.recorder = Recorder(settings.audio, self.telemetry, self.stop_event, vad,
                                 self.runtime_dir, doa_enabled=False)
        self.transcriber = Transcriber(settings.stt, settings.mai, self.telemetry)
        self.speaker = Speaker(settings.tts, settings.audio, self.telemetry, self.runtime_dir)
        self.engine = AnswerEngine(engine_config(settings, self.runtime_dir))
        self.session = Session()

    def _check_assets(self) -> None:
        required = [
            self.settings.models_dir / "silero_vad.onnx",
            self.settings.tts.voice_model,
            self.settings.tts.voice_config,
        ]
        missing = [str(p) for p in required if not Path(p).is_file()]
        if missing:
            raise RuntimeError(f"Aset model wajib belum ada: {', '.join(missing)}")

    # -- jawaban (pembungkus mesin v4 yang juga mengirim telemetri LLM) ------------
    def _answer(self, text: str, replying_to: str = "") -> dict[str, Any]:
        self.telemetry.stage("llm", "start", model=ENGINE_LABEL, backend="v4")
        result = self.engine.answer(text, self.transcriber.last_stats, replying_to=replying_to)
        meta = result.get("meta", {})
        self.telemetry.stage("llm", "done", ms=meta.get("total_ms"), route=result.get("route"),
                             backend=(meta.get("llm") or {}).get("backend", ""), model=ENGINE_LABEL)
        return result

    def _clear_conversation(self) -> None:
        self.engine.reset()

    def _expire_await(self, now: float | None = None) -> None:
        """Jendela "Ya?" habis: pertanyaan berikutnya harus menyebut nama lagi."""
        now = time.monotonic() if now is None else now
        if self.session.awaiting_question and now - self.session.awaiting_since > (self.session.await_window or self.settings.await_s):
            self.session.expire()
            self.telemetry.stage("idle", "standby", reason="await_timeout")

    # -- warmup -------------------------------------------------------------------
    def warmup(self) -> None:
        started = time.perf_counter()
        self.telemetry.status("warming", "memuat VAD")
        self.recorder.vad.reset()
        self.telemetry.status("warming", "memuat sidik suara")
        self.telemetry.status("warming", "memuat faster-whisper")
        self.transcriber.load()
        self.telemetry.status("warming", f"memvalidasi TTS ({self.speaker.backend})")
        path, _ms, _duration = self.speaker.synthesize("Halo.")
        path.unlink(missing_ok=True)
        self.telemetry.status("warming", "memuat FAQ dan RAG v4 (llama.cpp)")
        self.engine.start()
        if self.settings.warmup_llm:
            self.telemetry.status("warming", "memvalidasi v4")
            # "Halo Bron" menyentuh FAQ sapaan (tanpa LLM). prev_question tidak di-reset, sama seperti produksi.
            self.engine.answer("Halo Bron", None)
        elapsed = time.perf_counter() - started
        self.telemetry.status("ready", f"{elapsed:.1f}s")
        self.telemetry.stage("idle", "standby")
        self.telemetry.expression("idle")
        LOG.info("Warmup selesai dalam %.1fs", elapsed)

    def stop(self, _signal: int | None = None, _frame: Any = None) -> None:
        self.stop_event.set()

    # -- loop utama ----------------------------------------------------------------
    def run(self) -> None:
        self.warmup()
        LOG.info("BRONE talk siap, menunggu kata 'Brone'")
        while not self.stop_event.is_set():
            self.turn()
        self.telemetry.stage("idle", "stopped")
        self.telemetry.expression("idle")
        self.telemetry.close()
        LOG.info("BRONE talk berhenti")

    def turn(self) -> None:
        """Satu giliran: satu ucapan dari mic sampai jawaban diucapkan (atau diabaikan)."""
        try:
            capture = self.recorder.record()
        except Exception as exc:
            self.telemetry.stage("error", "audio", detail=str(exc)[:200])
            LOG.exception("Perekaman gagal")
            time.sleep(1)
            return
        if capture is None:
            self._expire_await()
            return
        self._expire_await(time.monotonic() - capture.duration_s)
        try:
            text = self.transcriber.transcribe(capture.path)
        except Exception as exc:
            self.telemetry.stage("error", "stt", detail=str(exc)[:200])
            LOG.exception("STT gagal")
            return
        finally:
            capture.path.unlink(missing_ok=True)
        if not text:
            return

        if _NAME_RE.search(text):
            text = collapse_repeats(text)
        # nama di awal kalimat atau akhir ucapan; di tengah kalimat bukan panggilan
        called_part = call_text(text)
        called = bool(called_part)
        if called:
            text = called_part
        stt = self.transcriber
        reason = stt_garbage_reason(text, stt.last_stats, stt.vocab, stt.prompt_terms) if stt.filter_enabled else ""
        if reason:
            LOG.info("STT diabaikan (%s): %r", reason, text[:120])
            self.telemetry.stage("stt", "ignored", reason=reason, text=text[:100])
            # sedang menunggu pertanyaan dan ucapannya tidak jelas: minta diulang, sekali per giliran
            if (self.session.awaiting_question and not self.session.social and not self.session.unclear_said
                    and len(_stt_tokens(text)) >= 3):
                self.session.unclear_said = True
                self.speaker.say(messages.MSG_UNCLEAR_AUDIO, "confused")
            return
        cleaned = stt_strip_prompt_sentence(text) if stt.filter_enabled else text
        if cleaned != text:
            if not cleaned:
                LOG.info("STT diabaikan (gema kalimat prompt): %r", text[:120])
                self.telemetry.stage("stt", "ignored", reason="gema kalimat prompt", text=text[:100])
                return
            LOG.info("Gema kalimat prompt dibuang: %r -> %r", text[:120], cleaned[:120])
            text = cleaned
            called_part = call_text(text)
            called = bool(called_part)
            if called:
                text = called_part

        awaiting = self.session.awaiting_question
        outcome = decide(text, called=called, awaiting=awaiting)

        if outcome.decision is Decision.STOP:
            self.speaker.say(messages.SAY_STOP, "neutral")
            self.session.awaiting_question = False
            self.telemetry.stage("idle", "standby", reason="voice_stop")
            return
        if outcome.decision is Decision.STANDBY:
            self.telemetry.stage("idle", "standby", heard=text[:100])
            return

        if called:
            # setiap ucapan yang memanggil Bron (nama di awal/akhir) dijawab; giliran baru mengosongkan riwayat
            self._clear_conversation()

        if outcome.decision is Decision.CONFIRM:
            if self.settings.await_s <= 0:
                # tanpa jendela susulan: ucapan tanpa nama tidak pernah dijawab (20 Okt 2026)
                self.speaker.say(messages.SAY_CALL_HINT, "happy")
                self.telemetry.stage("idle", "standby", wake_text=text[:100])
                return
            self.speaker.say(messages.SAY_CONFIRM, "happy")
            self.session.start_wait(self.settings.await_s)
            self.telemetry.stage("idle", "awaiting_question", wake_text=text[:100])
            return

        if outcome.wake:
            self.telemetry.stage("idle", "answering", wake_text=outcome.question[:100])
        else:
            self.telemetry.stage("idle", "answering", follow_up_text=text[:100])
        question = outcome.question
        social_reply = not outcome.wake and self.session.social
        replying_to = self.session.bot_text if social_reply else ""
        self.session.awaiting_question = False
        self.session.social = False

        clock = clock_answer(question)
        if clock:
            LOG.info("Jawaban jam sistem: %r -> %r", question[:80], clock)
            self.speaker.say(clock, "happy")
            self.telemetry.stage("idle", "standby")
            return

        try:
            answer = self._answer(question, replying_to)
        except Exception:
            self.telemetry.status("error", "v4 tidak tersedia")
            self.speaker.say(messages.SAY_SERVICE_ERROR, "confused")
            LOG.exception("Mesin jawaban gagal")
            self.telemetry.stage("idle", "standby")
            return

        route = str(answer.get("route", ""))
        if route == "abaikan" or (social_reply and route.startswith(_SILENT_ON_REPLY)):
            # ucapan bukan untuk Bron, atau obrolan tim di jendela tanya-balik: diam, jangan "Maaf, ..."
            LOG.info("Tidak dijawab (%s): %r", route, question[:80])
            self.telemetry.stage("idle", "standby", reason=route)
            return
        response = str(answer.get("response", "")).strip()
        expression = answer.get("expression", "neutral")
        if not response:
            response = messages.SAY_FALLBACK
            expression = "confused"
        self.speaker.say(response, expression)
        if answer.get("ask_back") and self.settings.social_await_s > 0:
            self.session.start_wait(self.settings.social_await_s, social=True, bot_text=response)
            self.telemetry.stage("idle", "awaiting_question", reason="tanya_balik")
            return
        self.telemetry.stage("idle", "standby")
