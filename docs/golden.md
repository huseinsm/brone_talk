# Fixture golden (baseline Fase 0)

Dibangkitkan oleh `scripts/make_golden.py` dari kode v4 di `~/brone-talk-v4`. Hasilnya di `tests/golden/`.

| File | Isi | Jumlah |
|---|---|---|
| tts_normalize.jsonl | clean_for_speech atas jawaban nyata | 117 |
| nlu_wake.jsonl | collapse_repeats, wake_question, clock_answer, stop | 587 |
| stt_filters.jsonl | _stt_fix, _mai_fix, stt_garbage_reason, stt_strip_prompt_sentence | 587 |
| engine_routes.jsonl | rute FAQ dan skor reranker, 60 pertanyaan eval | 60 |

## Keterbatasan yang sudah diketahui

- **stt_filters.garbage_reason kosong untuk semua baris.** Fixture dibuat tanpa `stats` dan `vocab`, sehingga filter hampir tidak aktif. Fixture ini belum cukup sebagai bukti; Fase 1 harus merekam ulang dengan stats/vocab yang sama seperti di produksi.
- **Satu mismatch FAQ di baseline:**
siapa dekan fakultas mipa | expect faq:dekan-fstem | got None tolak_mode_faq
- Rute dicatat dengan BRONE_MODE=faq, jadi jalur LLM (DeepSeek, LFM2.5) tidak tercakup. Teks LLM tidak dibandingkan.
- engine_routes bergantung pada server bge-m3 (8082) dan reranker (8083) yang hidup saat merekam.
