# RigLink Pi-Server — Status (2026-04-04)

## Builder-Phase: ABGESCHLOSSEN

Alle Aufgaben aus `skiller_webui.md` (1-8 + Nachtrag 2) sind implementiert und gepusht.

---

## Was der Pi-Server jetzt kann

### Web-UI (Port 80)
- **Layout 1:1 wie Desktop-Demo** — gleiche CSS-Klassen (`overlay-panel`, `setup-columns`, `setup-card`, `toggle-group`/`toggle-option`, `audio-row`, `menu-dropdown`)
- **Hamburger-Menü** (oben links) mit 4 Einträgen: Radio Setup, Audio Setup, Status, Theme
- **Radio Setup** — 2-Spalten-Layout mit:
  - CAT Control: Serial Port, Baud Rate, Data Bits (Toggle), Stop Bits (Toggle), Handshake (Toggle), CI-V Adresse
  - PTT Konfiguration: CAT/VOX/RTS/DTR als Toggle-Options
  - Setup-Rig-Row: Hersteller + Modell + Hamlib ID + Test CAT / Test PTT / Speichern Buttons
- **Audio Setup** — TRX-only (kein PC Mic/Spk):
  - TRX Microphone (Input) + TRX Loudspeaker (Output) via PipeWire
  - VU-Meter Anzeige
- **10 Theme-Presets** — Dark, Midnight Blue, Forest Green, Solarized Dark, Dracula, Nord, Monokai, Gruvbox Dark, High Contrast, Light
  - Klickbare Preset-Liste im Theme-Overlay
  - Sofortiges Live-Update der CSS-Variablen
  - Preset-Wahl wird in config.json persistiert
- **Systemstatus** — rigctld, IC-705 Verbindung, Uptime, IP, Hamlib-Version, Audio-Backend, USB-Geräte
- **Connection Badge** — pollt `/api/state` alle 3s, zeigt IC-705 Verbindungsstatus

### API-Endpoints
| Endpoint | Methode | Funktion |
|----------|---------|----------|
| `/api/state` | GET | Frequenz, Mode, S-Meter, PTT, Verbindung |
| `/api/ptt` | POST | PTT ein/aus |
| `/api/mode` | POST | Mode setzen (USB, LSB, FM, CW, ...) |
| `/api/frequency` | POST | Frequenz setzen (Hz) |
| `/api/config` | GET | Komplette Config als JSON |
| `/api/config/save` | POST | Config mergen + speichern |
| `/api/ports` | GET | Verfügbare Serial-Ports |
| `/api/cat/test` | POST | CAT-Verbindung testen |
| `/api/ptt/test` | POST | PTT 1s Test |
| `/api/audio/nodes` | GET | PipeWire Sources/Sinks |
| `/api/audio/rx/start` | POST | RX-Audio Stream starten |
| `/api/audio/rx/stop` | POST | RX-Audio Stream stoppen |
| `/api/audio/tx/start` | POST | TX-Audio Stream starten |
| `/api/audio/tx/stop` | POST | TX-Audio Stream stoppen |
| `/api/themes` | GET | Liste der 10 Preset-Namen |
| `/api/theme` | GET | Aktives Preset mit Farben |
| `/api/theme/save` | POST | Preset-Wahl speichern |
| `/api/status` | GET | Erweiterter Systemstatus |
| `/api/db/test` | GET | MariaDB Verbindungstest |

### Backend
- **rigctld** — automatischer Start, Verbindungsüberwachung, Reconnect
- **Poll-Thread** — Frequenz + S-Meter alle 150ms, Mode + PTT alle 3s
- **AudioStreamer** — PCM2901 USB-Audio via ALSA/PipeWire
- **Config** — JSON-basiert (`config.json`), merge-fähig

## Commits auf origin/main (DO4NRW/RigLink)
```
e62b78c docs: review.md nach Layout-Rebuild (Nachtrag 2)
1db67ef refactor(web-ui): Komplettes Layout-Rebuild 1:1 nach Demo
33adcf6 WD-03: Menü-Items EQ, Digi-Modus, Logbuch in Web-Demo ergänzt
```

## Auch gepusht: DO4NRW/RigLink-Reports (Branch: raspi-dev)

## Kette
```
Skiller ✓ → Builder ✓ → Tester (geweckt)
```
