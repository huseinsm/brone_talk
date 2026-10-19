"""Koreksi salah-dengar hasil STT (whisper dan MAI). Dipindah dari brone_talk.py (v4)."""

import re

from brone_talk.names import _BRONE_VARIANTS, _FILKOM_VARIANTS


_STT_FIX_RULES: list[tuple[str, str]] = [
    (rf"\b{_BRONE_VARIANTS}\s*(?:{_FILKOM_VARIANTS}|field|vill?e?|fil|phil|com|kom|koma)(?:\s*com)?\b",
     "BRONE FILKOM"),
    (r"\b(brownfield|bronevillekom|broneville|bronfield|braunfield|bronefilkom|brone_filkom)\b",
     "BRONE FILKOM"),
    (rf"\b{_FILKOM_VARIANTS}(?:\s*\.?\s*com)?\b", "FILKOM"),
    (r"\b(eprone|ebrone|ebron)\b", "Eh BRONE"),  # "Eh Brone" digabung Whisper small
    (rf"\b{_BRONE_VARIANTS}\b", "BRONE"),
    (r"\b(berawijaya|bravijaya|berawi\s+jaya|brawi\s+jaya)\b", "Brawijaya"),
    # "masuk UB" -> "masuk Uber" (bench TTS 6 Okt 2026); hanya setelah kata konteks kampus.
    (r"\b(masuk|kuliah\s+di|kampus|di|ke|dari|mahasiswa)\s+uber\b", r"\1 UB"),
    (r"\bbasiswa\b", "beasiswa"),
    (r"\bbi\s+ss\b", "BISS"),
    (r"\b(laborodrum|laborodum|laboratorium?)\b", "laboratorium"),
    (r"\b(bulet|bolet)\b", "bullet"),
    (r"\b(apas|apaa)\b", "apa"),
    (r"\b(dimana)\b", "di mana"),
    (r"\b(disana)\b", "di sana"),
    (r"\b(kemana)\b", "ke mana"),
    (r"\b(capai yang)\b", "capaian"),
    (r"\b(tembahan|tambaha)\b", "tambahan"),
    (r"\b(departemen teknik informatika)\b", "Departemen Teknik Informatika"),
    (r"\b(departemen sistem informasi)\b", "Departemen Sistem Informasi"),
    (r"\b(fakultas ilmu administrasi)\b", "Fakultas Ilmu Administrasi"),
    (r"\b(negerikan|di\s+negerikan)\b", "dinegerikan"),
    (r"\b(nirc|nerc|nirk|nark)\b", lambda m: m.group(0).upper()),
    (r"\b(unibraw|unibra|unbra|unibrow)\b", "UNIBRAW"),
    (r"\b(jawa\s+timur|jatim)\b", "Jawa Timur"),
    (r"\b(malang)\b", "Malang"),
    (r"\b(universitas\s+brawijaya|universitas\s+berawijaya|universitas\s+bravijaya|ub)\b",
     lambda m: "UB" if m.group(0).strip().lower() == "ub" else "Universitas Brawijaya"),
    # P14: "UKM" di awal kalimat tetap salah dengar walau sudah di hotwords
    # (uji empiris: whisper kurang konteks kiri untuk akronim 3-huruf di
    # posisi pertama). "ukaan"/"hukaan"/"kuka" bukan kata Indonesia asli,
    # jadi aman dikoreksi tanpa syarat konteks tambahan.
    (r"\b(ukaan|hukaan|ukaa|ukam)\b", "UKM"),
    (r"\bkuka(?:\s+ngapa)?\b", "UKM apa"),
    # "buka" hanya dikoreksi kalau diikuti pola pertanyaan UKM yang khas,
    # supaya tidak menimpa "buka" dalam arti sebenarnya (buka pintu, dll).
    (r"\bbuka\s+apa\s+saja\b", "UKM apa saja"),
    (r"\b(bis)\b(?=\s*\??\s*$)", "BISS"),  # "Apa itu bis?" -> BISS (akhir kalimat)
    (r"\bfimipa\b", "FMIPA"),
    (r"\b(kedekteran|kedoktern|kedokteren)\b", "kedokteran"),
]
_MAI_FIX_RULES: list[tuple[str, str]] = [
    # "di FTAB" digabung: "divtab", "DivTAP", "DFTAB" (6/16 klip FTAB).
    (r"\bd(?:i)?[vf]\s?ta[bp]\b", "di FTAB"),
    # "di FISIP" digabung: "divisip", "divisi F".
    (r"\bdivisi(?:p|\s+f)\b", "di FISIP"),
    (r"\b[fh]-?\s?mipa\b", "FMIPA"),  # "F-MIPA", "HMIPA"
    (r"\bfbi[\s-]?pk\b", "FBiPK"),  # "FBI-PK"
    (r"\bfik\b", "FPIK"),  # tidak ada fakultas "FIK" di UB
    (r"\b(dekan|di|ke|dari)\s+via\b", r"\1 FIA"),  # "Siapa dekan Via"
    (r"\bubei\b", "UB"),
]
def _stt_fix(text: str) -> str:
    """Rapikan salah-dengar umum tanpa mengubah makna kalimat."""
    if not text:
        return text
    out = text
    for pattern, repl in _STT_FIX_RULES:
        out = re.sub(pattern, repl, out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out
def _mai_fix(text: str) -> str:
    """Koreksi salah-dengar spesifik MAI-Transcribe-2."""
    if not text:
        return text
    out = text
    for pattern, repl in _MAI_FIX_RULES:
        out = re.sub(pattern, repl, out, flags=re.I)
    return out

