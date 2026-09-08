#!/usr/bin/env bash
# Crea un eseguibile standalone per QUESTO sistema/architettura (nessun
# prerequisito per chi lo scarica: Python e tutte le dipendenze, incluso
# libusb, sono incluse nel binario).
#
# PyInstaller non compila in modo incrociato: va eseguito separatamente su
# ogni piattaforma che si vuole distribuire (una volta su Mac per il
# binario Mac, una volta su Linux/Raspberry Pi per quello Linux, ecc.).
#
# Nota macOS: PyInstaller richiede un Python compilato con libreria
# condivisa (--enable-shared/--enable-framework). Un Python installato con
# pyenv è spesso statico di default e fallisce con un errore esplicito su
# questo — usiamo il Python di Homebrew se disponibile, altrimenti quello
# di sistema (su Linux/Raspberry Pi il python3 di sistema ha già la
# libreria condivisa, questo problema è specifico di certe build macOS).
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PYTHON_BIN="python3"
for candidate in \
  /opt/homebrew/opt/python@3.12/bin/python3.12 \
  /opt/homebrew/opt/python@3.11/bin/python3.11 \
  /usr/local/opt/python@3.12/bin/python3.12 \
  /usr/local/opt/python@3.11/bin/python3.11; do
  if [ -x "$candidate" ]; then
    PYTHON_BIN="$candidate"
    break
  fi
done

VENV_DIR=".venv-build"
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install -q pyinstaller

OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
OUT_NAME="siglent3303c-${OS_NAME}-${ARCH}"

pyinstaller \
  --onefile \
  --name "$OUT_NAME" \
  --add-data "${DIR}/static:static" \
  --collect-all libusb_package \
  --collect-all pyvisa_py \
  --copy-metadata pyvisa_py \
  --distpath dist \
  --workpath build \
  --specpath build \
  app.py

echo
echo "Eseguibile creato: dist/${OUT_NAME}"
