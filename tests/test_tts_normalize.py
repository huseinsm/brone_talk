"""Modul baru harus menghasilkan keluaran yang sama dengan clean_for_speech versi produksi.

Fixture (tests/golden/tts_normalize.jsonl) dibangkitkan oleh scripts/make_golden.py dan
tidak di-commit karena berisi data percakapan. Tanpa fixture, tes dilewati.
"""

import json
import unittest
from pathlib import Path

from brone_talk.tts.normalize import clean_for_speech

GOLDEN = Path(__file__).resolve().parent / "golden" / "tts_normalize.jsonl"


@unittest.skipUnless(GOLDEN.is_file(), "fixture golden belum dibangkitkan (lihat scripts/make_golden.py)")
class CleanForSpeechGolden(unittest.TestCase):
    def test_matches_production_output(self):
        rows = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreater(len(rows), 0)
        mismatches = [
            (r["input"], r["expected"], clean_for_speech(r["input"]))
            for r in rows
            if clean_for_speech(r["input"]) != r["expected"]
        ]
        self.assertEqual([], mismatches[:5], f"{len(mismatches)} dari {len(rows)} berbeda")


if __name__ == "__main__":
    unittest.main()
