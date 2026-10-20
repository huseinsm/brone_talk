"""Modul nlu.wake harus sama dengan produksi untuk seluruh masukan fixture nlu_wake.jsonl.

Fixture dibangkitkan lokal (scripts/make_golden.py) dan tidak di-commit. Tanpa fixture, tes dilewati.
"""

import json
import unittest
from pathlib import Path

from brone_talk.nlu import wake

GOLDEN = Path(__file__).resolve().parent / "golden" / "nlu_wake.jsonl"


@unittest.skipUnless(GOLDEN.is_file(), "fixture golden belum dibangkitkan (lihat scripts/make_golden.py)")
class WakeGolden(unittest.TestCase):
    def test_matches_production_output(self):
        rows = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
        mismatches = []
        for r in rows:
            got = {
                "called": bool(wake._NAME_RE.search(r["input"])),
                "collapsed": wake.collapse_repeats(r["input"]),
                "wake_question": wake.wake_question(wake.collapse_repeats(r["input"])),
                "clock": wake.clock_answer(r["input"], now=1_760_000_000.0),
                "stop": wake.matches(wake.STOP_PATTERNS, r["input"]),
            }
            for key, value in got.items():
                if value != r[key]:
                    mismatches.append((r["input"], key, r[key], value))
        self.assertEqual([], mismatches[:5], f"{len(mismatches)} selisih dari {len(rows)} masukan")


class CallText(unittest.TestCase):
    def test_call_starts_at_last_calling_sentence(self):
        self.assertEqual(wake.call_text("Satu, bentar. Oke. BRONE, siapa kamu?"), "BRONE, siapa kamu?")
        self.assertEqual(wake.call_text("Ya, Bey.\nBRONE, di mana gedung UB?"), "BRONE, di mana gedung UB?")
        self.assertEqual(wake.call_text("Brone, UB ada di mana?"), "Brone, UB ada di mana?")

    def test_name_inside_chatter_is_not_a_call(self):
        for text in ("Enggak, BRONE. Saya belum datang ke FIB.\nOh, iya.",
                     "Paling based on BRONE kali. Oke.", "Loh, tuh di BRONE tuh. Oke, sentar aja ke sana."):
            self.assertEqual(wake.call_text(text), "", text)

    def test_name_at_head_or_tail_is_a_call(self):
        for text in ("Brone, UB ada di mana?", "Halo Brone", "halo, BRONE. Jam berapa sekarang?",
                     "UB ada di mana, Brone?", "UB ada di mana Brone", "BRONE FILKOM itu apa"):
            self.assertTrue(wake.addressed(text), text)

    def test_name_mid_sentence_is_not_a_call(self):
        for text in ("kode BRONE talk itu", "Ada 2 BRONE ini sih", "Aku UB, BRONE, Kalian Masih Disini",
                     "Siapa yang membuat Brone tadi?", "saya mau makan siang", ""):
            self.assertFalse(wake.addressed(text), text)


if __name__ == "__main__":
    unittest.main()
