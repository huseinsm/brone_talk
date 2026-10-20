# Kontrak MQTT

BRONE Talk hanya **menerbitkan** telemetri ke broker Jetson (`192.168.100.2:1883`) dan tidak
mengirim perintah gerak. Dua konsumen membaca topik ini: `state_machine_node.py` dan
`brone_talk_monitor.py` di `brone_main_ws`. Mengubah nama topik atau field berarti mengubah
keduanya, jadi kontrak ini harus tetap stabil.

Semua payload JSON, UTF-8 (`ensure_ascii=False`). Penerbitan best-effort: broker mati tidak
menghentikan giliran percakapan.

| Topik | QoS | Pengirim | Payload |
|---|---|---|---|
| `robot/voice_status` | 1 | `Telemetry.status` | `{"status": str, "detail": str}` |
| `robot/voice_stage` | 0 | `Telemetry.stage` | `{"stage": str, "state": str, "ts": float, ...field}` |
| `robot/vad_status` | 0 | `Telemetry.vad` | `{"status": "speaking"\|"silence"\|"stopped", "rms": float}` |
| `robot/expression` | 0 | `Telemetry.expression` | `{"expression": str}` atau `{"expression": str, "duration": int}` |

## voice_status

`status` memakai nilai: `warming` (dengan `detail` langkah warmup), `ready` (`detail` = waktu
warmup), `error` (`detail` = pesan singkat). Konsumen menampilkannya sebagai status "Voice engine".

## voice_stage

`stage` dan `state` yang diterbitkan:

| stage | state | field tambahan | Arti |
|---|---|---|---|
| `listening` | `start` | `device`, `sample_rate` | mulai mendengarkan |
| `listening` | `mic` | `node` | node PipeWire terpilih |
| `listening` | `speech` | `rms` | ucapan terdeteksi |
| `listening` | `done` | `audio_s`, `peak_rms` | klip siap untuk STT |
| `listening` | `timeout` | `peak_rms` | tidak ada ucapan |
| `listening` | `too_short` / `low_energy` | `audio_s` / `rms` | klip dibuang |
| `stt` | `start` / `done` | `model`, `backend` / `ms`, `text`, `model` | transkripsi |
| `stt` | `ignored` | `reason`, `text` | ucapan dibuang filter |
| `llm` | `start` | `model`, `backend` | mesin jawaban mulai (`backend` = `v4`) |
| `llm` | `done` | `ms`, `route`, `backend`, `model` | jawaban siap (`route` = faq, llm_cloud, dst.) |
| `idle` | `awaiting_question` | `wake_text` | "Ya?" diucapkan |
| `idle` | `answering` | `wake_text` / `follow_up_text` | menjawab |
| `idle` | `standby` | `reason`, `heard` (opsional) | kembali menunggu |
| `idle` | `stopped` | - | layanan berhenti |
| `tts` | `start` / `done` | `ms`, `audio_s`, `played` | sintesis dan playback |
| `error` | `audio` / `stt` / `llm` / `tts` | `detail` | kegagalan per komponen |

## vad_status

`status` `speaking` atau `silence` diterbitkan tiap 8 jendela (~256 ms), `stopped` saat klip
selesai. `rms` dalam skala 0..32768.

## expression

Ekspresi wajah robot: `happy`, `neutral`, `sad`, `excited`, `confused`, `speaking`, atau `idle`.
`duration` (detik, dibulatkan ke atas) hadir bila ucapan diperkirakan berlangsung lama.
