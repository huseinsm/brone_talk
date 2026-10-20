# Arsitektur

## Alur satu giliran

```
mic (PipeWire/ALSA)                                 [audio/capture.py]
  -> Silero VAD per 32 ms                           [audio/vad.py]
  -> endpointing: mulai saat ucapan, selesai setelah senyap [audio/endpointing.py]
  -> STT: MAI-Transcribe-2 (cloud) atau whisper     [stt/transcriber.py]
  -> panggilan: "Brone" di awal kalimat / akhir ucapan [nlu/wake.py call_text]
  -> koreksi kata + filter sampah + strip prompt    [stt/corrections.py, stt/filters.py]
  -> keputusan: diam / ingatkan nama / jawab / stop [session.py]
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
3. **Obrolan santai berjawaban tetap** (`kb/smalltalk.yaml`): menang bila skornya setara atau lebih
   tinggi dari FAQ. Permintaan pantun, lelucon, dan tebak-tebakan dipilih lewat kata kunci.
4. **Gerakan fisik** (`is_motion_command`): perintah pendek yang diawali kata gerak ("lambaikan
   tangan", "ikut aku") -> "kontrol gerakan belum aktif". Pertanyaan tidak termasuk.
5. **Retrieval hybrid** (`engine/retrieval.py`): BM25 dan embedding, digabung dengan RRF.
6. **Reranker** bge-reranker-v2-m3 (`servers.py`). Skor di bawah `BRONE_RERANK_MIN` -> tidak ada
   data UB: obrolan dijawab LLM persona (`CHAT_PROMPT`), permintaan info ditolak ("belum punya informasi").
7. **LLM**: DeepSeek lebih dulu; gagal atau lewat batas waktu -> LFM2.5-2.6B lokal (llama.cpp).
   Prompt dan format JSON di `engine/llm.py`.
8. **Cek grounding** (`engine/grounding.py`): angka dan nama di jawaban harus ada di konteks,
   bila tidak jawaban diganti penolakan.

Tidak ada cache semantik: jawaban LLM tidak disimpan untuk dipakai ulang.

## Modul dan tanggung jawab

| Modul | Isi |
|---|---|
| `config.py` | semua variabel env, sekali baca, default = nilai produksi |
| `app.py` | `TalkService`: wiring, warmup, loop `turn()` |
| `session.py` | `decide()` murni: keputusan per ucapan; `Session`: state menunggu pertanyaan ("Ya?") |
| `cli.py`, `__main__.py` | perintah `run`, `self-test`, `list-devices`, `mic-test`, `ask` |
| `audio/` | perangkat, VAD, endpointing, perekaman |
| `stt/` | transkripsi, koreksi, filter, skor confidence |
| `nlu/wake.py` | nama Brone, panggilan, jawaban jam, kata stop |
| `names.py` | satu sumber variasi nama "Brone" |
| `engine/` | mesin jawaban (FAQ, retrieval, reranker, LLM, grounding) |
| `tts/` | normalisasi teks untuk TTS, Piper, playback |
| `telemetry.py` | publisher MQTT |
| `messages.py` | semua kalimat tetap yang diucapkan |

## Status state (`session.py`)

```
IDLE --(nama di awal/akhir + pertanyaan)--------> jawab -> IDLE
IDLE --(nama di tengah kalimat / tanpa nama)----> IDLE (diam)
IDLE --(nama saja)--> "Sebut Bron bersama pertanyaannya" -> IDLE   (BRONE_AWAIT_SECONDS=0, produksi)
IDLE --(nama saja)--> AWAITING ("Ya?")                              (bila BRONE_AWAIT_SECONDS > 0)
IDLE --(Bron bertanya balik)--> AWAITING sosial (BRONE_SOCIAL_AWAIT_SECONDS, 8 s)
AWAITING --(satu ucapan tanpa nama)--> jawab -> IDLE (sosial: diam bila ujungnya penolakan)
AWAITING --(stop)--> IDLE ("Baik, Bron kembali standby.")
AWAITING --(jendela habis)--> IDLE
```

Kunci penanya (sidik suara + arah) dihapus 19 Okt 2026: setiap pertanyaan harus menyebut nama.

## Asal kode

| Bagian | Sumber (repo lama) |
|---|---|
| mesin jawaban, KB | `~/brone-talk-v4/brone_v4.py`, `~/brone-talk-v4/kb/` |
| audio, STT, TTS, service | `~/brone-talk-v4/brone_talk.py` (sudah berisi kait v4) |
| normalisasi TTS | `brone_talk.py` bagian normalisasi (versi lama) |

Repo lama tidak diubah; `brone-pakai lama|v4` tetap bisa dipakai untuk kembali.
