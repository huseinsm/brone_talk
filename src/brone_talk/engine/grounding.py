"""grounding: bagian mesin jawaban v4 (dipindah dari brone_v4.py tanpa perubahan logika)."""

from __future__ import annotations

import re


from brone_talk.engine.util import norm_text

_GROUND_ALLOW = {"bron", "brone", "ub", "universitas", "brawijaya", "maaf", "indonesia", "malang", "jawa", "timur"}

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)

def grounding_problems(answer: str, context: str, question: str) -> list[str]:
    """Daftar angka/nama di jawaban yang tidak ada di konteks maupun pertanyaan."""
    src = f"{context} {question}"
    src_digits = {_digits(m) for m in re.findall(r"\d[\d.,\-/]*\d|\d", src)}
    src_all_digits = _digits(src)
    problems = []
    for m in re.findall(r"\d[\d.,\-/]*\d|\d", answer):
        d = _digits(m)
        if d and d not in src_digits and d not in src_all_digits:
            problems.append(m)
    vocab = set(norm_text(src).split()) | _GROUND_ALLOW
    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        toks = re.findall(r"[A-Za-z][A-Za-z\-']*", sentence)
        for i, tok in enumerate(toks):
            if i == 0 or not tok[0].isupper() or len(tok) < 3:
                continue
            if norm_text(tok) not in vocab and not all(p in vocab for p in norm_text(tok).split()):
                problems.append(tok)
    return problems
