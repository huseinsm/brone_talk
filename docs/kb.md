# Basis pengetahuan (KB)

Sumber: `kb/knowledge.yaml`. Dari sini dibangkitkan:

- `kb/chunks.jsonl`: potongan kecil untuk retrieval (BM25 dan embedding).
- `kb/faq.jsonl`: pertanyaan dan variasinya untuk FAQ semantik.
- `kb/entities.json`: alias fakultas dan peran untuk pengaman FAQ.

`kb/build_kb.py` juga menulis `knowledge.txt` (format lama) dan `faq_review.md` (daftar untuk
ditinjau manusia). Keduanya tidak dibaca mesin v4, jadi tidak dibawa ke repo.

```bash
cd kb
python build_kb.py --check     # validasi saja
python build_kb.py             # bangun ulang chunks, faq, entities
```

Data tabel (`kb/data/*.csv`: UKT dan IPI 2026) juga dibaca `build_kb.py`.

Setelah mengubah KB, jalankan `make test`. Tes engine golden akan memberi tahu bila rute FAQ berubah
(tes itu butuh fixture, lihat `docs/testing.md`). Embedding dihitung ulang otomatis saat service
start, lalu disimpan di `runtime/embcache.json`.

Fakta yang berubah tahunan (pimpinan, biaya, tanggal) harus diperbarui di `knowledge.yaml`. Field
`berlaku_hingga` menghentikan FAQ atau chunk yang sudah basi tanpa menghapusnya.
