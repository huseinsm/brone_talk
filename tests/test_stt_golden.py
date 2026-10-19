"""Koreksi dan filter STT harus sama dengan produksi untuk seluruh fixture stt_filters.jsonl.

Catatan: fixture dibangkitkan tanpa stats/vocab, sehingga garbage_reason hampir selalu kosong.
Tes ini tetap menjaga parity koreksi dan strip prompt, tetapi belum membuktikan filter sampah.
Fixture tidak di-commit; tanpa fixture, tes dilewati.
"""

import json
import unittest
from pathlib import Path

from brone_talk.stt import corrections, filters

GOLDEN = Path(__file__).resolve().parent / "golden" / "stt_filters.jsonl"


@unittest.skipUnless(GOLDEN.is_file(), "fixture golden belum dibangkitkan (lihat scripts/make_golden.py)")
class SttGolden(unittest.TestCase):
    def test_matches_production_output(self):
        rows = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
        mismatches = []
        for r in rows:
            got = {
                "stt_fix": corrections._stt_fix(r["input"]),
                "mai_fix": corrections._mai_fix(r["input"]),
                "garbage_reason": filters.stt_garbage_reason(r["input"]),
                "strip_prompt": filters.stt_strip_prompt_sentence(r["input"]),
            }
            for key, value in got.items():
                if value != r[key]:
                    mismatches.append((r["input"], key, r[key], value))
        self.assertEqual([], mismatches[:5], f"{len(mismatches)} selisih dari {len(rows)} masukan")


if __name__ == "__main__":
    unittest.main()
