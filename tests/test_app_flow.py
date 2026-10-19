"""Alur giliran (TalkService.turn) dengan komponen palsu: rekaman, STT, speaker, kunci, dan mesin.

Tujuannya menguji wiring keputusan (session.decide) dengan efek sampingnya, tanpa mic, speaker,
atau server model. Aturan yang diuji sama dengan loop produksi brone_talk.py v4.
"""

import tempfile
import unittest
from pathlib import Path

from brone_talk import messages
from brone_talk.app import TalkService
from brone_talk.session import Session


class FakeCapture:
    def __init__(self, path):
        self.path = path
        self.duration_s = 1.0


class FakeRecorder:
    def __init__(self, path):
        self.path = path
        self.queue = []

    def record(self):
        return self.queue.pop(0) if self.queue else None


class FakeTranscriber:
    def __init__(self):
        self.queue = []
        self.last_stats = {}
        self.vocab = frozenset()
        self.prompt_terms = frozenset()
        self.filter_enabled = False  # filter sampah diuji terpisah (tests/test_stt_golden.py)

    def transcribe(self, path):
        return self.queue.pop(0)


class FakeSpeaker:
    def __init__(self):
        self.said = []

    def say(self, text, expression):
        self.said.append((text, expression))
        return True


class FakeVerdict:
    def __init__(self, accepted, reason):
        self.accepted = accepted
        self.reason = reason


class FakeLock:
    def __init__(self):
        self.active = False
        self.engaged = 0
        self.touched = 0

    def engage(self, capture):
        self.engaged += 1
        self.active = True
        return True

    def touch(self, now=None):
        self.touched += 1

    def check(self, capture):
        return FakeVerdict(accepted=True, reason="tes")

    def accept(self, capture, verdict):
        pass

    def expire_if_idle(self, now=None):
        return False


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.resets = 0

    def answer(self, text, stt):
        self.calls.append(text)
        return {"route": "faq", "response": f"JAWAB {text}", "expression": "happy", "meta": {}}

    def reset(self):
        self.resets += 1


class FakeTelemetry:
    def __init__(self):
        self.stages = []

    def stage(self, stage, state="", **fields):
        self.stages.append((stage, state))

    def status(self, status, detail=""):
        pass

    def vad(self, status, rms):
        pass

    def expression(self, expression, duration=None):
        pass


class TurnFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.svc = object.__new__(TalkService)  # lewati __init__ (butuh perangkat keras)
        self.svc.telemetry = FakeTelemetry()
        self.svc.recorder = FakeRecorder(self.dir)
        self.svc.transcriber = FakeTranscriber()
        self.svc.speaker = FakeSpeaker()
        self.svc.lock = FakeLock()
        self.svc.engine = FakeEngine()
        self.svc.session = Session()
        self.svc.runtime_dir = self.dir

    def tearDown(self):
        self._tmp.cleanup()

    def hear(self, *texts):
        """Dengarkan ucapan berurutan; tiap ucapan = satu giliran."""
        for text in texts:
            wav = self.dir / f"in-{len(self.svc.recorder.queue)}-{len(text)}.wav"
            wav.write_bytes(b"")
            self.svc.recorder.queue.append(FakeCapture(wav))
            self.svc.transcriber.queue.append(text)
            self.svc.turn()

    def said(self):
        return [text for text, _ in self.svc.speaker.said]

    def test_name_with_question_is_answered_directly(self):
        self.hear("Brone, UB ada di mana?")
        self.assertEqual(self.said(), ["JAWAB UB ada di mana?"])
        self.assertEqual(self.svc.engine.calls, ["UB ada di mana?"])
        self.assertFalse(self.svc.session.awaiting_question)

    def test_name_only_confirms_then_next_utterance_is_answered(self):
        self.hear("Halo Brone", "berapa mahasiswa di UB")
        self.assertEqual(self.said(), [messages.SAY_CONFIRM, "JAWAB berapa mahasiswa di UB"])
        self.assertFalse(self.svc.session.awaiting_question)

    def test_unaddressed_speech_is_ignored(self):
        self.hear("saya mau makan siang")
        self.assertEqual(self.said(), [])
        self.assertEqual(self.svc.engine.calls, [])

    def test_stop_word_while_awaiting_says_standby(self):
        self.hear("Halo Brone", "selesai")
        self.assertEqual(self.said(), [messages.SAY_CONFIRM, messages.SAY_STOP])
        self.assertFalse(self.svc.session.awaiting_question)

    def test_clock_question_skips_engine(self):
        self.hear("Brone, jam berapa sekarang?")
        self.assertEqual(self.svc.engine.calls, [])
        self.assertTrue(self.said()[0].startswith("Sekarang pukul "))

    def test_lock_engages_on_wake_but_follow_up_without_name_is_ignored(self):
        self.hear("Brone, UB ada di mana?", "dan kalau FILKOM")
        self.assertEqual(self.svc.lock.engaged, 1)
        self.assertEqual(self.svc.engine.calls, ["UB ada di mana?"])

    def test_new_wake_clears_conversation_once(self):
        self.hear("Brone, UB ada di mana?")
        self.assertEqual(self.svc.engine.resets, 1)

    def test_unclear_audio_is_said_once_while_awaiting(self):
        # derau yang lolos ke jalur "tidak jelas": filter diaktifkan untuk giliran ini saja
        self.svc.transcriber.filter_enabled = True
        import brone_talk.app as app_mod

        original = app_mod.stt_garbage_reason
        app_mod.stt_garbage_reason = lambda text, *a, **k: "derau" if "tidak jelas" in text or "derau" in text else ""
        try:
            self.hear("Halo Brone", "kata kata tidak jelas sama sekali", "lagi derau tiga kata")
        finally:
            app_mod.stt_garbage_reason = original
        unclear = [t for t in self.said() if t == messages.MSG_UNCLEAR_AUDIO]
        self.assertEqual(len(unclear), 1)


if __name__ == "__main__":
    unittest.main()
