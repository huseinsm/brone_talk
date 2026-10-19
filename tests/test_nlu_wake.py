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


if __name__ == "__main__":
    unittest.main()
