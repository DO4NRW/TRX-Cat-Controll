# RigLink Review — NW-01 (Remote Server)

## Letzter Stand: 2026-04-04

### Commit: `20d4aed` — feat(web-ui): Aufgaben 1-8

**Erledigt (Skiller-Plan skiller_webui.md):**

| # | Aufgabe | Status |
|---|---------|--------|
| 1 | `/api/theme` Endpoint in server.py | DONE (war bereits vorhanden) |
| 2 | CSS-Klassen: setup-columns, setup-card, toggle-group | DONE |
| 3 | Radio-Setup Overlay mit setup-cards + toggle-groups | DONE |
| 4 | Audio-Setup auf TRX-only reduziert + Streaming-Toggles | DONE |
| 5 | Dynamic Theme via /api/theme (kein hardcodiertes THEMES) | DONE |
| 6 | Willkommens-Text "oben rechts" -> "oben links" | DONE |
| 7 | 10 Theme-Presets in server.py (THEMES Dict) | DONE |
| 8 | Theme-Selector Dropdown im Theme-Overlay | DONE |

### Verifikation (Tester-Kriterien):
- `toggle-group` Elemente: 17 (Soll: >= 10)
- `setup-card` Elemente: 9 (Soll: >= 4)
- `setup-columns` Elemente: 3 (Soll: >= 1)
- `a-pc-mic` Referenzen: 0 (entfernt)
- `a-pc-spk` Referenzen: 0 (entfernt)
- `/api/themes` liefert 10 Preset-Namen
- `/api/theme` liefert aktives Preset mit Farben
- `/api/theme/save` speichert Preset-Wahl

### Geänderte Dateien:
- `server.py` — THEMES Dict (10 Presets), /api/themes, /api/theme, /api/theme/save
- `templates/index.html` — CSS, HTML (Radio/Audio/Theme Overlays), JS (loadTheme, loadThemeList, changeTheme, tgToggle, toggleRx/TxStream)

### Pushed: origin/main (DO4NRW/RigLink)
