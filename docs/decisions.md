# Keputusan dan alasannya

Setiap keputusan di sini diambil dari perilaku produksi dan pengukuran yang sudah dilakukan di
NUC. Kalau mau mengubahnya, ukur ulang di hardware yang sama dulu.

## Audio

- **Endpointing satu implementasi.** Jalur ALSA (dengan arah suara) dan jalur sounddevice memakai
  `audio/endpointing.py` yang sama. Dua loop lama identik secara logika; hanya sumber sampel dan
  DOA yang berbeda. Jalur sounddevice kini juga mengirim `doa=None` di telemetri.
- **Gate energi.** Klip dengan RMS di bawah `BRONE_MIN_UTTERANCE_RMS` (0,030) dibuang. Derau ruangan
  NUC biasanya 0,01 sampai 0,05.
- **Mic dipilih tiap rekaman.** Urutan `BRONE_INPUT_PIPEWIRE_NODES` adalah prioritas. Mic wireless
  dengan RNNoise didahulukan. XVF3800 tidak diberi RNNoise karena chip-nya sudah meredam derau dan
  double-NS merusak STT.
- **Derau tidak diredam di kode.** `BRONE_NOISE_REDUCE` tetap default `0`.

## Kunci penanya (dinonaktifkan 19 Okt 2026)

Kunci penanya (sidik suara CAM++ dan arah SRP-PHAT, 12 Okt 2026) **dinonaktifkan atas permintaan
pengguna**. Pertanyaan lanjutan tanpa nama membuat robot menjawab suara orang lain yang kebetulan
cocok dengan penanya sebelumnya, dan tidak sesuai harapan. Kode `speaker_lock/` masih ada tetapi
tidak dipanggil (`BRONE_LOCK=0`, default kini nonaktif).

## Panggilan dan jendela "Ya?"

- Setiap pertanyaan harus memuat "Brone". Tidak ada lagi mode terkunci.
- Hanya "Brone" tanpa pertanyaan: robot menjawab "Ya?". Ucapan berikutnya **satu kali** saja
  dijawab tanpa nama, dalam jendela `BRONE_AWAIT_SECONDS` (15 detik). Setelah itu harus menyebut
  "Brone" lagi.

## Wake word "halo brone" (KWS, disepakati 23 Okt 2026)

Aktif bila `BRONE_KWS_MODEL` diisi path model openWakeWord (`halo_brone.onnx`, dilatih di
AI-Center 25 Okt 2026). Kosong = mode lama (nama disebut di teks STT).

- **Bangun hanya lewat model KWS**, tidak lewat teks. STT (MAI/whisper) baru jalan setelah bangun,
  jadi biaya MAI turun dan obrolan sekitar tidak pernah ditranskripsi.
- **Satu pertanyaan per bangun.** Alur: tidur -> "halo brone" -> tunggu jeda bicara -> "Ya?" ->
  satu pertanyaan dalam `BRONE_KWS_WINDOW_SECONDS` (8 s, tanpa menyebut nama) -> jawab -> tidur.
  Ucapan sebelum "Ya?" dibuang (tidak ada "halo brone, <pertanyaan>" sekali napas). Tidak bicara
  dalam jendela = tidur lagi tanpa suara.
- **"halo brone" juga interupsi** (`BRONE_KWS_INTERRUPT`, menggantikan rencana "Brone stop"):
  selama berpikir/berbicara, pemantau KWS di thread lain menghentikan TTS dan berhenti menunggu
  LLM, lalu langsung "Ya?". Thread mesin jawaban tidak dibunuh; hasilnya dibuang dan panggilan
  mesin berikutnya menunggu thread itu selesai.
- **Penjaga suara sendiri:** deteksi diabaikan bila kalimat yang sedang diucapkan Bron memuat
  "halo ... bron". Persona tidak dilarang mengucapkannya (pengguna menilai kecil kemungkinannya).
- **Tanya-balik tetap tanpa wake word:** tanggapan atas pertanyaan balik Bron diterima dalam
  `BRONE_SOCIAL_AWAIT_SECONDS`.
- **Pemantau membuka mic sendiri** (arecord kedua lewat PipeWire), bukan berbagi aliran dengan
  perekam. Lebih sederhana, dan PipeWire mengizinkan beberapa klien rekam pada node yang sama.
- **openwakeword dipasang `--no-deps`:** paketnya menuntut tflite-runtime di Linux yang tidak
  punya wheel py3.12. BRONE hanya memakai ONNX.

## STT

- **MAI-Transcribe-2 utama, whisper cadangan.** Whisper dimuat sejak awal dan dipakai saat internet
  lambat atau Azure gagal. Batas tunggu MAI 3,5 detik; lewat itu, cloud dihentikan 30 detik.
- **Model whisper: `faster-whisper-small`** (produksi). README lama menyebut large-v3-turbo, tetapi
  drop-in aktif memakai small.
- **Threads = 4.** Jumlah P-core fisik i7-1260P. Diukur: 12 threads ~1,8 detik per klip, 16 threads
  ~2,0 detik, 4 threads ~1,5 detik. Jangan naikkan tanpa mengukur ulang.
- **Beam = 5 (produksi).** Kode lama default 3 (identik teks, 8% lebih cepat). Produksi memakai 5;
  1 dan 2 terbukti membuang kata ("apa kabar" menjadi "apakah").
- **Prompt baku tanpa kosakata KB.** Kode lama bisa menambahkan judul KB ke prompt, tetapi hanya
  bila `BRONE_WHISPER_TOPICS=1`. Produksi = 0, jadi prompt sama persis dengan prompt baku. Repo
  baru tidak membaca `knowledge.txt` sama sekali. Ini menyederhanakan dan tidak mengubah perilaku.
- **Filter sampah** (`stt/filters.py`) dibaca bersama kosakata prompt. Fixture golden dibuat
  tanpa kosakata, jadi tes golden untuk `garbage_reason` belum membuktikan filter ini (lihat
  `docs/golden.md`).

## Mesin jawaban

- **FAQ dulu, RAG kemudian, LLM terakhir.** Pertanyaan yang sudah ada di FAQ tidak pernah sampai ke
  LLM. Bila reranker tidak yakin, robot menolak tanpa LLM.
- **Pengaman FAQ** (`entities.py`, `FaqIndex._guard`). Menghindari jawaban yang salah tetapi mirip,
  misalnya "wakil rektor" dijawab FAQ "rektor", atau "rektor tahun 2010" dijawab rektor sekarang.
- **Grounding.** Angka dan nama di jawaban LLM harus ada di konteks atau pertanyaan. Bila tidak, jawaban
  diganti penolakan. Ini mencegah LLM mengarang fakta yang tidak ada di KB.
- **Tidak ada semantic cache.** Jawaban LLM tidak disimpan untuk dipakai ulang, supaya tidak ada
  jawaban basi.
- **Cloud 5 detik** (produksi). Kode lama default 8 detik. Lewat batas, pindah ke LLM lokal.
- **Riwayat tidak dipakai.** `BRONE_HISTORY_MESSAGES` ada di unit lama tetapi mesin v4 tidak memakai
  riwayat percakapan; hanya pertanyaan sebelumnya yang dipakai untuk pertanyaan pendek.

## Percakapan (session.py)

- **Panggilan di mana pun dalam kalimat.** "Brone, UB di mana?" dan "UB di mana, Brone?" keduanya
  menjawab. "BRONE FILKOM" adalah nama proyek, bukan panggilan.
- **"Ya?" hanya sekali** per penantian. Ucapan tidak jelas saat menunggu juga hanya diminta diulang
  sekali per giliran, supaya derau tidak membuat robot terus bicara.
- **Riwayat dibersihkan** setiap kali nama disebut di luar penantian.

## Yang dihapus dari versi lama

- RAG v1, v2, v3 (RagLite*), `knowledge.txt`, dan semua jalur Ollama/DeepSeek di kelas `Conversation`.
  Mesin v4 menggantikannya seluruhnya.
- Soniox STT dan TTS (Soniox TTS dihapus 14 Okt 2026). Google STT juga tidak dipakai produksi.
- `BRONE_ENGINE=legacy`. Tidak ada lagi jalur lama di repo ini.
- Skrip pengembangan lama (`_bench_*.py`, berkas `.bak*`). Riwayat sekarang di git.

## Nama dan deploy

- **Unit tetap `brone-talk.service`.** `state_machine_node.py` memanggil nama itu lewat systemctl,
  jadi nama tidak diubah.
- **Nama unit llama.cpp (`brone-v4-*`) belum diganti.** Layanan itu sedang dipakai. Penggantian
  ke `brone-llm|embed|rerank` ditunda sampai cutover, supaya tidak memutus layanan yang hidup.
- **Serial perangkat di konfigurasi PipeWire disensor** di salinan repo. Nilai aslinya tetap di
  `~/.config/pipewire/pipewire.conf.d/` di NUC.
- **Rahasia tidak masuk repo.** Kunci DeepSeek dan MAI dibaca dari
  `~/.config/brone-talk/brone.env`. `EnvironmentFile` menimpa `Environment=` di unit, jadi file itu
  hanya berisi rahasia.
