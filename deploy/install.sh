#!/usr/bin/env bash
# Pasang BRONE Talk di NUC: venv, symlink model, dan unit systemd --user.
# TIDAK mengaktifkan atau menjalankan layanan. Jalankan dari folder repo:
#   bash deploy/install.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .

# Model tidak ada di git. Pakai folder model yang sudah ada di NUC, atau isi manual (lihat docs/deployment.md).
if [ ! -e models ]; then
  if [ -d "$HOME/brone-talk/models" ]; then
    ln -s "$HOME/brone-talk/models" models
    echo "models -> $HOME/brone-talk/models (symlink)"
  else
    echo "PERINGATAN: folder models/ belum ada. Lihat docs/deployment.md." >&2
  fi
fi

# Dipasang sebagai brone-talk-next.service: unit produksi brone-talk.service TIDAK disentuh.
# Cutover (mengganti nama unit) dilakukan manual, lihat docs/deployment.md.
mkdir -p runtime "$HOME/.config/systemd/user" "$HOME/.config/brone-talk"
install -m 644 deploy/systemd/brone-talk.service "$HOME/.config/systemd/user/brone-talk-next.service"
systemctl --user daemon-reload

# EnvironmentFile menimpa Environment= di unit, jadi file ini HANYA berisi rahasia.
if [ ! -f "$HOME/.config/brone-talk/brone.env" ]; then
  umask 077
  printf 'BRONE_DEEPSEEK_API_KEY=\nBRONE_MAI_API_KEY=\n' > "$HOME/.config/brone-talk/brone.env"
  echo "Dibuat $HOME/.config/brone-talk/brone.env (isi kedua kunci, chmod 600)."
fi
echo "Terpasang sebagai brone-talk-next (belum dijalankan). Uji: systemctl --user start brone-talk-next"
