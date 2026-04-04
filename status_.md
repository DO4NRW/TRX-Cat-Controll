# RigLink Server — Aktueller Stand (2026-04-04)

## Skiller-Phase: ABGESCHLOSSEN

### Was wurde gemacht
- `skiller_raspi.md` analysiert (Soll-Zustand der Web-UI)
- Alle relevanten Dateien gelesen und IST-Zustand erfasst:
  - `server.py` — Flask-Server mit rigctld, CAT, Audio, Config APIs (Port 80)
  - `templates/index.html` — Aktuelle Web-UI mit Overlays (Menu, Radio, Audio, Status, Theme)
  - `audio.py` — PCM2901 USB-Audio Erkennung + Streaming (ALSA/PipeWire)
  - `config.json` — IC-705 Konfiguration (Port, Baud, Hamlib etc.)

### Gaps identifiziert
| Problem | Detail |
|---------|--------|
| `toggle-group` fehlt | 0 Elemente, Demo hat >10 |
| `setup-card` fehlt | 0 Elemente |
| `setup-columns` fehlt | 0 Elemente (nur `.two-col` vorhanden) |
| Audio-Setup zu viel | 4 Felder statt 2 (PC Mic + PC Spk müssen raus) |
| `/api/theme` fehlt | Kein Endpoint, Theme ist hardcoded im JS |
| Willkommens-Text falsch | Sagt "oben rechts", Hamburger ist aber links |

### Erstellt
- **`/opt/riglink/skiller_webui.md`** — Detaillierter Builder-Plan mit 6 Aufgaben
  1. `/api/theme` + `/api/theme/save` Endpoints in server.py
  2. CSS-Klassen `.setup-columns`, `.setup-card`, `.toggle-group`
  3. Radio-Setup Overlay umbauen (setup-cards + toggle-groups)
  4. Audio-Setup auf TRX Mic + TRX Speaker reduzieren
  5. Dynamic Theme via `/api/theme` (JS laden statt hardcoded)
  6. Text "oben rechts" → "oben links"
- Verifikations-Befehle für Tester dokumentiert
- **SKILLER-DONE** in `/mnt/watcher/riglink_server/TODO.md` geschrieben

## Kette
```
Skiller ✓ → Builder (wartet) → Tester (wartet)
```

## Projektstruktur
```
/opt/riglink/
├── server.py          — Flask + rigctld (Port 80)
├── audio.py           — USB-Audio Erkennung/Streaming
├── display.py         — OLED Display
├── config.json        — TRX-Konfiguration
├── templates/
│   └── index.html     — Web-UI (Setup-Only, kein Dashboard)
├── static/icons/      — (leer)
├── skiller_raspi.md   — Original-Aufgabe
└── skiller_webui.md   — Builder-Plan (NEU)
```
