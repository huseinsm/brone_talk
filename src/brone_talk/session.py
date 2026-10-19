"""Keputusan per ucapan: kapan robot diam, kapan minta diulang, kapan menjawab.

Aturan (dari brone_talk.py v4, BroneTalkService.run):
  - "Brone" disebut di mana pun dalam kalimat -> pertanyaannya dijawab langsung.
  - Hanya nama ("Brone", "Halo Brone") -> jawab "Ya?", lalu ucapan berikutnya dianggap pertanyaan.
  - Setelah "Ya?" -> SATU ucapan berikutnya tanpa nama dijawab, dalam jendela waktu
    (BRONE_AWAIT_SECONDS). Setelah itu harus menyebut nama lagi.
  - Tidak disebut nama dan tidak sedang menunggu -> diabaikan (standby).
  - Kata stop saat menunggu pertanyaan -> kembali standby.
Tidak ada kunci penanya (sidik suara/arah): dihapus atas permintaan pengguna (19 Okt 2026).

decide() murni: tidak memanggil audio, LLM, atau MQTT. Efek samping ada di app.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from brone_talk.nlu.wake import STOP_PATTERNS, matches, wake_question


class Decision(Enum):
    STOP = "stop"  # kata stop saat menunggu pertanyaan
    STANDBY = "standby"  # tidak ditujukan ke robot
    CONFIRM = "confirm"  # hanya nama: jawab "Ya?" dan tunggu pertanyaan
    ANSWER = "answer"  # ada pertanyaan yang harus dijawab


@dataclass(frozen=True)
class Outcome:
    decision: Decision
    question: str = ""  # teks yang dijawab (untuk ANSWER)
    wake: bool = False  # True bila ANSWER berasal dari ucapan yang menyebut nama


@dataclass
class Session:
    """State antar giliran. awaiting_question: sudah dipanggil, menunggu pertanyaan.
    unclear_said: pesan "suara kurang jelas" sudah diucapkan pada giliran menunggu ini."""

    awaiting_question: bool = False
    unclear_said: bool = False
    awaiting_since: float = 0.0  # time.monotonic() saat "Ya?" diucapkan

    def expire(self) -> None:
        """Kunci penanya habis: penantian pertanyaan ikut berakhir."""
        self.awaiting_question = False


def decide(text: str, *, called: bool, awaiting: bool) -> Outcome:
    if awaiting and matches(STOP_PATTERNS, text):
        return Outcome(Decision.STOP)
    # Tanpa nama, robot hanya menjawab bila sedang menunggu pertanyaan setelah "Ya?".
    if not called and not awaiting:
        return Outcome(Decision.STANDBY)
    if called:
        question = wake_question(text)
        if not question:
            return Outcome(Decision.CONFIRM)
        return Outcome(Decision.ANSWER, question=question, wake=True)
    return Outcome(Decision.ANSWER, question=text, wake=False)
