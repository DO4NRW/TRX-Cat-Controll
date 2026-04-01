#!/bin/bash
# TRX Cat Control V2 — Starten (Linux/macOS)
cd "$(dirname "$0")"
if [ ! -d "venv" ]; then
    echo "Erst ./setup.sh ausführen!"
    exit 1
fi
source venv/bin/activate
python main.py
