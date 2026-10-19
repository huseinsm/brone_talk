"""Endpointing harus berperilaku seperti dua loop lama (sounddevice dan ALSA) untuk VAD terskrip.

Nilai yang diharapkan dihitung tangan dari logika versi lama (preroll 8 jendela, berhenti setelah
silence_limit jendela senyap berturut-turut, batas window_limit). Jendela = 512 sampel.
"""

import unittest

import numpy as np

from brone_talk.audio.constants import VAD_WINDOW
from brone_talk.audio.endpointing import CaptureLost, Endpointer, StopCapture


class ScriptedVad:
    def __init__(self, probs):
        self._probs = list(probs)
        self._i = 0

    def reset(self):
        self._i = 0

    def probability(self, samples):
        p = self._probs[self._i]
        self._i += 1
        return p


class FakeTelemetry:
    def __init__(self):
        self.events = []

    def vad(self, status, rms_float):
        self.events.append(("vad", status))

    def stage(self, stage, state="", **fields):
        self.events.append(("stage", stage, state))


def blocks(n):
    for _ in range(n):
        yield np.full(VAD_WINDOW, 0.01, dtype=np.float32)


class EndpointerTest(unittest.TestCase):
    def run_endpointer(self, probs, silence_limit=3, window_limit=20):
        vad = ScriptedVad(probs)
        ep = Endpointer(vad, FakeTelemetry(), threshold=0.5, silence_limit=silence_limit, window_limit=window_limit)
        return ep.run(blocks(len(probs)))

    def test_ends_after_silence_limit(self):
        # 0,1 senyap (preroll); 2 mulai ucapan; 3 ucapan; 4-6 senyap -> berhenti di 6
        utt = self.run_endpointer([0.1, 0.1, 0.9, 0.9, 0.1, 0.1, 0.1])
        self.assertEqual(len(utt.frames), 7)  # preroll 0-2, ucapan 3, senyap 4-6 (ikut terekam)
        self.assertEqual(utt.speech_start, 0)
        self.assertEqual(utt.speech_end, 7 * VAD_WINDOW)

    def test_silence_counter_resets_on_speech(self):
        # senyap 2 kali lalu ucapan lagi: tidak boleh berhenti di tengah
        utt = self.run_endpointer([0.9, 0.1, 0.1, 0.9, 0.1, 0.1, 0.1])
        self.assertEqual(len(utt.frames), 7)
        self.assertEqual(utt.speech_end, 7 * VAD_WINDOW)

    def test_preroll_is_capped_at_eight_windows(self):
        # 10 jendela senyap lalu ucapan di indeks 10: preroll hanya 8 jendela terakhir
        probs = [0.1] * 10 + [0.9, 0.1, 0.1, 0.1]
        utt = self.run_endpointer(probs, silence_limit=3)
        self.assertEqual(utt.speech_start, (10 - 8 + 1) * VAD_WINDOW)
        # preroll 8 jendela sudah memuat jendela ucapan pertama, lalu 3 jendela senyap (idx 11-13)
        self.assertEqual(len(utt.frames), 8 + 3)

    def test_no_speech_returns_empty_frames_at_window_limit(self):
        utt = self.run_endpointer([0.1] * 5, window_limit=5)
        self.assertEqual(utt.frames, [])
        self.assertEqual(utt.speech_end, 5 * VAD_WINDOW)

    def test_window_limit_caps_endless_source(self):
        vad = ScriptedVad([0.9] * 100)
        ep = Endpointer(vad, FakeTelemetry(), threshold=0.5, silence_limit=3, window_limit=4)
        utt = ep.run(blocks(100))
        self.assertEqual(len(utt.frames), 4)
        self.assertEqual(utt.speech_end, 4 * VAD_WINDOW)

    def test_source_is_closed_when_run_finishes(self):
        closed = []

        def source():
            try:
                yield from blocks(10)
            finally:
                closed.append(True)

        ep = Endpointer(ScriptedVad([0.9, 0.1, 0.1, 0.1] + [0.1] * 6), FakeTelemetry(),
                        threshold=0.5, silence_limit=3, window_limit=20)
        ep.run(source())
        self.assertEqual(closed, [True])

    def test_stop_and_lost_propagate(self):
        def stopping():
            yield np.zeros(VAD_WINDOW, dtype=np.float32)
            raise StopCapture()

        def lost():
            yield np.zeros(VAD_WINDOW, dtype=np.float32)
            raise CaptureLost()

        ep = Endpointer(ScriptedVad([0.9, 0.9]), FakeTelemetry(), threshold=0.5, silence_limit=3, window_limit=20)
        with self.assertRaises(StopCapture):
            ep.run(stopping())
        ep = Endpointer(ScriptedVad([0.9, 0.9]), FakeTelemetry(), threshold=0.5, silence_limit=3, window_limit=20)
        with self.assertRaises(CaptureLost):
            ep.run(lost())


if __name__ == "__main__":
    unittest.main()
