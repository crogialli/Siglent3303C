#!/usr/bin/env bash
# Mono-comando: crea/aggiorna il virtualenv se serve, poi avvia l'app.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip -q
  pip install -r requirements.txt -q
else
  source .venv/bin/activate
fi

python app.py
