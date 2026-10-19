"""Aturan giliran (session.decide) harus sama dengan loop produksi brone_talk.py v4."""

import unittest

from brone_talk.session import Decision, Session, decide


class DecideTest(unittest.TestCase):
    def test_name_with_question_answers_question(self):
        out = decide("Brone, UB ada di mana?", called=True, locked=False, awaiting=False)
        self.assertEqual(out.decision, Decision.ANSWER)
        self.assertEqual(out.question, "UB ada di mana?")
        self.assertTrue(out.wake)

    def test_name_only_asks_for_question(self):
        out = decide("Halo Brone", called=True, locked=False, awaiting=False)
        self.assertEqual(out.decision, Decision.CONFIRM)

    def test_question_after_confirm_is_answered_without_name(self):
        out = decide("berapa mahasiswa di UB", called=False, locked=False, awaiting=True)
        self.assertEqual(out.decision, Decision.ANSWER)
        self.assertEqual(out.question, "berapa mahasiswa di UB")
        self.assertFalse(out.wake)

    def test_follow_up_while_locked_without_name_is_ignored(self):
        # kunci penanya aktif tidak cukup: tanpa nama dan tanpa "Ya?", diam
        out = decide("dan kalau di FILKOM", called=False, locked=True, awaiting=False)
        self.assertEqual(out.decision, Decision.STANDBY)

    def test_unaddressed_speech_is_standby(self):
        out = decide("saya mau makan siang", called=False, locked=False, awaiting=False)
        self.assertEqual(out.decision, Decision.STANDBY)

    def test_stop_word_only_stops_while_awaiting(self):
        self.assertEqual(decide("selesai", called=False, locked=False, awaiting=True).decision, Decision.STOP)
        # tanpa menunggu, kata "selesai" bukan perintah berhenti
        self.assertEqual(decide("selesai", called=False, locked=False, awaiting=False).decision, Decision.STANDBY)

    def test_brone_filkom_is_a_project_name_not_a_call(self):
        # "BRONE FILKOM" bukan panggilan di awal kalimat (lihat _HEAD_CALL_RE), tetap dijawab sebagai pertanyaan
        out = decide("BRONE FILKOM itu apa", called=True, locked=False, awaiting=False)
        self.assertEqual(out.decision, Decision.ANSWER)


class SessionTest(unittest.TestCase):
    def test_expire_clears_waiting(self):
        s = Session(awaiting_question=True, unclear_said=True)
        s.expire()
        self.assertFalse(s.awaiting_question)


if __name__ == "__main__":
    unittest.main()
