"""Aturan giliran (session.decide) dan state penantian (Session)."""

import unittest

from brone_talk.session import Decision, Session, decide


class DecideTest(unittest.TestCase):
    def test_name_with_question_answers_question(self):
        out = decide("Brone, UB ada di mana?", called=True, awaiting=False)
        self.assertEqual(out.decision, Decision.ANSWER)
        self.assertEqual(out.question, "UB ada di mana?")
        self.assertTrue(out.wake)

    def test_name_only_asks_for_question(self):
        out = decide("Halo Brone", called=True, awaiting=False)
        self.assertEqual(out.decision, Decision.CONFIRM)

    def test_question_after_confirm_is_answered_without_name(self):
        out = decide("berapa mahasiswa di UB", called=False, awaiting=True)
        self.assertEqual(out.decision, Decision.ANSWER)
        self.assertEqual(out.question, "berapa mahasiswa di UB")
        self.assertFalse(out.wake)

    def test_follow_up_without_name_is_ignored(self):
        # setelah jawaban, ucapan tanpa nama dan tanpa "Ya?" tidak dijawab
        out = decide("dan kalau di FILKOM", called=False, awaiting=False)
        self.assertEqual(out.decision, Decision.STANDBY)

    def test_unaddressed_speech_is_standby(self):
        out = decide("saya mau makan siang", called=False, awaiting=False)
        self.assertEqual(out.decision, Decision.STANDBY)

    def test_stop_word_only_stops_while_awaiting(self):
        self.assertEqual(decide("selesai", called=False, awaiting=True).decision, Decision.STOP)
        # tanpa menunggu, kata "selesai" bukan perintah berhenti
        self.assertEqual(decide("selesai", called=False, awaiting=False).decision, Decision.STANDBY)

    def test_brone_filkom_is_a_project_name_not_a_call(self):
        # "BRONE FILKOM" bukan panggilan di awal kalimat (lihat _HEAD_CALL_RE), tetap dijawab sebagai pertanyaan
        out = decide("BRONE FILKOM itu apa", called=True, awaiting=False)
        self.assertEqual(out.decision, Decision.ANSWER)


class SessionTest(unittest.TestCase):
    def test_end_wait_clears_waiting(self):
        s = Session(awaiting_question=True, unclear_said=True, social=True)
        s.end_wait()
        self.assertFalse(s.awaiting_question)
        self.assertFalse(s.social)

    def test_window_expiry(self):
        s = Session()
        s.start_wait(8.0)
        self.assertFalse(s.expired(s.awaiting_since + 7.9, 15.0))
        self.assertTrue(s.expired(s.awaiting_since + 8.1, 15.0))

    def test_unclear_is_said_once_and_never_for_ask_back(self):
        s = Session()
        s.start_wait(15.0)
        self.assertTrue(s.should_say_unclear())
        self.assertFalse(s.should_say_unclear())
        s.start_wait(8.0, social=True, bot_text="Kamu sudah makan?")
        self.assertFalse(s.should_say_unclear())


if __name__ == "__main__":
    unittest.main()
