# BRONE Talk

Pipeline percakapan suara robot BRONE (Intel NUC): panggilan "Brone", transkripsi (MAI-Transcribe-2
dengan cadangan whisper lokal), jawaban dari FAQ semantik, RAG, dan LLM, lalu suara Piper. Telemetri
dikirim ke broker MQTT di Jetson.

> **Status:** refactor dari versi produksi `~/brone-talk-v4`. Logika inti sudah dipindah dan diuji
> terhadap perilaku produksi. Pengujian di perangkat keras dan cutover belum dilakukan. Lihat
> [docs/testing.md](docs/testing.md) dan [docs/deployment.md](docs/deployment.md).

## Mulai cepat

```bash
make install                         # venv, paket, unit systemd --user (tidak dijalankan)
make test                            # tes unit dan golden
make ask Q="siapa dekan filkom"      # uji mesin jawaban lewat teks
make self-test                       # validasi model dan mesin tanpa mic/speaker
systemctl --user start brone-talk    # jalankan layanan di NUC
```

Rahasia (`BRONE_DEEPSEEK_API_KEY`, `BRONE_MAI_API_KEY`) hanya di `~/.config/brone-talk/brone.env`.
Repo ini tidak menyimpan kunci.

## Cara kerja singkat

1. Mic PipeWire, Silero VAD memotong ucapan.
2. STT, lalu koreksi dan filter sampah.
3. Keputusan: hanya ucapan dengan "Brone" di awal kalimat atau di akhir ucapan yang dijawab.
4. Jawaban: jam sistem, atau mesin jawaban (FAQ, obrolan santai, reranker, LLM, cek grounding).
5. Piper TTS dan playback, dengan telemetri MQTT di setiap tahap.

Detail di [docs/architecture.md](docs/architecture.md).

## Struktur

```
src/brone_talk/     paket: config, app, session, cli, audio/, stt/, engine/, tts/, nlu/
kb/                 basis pengetahuan (knowledge.yaml, build_kb.py, data/, hasil build)
tests/              unit dan golden
scripts/            make_golden.py (fixture lokal), gen_config_docs.py (docs konfigurasi)
deploy/             install.sh, unit systemd, konfigurasi PipeWire (serial disensor)
docs/               arsitektur, konfigurasi, kontrak MQTT, keputusan, deploy, pengujian
```

## Dokumentasi

- [Arsitektur](docs/architecture.md): alur giliran, mesin jawaban, state percakapan.
- [Konfigurasi](docs/configuration.md): semua variabel env, default produksi. Dibangkitkan dari `config.py`.
- [Kontrak MQTT](docs/mqtt-contract.md): topik dan payload yang dibaca state machine dan monitor.
- [Keputusan](docs/decisions.md): alasan setiap ambang dan pilihan, dan apa yang dihapus dari versi lama.
- [Deploy](docs/deployment.md): pasang, smoke test, cutover, rollback.
- [Pengujian](docs/testing.md): apa yang sudah dan belum dibuktikan.
- [Basis pengetahuan](docs/kb.md): cara membangun ulang KB.
- [Baseline produksi](docs/baseline-config.md) dan [fixture golden](docs/golden.md).

## Lisensi

Belum ditentukan. Sampai ada lisensi, kode ini tidak boleh dipakai ulang tanpa izin dari pemilik repo.
