#!/usr/bin/env bash
# Pemeriksaan mic sebelum BRONE Talk start (dipanggil sebagai ExecStartPre; gagal tidak menghentikan service).
# Kartu XVF3800 ada tapi node PipeWire brone-mic-xvf diam -> sesi PipeWire macet (mis. setelah kartu dicabut-pasang).
# Solusi: restart pipewire dan wireplumber sekali, lalu ukur lagi.
set -u
PY="$HOME/brone_talk/.venv/bin/python"
TMP="$(mktemp --suffix=.wav)"
trap 'rm -f "$TMP"' EXIT

level() {  # cetak RMS 2 detik dari brone-mic-xvf (0 bila tidak ada data)
    timeout -s INT 2 pw-record --target brone-mic-xvf --rate 16000 --channels 1 "$TMP" >/dev/null 2>&1
    "$PY" - "$TMP" <<'PY'
import sys, wave, numpy as np
try:
    with wave.open(sys.argv[1]) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    print(f"{float(np.sqrt(np.mean(x**2))) if x.size else 0.0:.6f}")
except Exception:
    print("0.000000")
PY
}

if ! grep -q "XVF3800" /proc/asound/cards; then
    echo "mic_check: kartu XVF3800 tidak terdeteksi, dilewati"; exit 0
fi
rms="$(level)"
if awk "BEGIN{exit !($rms < 0.0005)}"; then
    echo "mic_check: brone-mic-xvf diam (rms=$rms), restart pipewire dan wireplumber"
    systemctl --user restart pipewire wireplumber
    sleep 6
    rms="$(level)"
fi
echo "mic_check: brone-mic-xvf rms=$rms"
exit 0
