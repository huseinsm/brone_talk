"""Wake word, pengenalan panggilan, dan jawaban jam untuk BRONE.

Dipindah dari brone_talk.py (v4) tanpa perubahan logika. Semua fungsi di sini murni.
Bentuk variasi nama ("Brone", "Bron", salah-dengar STT) hanya didefinisikan sekali di sini.
"""

from __future__ import annotations

import re
import time

from brone_talk.names import _BRONE_VARIANTS
from brone_talk.text import _stt_tokens




_NAME = _BRONE_VARIANTS

_NAME_RE = re.compile(rf"\b{_NAME}\b", re.I)

_CALL_WORDS = ("halo", "hallo", "hai", "hei", "hey", "hi", "hello", "eh", "oh", "ya", "iya",
               "selamat", "pagi", "siang", "sore", "malam", "permisi", "tolong")

_CALL = "|".join(_CALL_WORDS)

_HEAD_CALL_RE = re.compile(rf"^[\W_]*(?:(?:{_CALL})\b[\W_]*)*{_NAME}\b(?!\s*filkom)[\s,.!?-]*", re.I)

_TAIL_CALL_RE = re.compile(rf"\s*,\s*{_NAME}\s*([.!?]*)\s*$", re.I)

_HEAD_NAME_RE = re.compile(rf"^[\W_]*(?:(?:{_CALL})\b[\W_]*)*{_NAME}\b", re.I)

_TAIL_NAME_RE = re.compile(rf"\b{_NAME}[\W_]*$", re.I)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\s*\n\s*")

def call_text(text: str) -> str:
    """Bagian ucapan yang memanggil Bron, atau "" bila nama tidak dipakai sebagai panggilan.

    Panggilan = nama di awal kalimat (boleh didahului sapaan) atau di akhir ucapan:
    "Brone, UB ada di mana?", "UB ada di mana, Brone?" -> utuh;
    "Oke. Satu, dua. BRONE, siapa kamu?" -> "BRONE, siapa kamu?" (STT menggabung beberapa
    kalimat dalam satu klip; yang dijawab mulai dari panggilan terakhir);
    "kode BRONE talk itu", "Enggak, BRONE. Saya belum ke FIB. Oh, iya." -> "".
    20 Okt 2026: tim menyebut "BRONE" di tengah obrolan kerja dan robot menjawab penolakan
    18 kali sejak 19 Okt; sejak itu nama di tengah kalimat bukan panggilan.
    """
    text = (text or "").strip()
    pieces = [p for p in _SENTENCE_SPLIT_RE.split(text) if p]
    for i in range(len(pieces) - 1, -1, -1):
        if _HEAD_NAME_RE.match(pieces[i]):
            return " ".join(pieces[i:]) if i else text
    return text if _TAIL_NAME_RE.search(text) else ""

def addressed(text: str) -> bool:
    return bool(call_text(text))

def wake_question(text: str) -> str:
    """Pertanyaan dari ucapan yang memanggil Bron (lihat call_text untuk posisi nama).

    "Brone, UB ada di mana?" dan "UB ada di mana, Brone?" -> "UB ada di mana?";
    "Siapa yang membuat Brone?" -> utuh (nama di tengah kalimat bagian dari pertanyaan).
    Kosong bila nama tidak disebut, atau ucapan hanya panggilan tanpa isi
    (< 2 kata selain nama/sapaan, mis. "Brone" atau "Halo Brone").
    """
    if not _NAME_RE.search(text or ""):
        return ""
    question = _HEAD_CALL_RE.sub("", text.strip(), count=1)
    question = _TAIL_CALL_RE.sub(r"\1", question).strip(" ,.!-")
    content = [w for w in re.findall(r"\w+", question.lower())
               if w not in _CALL_WORDS and not _NAME_RE.fullmatch(w)]
    return question if len(content) >= 2 else ""

def collapse_repeats(text: str) -> str:
    """Buang panggilan yang diulang: "Halo, BRONE. Halo, BRONE. Halo, BRONE." -> "Halo, BRONE.",
    "Brone, Brone, UB di mana?" -> "Brone, UB di mana?".

    Orang yang tidak langsung dijawab memanggil Bron berkali-kali; tanpa ini klipnya
    dibuang stt_garbage_reason sebagai "frasa berulang" (journal 6 Okt 2026).

    13 Okt 2026: hanya ulangan yang memuat nama Bron yang diringkas. Dulu semua bagian
    berkoma ikut diringkas, jadi halusinasi derau "BRONE, Rector, Rector, Rector," menjadi
    "BRONE, Rector," dan "…AGITO, FUK, FUK, FUK" lolos filter lalu dijawab.
    """
    parts: list[str] = []
    for part in re.split(r"(?<=[.!?,])\s+", text.strip()):
        if parts and _stt_tokens(part) == _stt_tokens(parts[-1]) and _NAME_RE.search(part):
            continue
        parts.append(part)
    keys = [_stt_tokens(p) for p in parts]
    for period in range(1, len(parts) // 2 + 1):
        if (all(keys[i] == keys[i % period] for i in range(len(keys)))
                and _NAME_RE.search(" ".join(parts[:period]))):
            return " ".join(parts[:period])
    return " ".join(parts)

_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

_BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
          "September", "Oktober", "November", "Desember"]

_CLOCK_FILLER = {"bron", "brone", "brun", "broni", "bronny", "brony", "berone", "beran", "beron", "done", "halo", "hallo", "hai", "hello", "hi",
                 "baiklah", "baik", "ya", "sekarang", "dong", "kah", "tolong", "sih", "nih", "oke", "coba",
                 "kasih", "tau", "tahu", "boleh", "saya", "aku", "mau", "tanya"}

_CLOCK_TIME = re.compile(r"(jam|pukul) berapa|what time is it")

_CLOCK_DAY = re.compile(r"(hari ini )?hari (ini )?apa( hari ini| ini)?")

_CLOCK_DATE = re.compile(r"(hari ini )?tanggal (berapa|hari ini)( hari ini)?")

def clock_answer(text: str, now: float | None = None) -> str:
    """Jawaban jam/hari/tanggal dari jam sistem, atau "" bila bukan pertanyaan waktu murni.

    Model 0.8B tidak punya jam dan mengarang ("Jam 12:00 WIB", "hari Jumat" pada hari Minggu).
    Hanya dipakai bila seluruh kalimat (tanpa sapaan/pengisi) adalah pertanyaan waktu, supaya
    "perpustakaan buka jam berapa?" tetap ke RAG.
    """
    words = re.findall(r"[a-z]+", (text or "").lower())
    core = " ".join(w for w in words if w not in _CLOCK_FILLER)
    t = time.localtime(now) if now is not None else time.localtime()
    if _CLOCK_TIME.fullmatch(core):
        return f"Sekarang pukul {t.tm_hour:02d}.{t.tm_min:02d} WIB."
    if _CLOCK_DAY.fullmatch(core) or _CLOCK_DATE.fullmatch(core):
        return f"Hari ini hari {_HARI[t.tm_wday]}, {t.tm_mday} {_BULAN[t.tm_mon - 1]} {t.tm_year}."
    return ""

STOP_PATTERNS = [r"\bselesai\b", r"\bdiam\b", r"\bstop\b", r"\bsampai jumpa\b"]

def matches(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)
