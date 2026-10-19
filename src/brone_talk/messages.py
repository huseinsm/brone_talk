"""Kalimat tetap yang diucapkan robot saat menolak atau gagal. Dipindah dari brone_v4.py."""

from __future__ import annotations


MSG_UNCLEAR_AUDIO = "Maaf, suaranya kurang jelas. Bisa diulang pertanyaannya?"

MSG_NOT_UNDERSTOOD = "Maaf, Bron kurang paham pertanyaannya. Bisa diulang dengan kalimat lain?"

MSG_NO_INFO = "Maaf, Bron belum punya informasi tentang itu. Informasi lengkap bisa dilihat di www.ub.ac.id."

MSG_MOTION = "Maaf, kontrol gerakan Bron belum diaktifkan."

MSG_SERVICE_DOWN = "Maaf, layanan percakapan Bron sedang bermasalah."

# Kalimat yang diucapkan saat alur percakapan (bukan penolakan mesin jawaban).
SAY_CONFIRM = "Ya?"
SAY_STOP = "Baik, Bron kembali standby."
SAY_SERVICE_ERROR = "Maaf, layanan percakapan Bron sedang bermasalah."
SAY_FALLBACK = "Maaf, saya tidak mengerti."  # jawaban kosong dari mesin (sama dengan produksi)
