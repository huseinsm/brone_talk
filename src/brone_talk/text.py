"""Tokenisasi teks bersama (STT, wake word).

Dipindah dari brone_talk.py (v4). Fungsi murni.
"""

import re
import unicodedata


def stt_tokens(text: str) -> list[str]:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", norm)

