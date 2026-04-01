# RigLink — Projektkontext

## Übersicht
Amateurfunk TRX-Steuerung (CAT Control) mit PySide6/Qt. Steuert Transceiver via CAT-Protokoll, Audio-Routing zwischen PC und TRX, VOX, S-Meter.

**Entwickler:** DO4NRW | **Sprache:** Deutsch | **Framework:** PySide6 | **Python:** 3.x (venv: /home/themock/venv)

## Projektstruktur
```
main.py                          — App-Start
main_ui.py                       — MainWindow, Overlays (Radio Setup, Audio Setup), Top-Bar
configs/
  status_conf.json               — Status-Messages, last_rig
  theme.json                     — Globale Farbkonfiguration
  audio_conf.json                — (deprecated, Audio jetzt in Rig-Config)
rig/                             — Rig-Ordner (wird dynamisch gescannt)
  yaesu/ft991a/
    config.json                  — CAT, PTT, Audio, VOX Config
    cat_handler.py               — CAT-Befehle (Serial)
    ft991a_ui.py                 — Rig-spezifische GUI (FT991AWidget)
  icom/ic7300/
    config.json                  — (nur Config, noch keine GUI)
assets/icons/                    — SVG/PNG Icons
assets/audio/                    — Test-WAV, temp_rec.wav
core/status.py                   — StatusManager
```

## Architektur-Regeln
- **Jeder TRX** hat eigenen Ordner: `rig/<hersteller>/<modell>/` mit `config.json` + optional `<modell>_ui.py`
- **Rig-Widget** wird dynamisch geladen: `<MODELL>Widget` Klasse
- **Audio-Config** wird IN die Rig-Config gespeichert (nicht separat)
- **Neues Rig hinzufügen** = Ordner + config.json anlegen, App scannt automatisch

## Audio (Linux)
- **NICHT sounddevice** für TRX-Audio nutzen — PipeWire blockiert ALSA hw-Devices
- **pw-cat** mit `--target <node.name>` für alle Audio-Streams (RX + TX)
- `node.name` über `pw-cli info <id>` abfragen, NICHT die Node-ID verwenden
- **sounddevice** nur für Windows/Mac Fallback
- Wave Test / Rec Test nutzen immer die AKTUELLEN Dropdown-Werte, nicht die gespeicherte Config

## S-Meter Kalibrierung
- Eigene Tabelle pro Preamp (IPO/AMP1/AMP2) UND Modus (FM vs SSB)
- Key-Format: `"AMP1_FM"` für modus-spezifisch, `"AMP1"` als Fallback
- 80% Schwelle für Stufenwechsel (`frac >= 0.8`)
- Smoothing: 80% neuer Wert, 20% alter Wert

## UI/Design
- **Farbschema:** Teal #06c6a4 (Logo-Farbe), definiert in configs/theme.json
- **Alle Texte weiß** (#ffffff), Slider-Spur grau (#888888), Handle Teal
- **Aktive Buttons:** nur Border Teal, kein gefüllter Hintergrund
- **Leertaste = nur PTT** — alle Widgets haben NoFocus, QLineEdit hat ClickFocus
- **Overlays:** EventFilter muss ComboBox-Popups durchlassen (separates Fenster)

## Polling
- **150ms Timer** — nur Frequenz + S-Meter
- **Voller Sync** (Mode, Preamp, Power, DNR) nur bei Connect + Button-Klicks
- **Kein ständiges Pollen** von Mode/Preamp/DSP

## VOX
- Toggle + THR Slider (-60 bis -5 dBFS, 5er Schritte) + HOLD Slider (100-2000ms, 100er Schritte)
- **Debounce:** 150ms über Schwelle bevor PTT aktiv
- **Lockout:** 500ms nach PTT-Off (verhindert Re-Trigger durch RX-Audio/FM-Rauschen)
- Auto-Save in Rig-Config

## CAT Disconnect
- `connected = False` OHNE Lock setzen (stoppt laufende Queries)
- Polling sofort stoppen, GUI zurücksetzen
- Serial im Background-Thread schließen (kein GUI-Freeze)

## TODO nächste Session
- **Theme live anwenden:** `load_theme()` Funktion die alle Styles aus `configs/theme.json` generiert, `apply_theme()` die nach Speichern im Theme Editor alle Widgets refresht. Aktuell werden Farben nur gespeichert aber nicht live gesetzt — braucht App-Neustart. Alle hardcodierten Farben in Stylesheets durch theme.json Werte ersetzen.

## Git Referenz
Alte Version (CustomTkinter): https://github.com/DO4NRW/TRX-Cat-Controll
