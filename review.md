# RigLink Review — NW-01 (Remote Server)

## Letzter Stand: 2026-04-04

### Commit: `1db67ef` — refactor(web-ui): Komplettes Layout-Rebuild 1:1 nach Demo

**Erledigt (Skiller-Plan skiller_webui.md):**

| # | Aufgabe | Status |
|---|---------|--------|
| 1 | `/api/theme` + `/api/theme/save` + `/api/themes` Endpoints | DONE |
| 2 | CSS-Klassen aus Demo übernommen | DONE (Nachtrag 2: komplett neu) |
| 3 | Radio-Setup mit setup-rig-row + toggle-groups | DONE (1:1 Demo) |
| 4 | Audio-Setup TRX-only mit audio-row + VU-Meter | DONE (1:1 Demo) |
| 5 | Dynamic Theme via /api/theme | DONE |
| 6 | Willkommens-Text "oben links" | DONE |
| 7 | 10 Theme-Presets in server.py (Demo-Variablen) | DONE |
| 8 | Theme-Selector als Preset-Liste im Overlay | DONE |
| N2 | Komplettes Layout-Rebuild nach Demo-Vorlage | DONE |

### Layout-Rebuild Details (Nachtrag 2):
- **CSS-Variablen**: Demo-Schema (--accent, --bg-dark, --bg-mid, --bg-light, --border, --border-hover, --text, --text-secondary, --text-muted, --error)
- **CSS-Klassen**: overlay-panel, overlay-panel-wide, overlay-panel-tall, setup-columns, setup-card, setup-rig-row, toggle-group, toggle-option, audio-row, audio-label, menu-dropdown, menu-item, etc.
- **Radio Setup**: setup-rig-row (Hersteller + Modell + Hamlib ID + Test/Save Buttons) + 2-Spalten setup-columns mit toggle-groups für Data Bits, Stop Bits, Handshake, PTT Method
- **Audio Setup**: audio-row mit Labels (TRX MICROPHONE, TRX LOUDSPEAKER) + VU-Meter
- **Theme**: Preset-Liste (nicht Dropdown) — klickbare Items wie Demo
- **Menu**: menu-dropdown statt overlay-box — wie Demo
- **THEMES**: 11 Keys pro Preset (accent, accent_dark, error, bg_dark, bg_mid, bg_light, border, border_hover, text, text_secondary, text_muted)
- **Zeilenanzahl**: 876 → 756 (Demo: 443 — Differenz = Pi-spezifische Status/Config-Seiten)

### Verifikation:
- `toggle-group` Elemente: 7 (CSS + HTML)
- `toggle-option` Elemente: 20
- `setup-card` Elemente: 8
- `setup-columns` Elemente: 3
- `overlay-panel` Elemente: 11
- `setup-rig-row` Elemente: 4
- `audio-row` Elemente: 4
- `a-pc-mic` / `a-pc-spk`: 0 (entfernt)
- Keine hardcodierten Hex-Farben außer CSS-Fallbacks in var()

### Geänderte Dateien:
- `server.py` — THEMES auf Demo-Variablen umgestellt (11 Keys)
- `templates/index.html` — Komplett neu geschrieben nach docs/style.css + docs/index.html

### Pushed: origin/main (DO4NRW/RigLink)
