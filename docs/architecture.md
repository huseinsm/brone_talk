# Arsitektur

## Alur satu giliran

```
mic (PipeWire/ALSA)                                 [audio/capture.py]
  -> Silero VAD per 32 ms                           [audio/vad.py]
  -> endpointing: mulai saat ucapan, selesai setelah senyap [audio/endpointing.py]
  -> arah suara dari 4 mic (bila XVF3800 tersambung) [audio/capture.py, speaker_lock/doa]
  -> kunci penanya: sidik suara + arah              [speaker_lock/lock.py]
  -> STT: MAI-Transcribe-2 (cloud) atau whisper     [stt/transcriber.py]
  -> koreksi kata + filter sampah + strip prompt    [stt/corrections.py, stt/filters.py]
  -> keputusan: diam / jawab "Ya?" / jawab / stop   [session.py]
  -> jam sistem (tanpa LLM)                          [nlu/wake.py]
  -> mesin jawaban                                  [engine/answer.py]
  -> TTS Piper + playback                           [tts/speaker.py, tts/normalize.py]
  -> telemetri MQTT di setiap tahap                 [telemetry.py]
```

## Mesin jawaban (engine)

Urutan per pertanyaan (`engine/answer.py`, `AnswerEngine.answer`):

1. **Gerbang confidence STT.** Bila rata-rata probabilitas STT dan segmen terlemah cukup, FAQ
   dipakai dengan ambang biasa. Bila tidak, FAQ hanya dipakai kalau kemiripannya sangat tinggi.
2. **FAQ semantik** (`engine/faq.py`): embedding bge-m3 (`servers.py`) dibandingkan dengan 146 FAQ
   dan variasi kalimatnya. Pengaman (`engine/entities.py`, `FaqIndex._guard`): FAQ satu fakultas
   tidak dipakai untuk fakultas lain, peran (rektor/dekan) harus cocok, kata tanya harus cocok,
   tahun harus ada di FAQ.
3. **Gerakan fisik** diminta -> "kontrol gerakan belum aktif" (tanpa kontrol gerak di repo ini).
4. **Retrieval hybrid** (`engine/retrieval.py`): BM25 dan embedding, digabung dengan RRF.
5. **Reranker** bge-reranker-v2-m3 (`servers.py`). Skor di bawah `BRONE_RERANK_MIN` -> robot
   menolak lewat kode ("belum punya informasi"), tanpa LLM.
6. **LLM**: DeepSeek lebih dulu; gagal atau lewat batas waktu -> LFM2.5-2.6B lokal (llama.cpp).
   Prompt dan format JSON di `engine/llm.py`.
7. **Cek grounding** (`engine/grounding.py`): angka dan nama di jawaban harus ada di konteks,
   bila tidak jawaban diganti penolakan.

Tidak ada cache semantik: jawaban LLM tidak disimpan untuk dipakai ulang.

## Modul dan tanggung jawab

| Modul | Isi |
|---|---|
| `config.py` | semua variabel env, sekali baca, default = nilai produksi |
| `app.py` | `TalkService`: wiring, warmup, loop `turn()` |
| `session.py` | `decide()` murni: keputusan per ucapan; `Session`: state menunggu pertanyaan |
| `cli.py`, `__main__.py` | perintah `run`, `self-test`, `list-devices`, `mic-test`, `ask` |
| `audio/` | perangkat, VAD, endpointing, perekaman |
| `speaker_lock/` | kunci penanya (sidik suara CAM++ dan arah SRP-PHAT) |
| `stt/` | transkripsi, koreksi, filter, skor confidence |
| `nlu/wake.py` | nama Brone, panggilan, jawaban jam, kata stop |
| `names.py` | satu sumber variasi nama "Brone" |
| `engine/` | mesin jawaban (FAQ, retrieval, reranker, LLM, grounding) |
| `tts/` | normalisasi teks untuk TTS, Piper, playback |
| `telemetry.py` | publisher MQTT |
| `messages.py` | semua kalimat tetap yang diucapkan |

## Status state (`session.py`)

```
IDLE --(nama + pertanyaan)----------------------> jawab -> IDLE
IDLE --(nama saja)--> AWAITING --(ucapan valid)--> jawab -> IDLE
AWAITING --(stop)--> IDLE ("Baik, Bron kembali standby.")
AWAITING --(ucapan tidak jelas, sekali)--> tetap AWAITING
ucapan tanpa nama HANYA dijawab di status AWAITING (kunci penanya tidak cukup); kunci habis setelah 15 s senyap
```

Kunci penanya (`speaker_lock/lock.py`) dibuat saat nama disebut, diperpanjang setiap kali ada
ucapan penanya atau jawaban selesai, dan lepas setelah `BRONE_LOCK_TIMEOUT_SECONDS` tanpa suara.

## Asal kode

| Bagian | Sumber (repo lama) |
|---|---|
| mesin jawaban, KB | `~/brone-talk-v4/brone_v4.py`, `~/brone-talk-v4/kb/` |
| audio, STT, TTS, service | `~/brone-talk-v4/brone_talk.py` (sudah berisi kait v4) |
| kunci penanya | `~/brone-talk/brone_lock.py` |
| normalisasi TTS | `brone_talk.py` bagian normalisasi (versi lama) |

Repo lama tidak diubah; `brone-pakai lama|v4` tetap bisa dipakai untuk kembali.
