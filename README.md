# TRX Cat control (CAT Voice Control Interface)

**TRX Cat control** ist ein **CAT Voice Control Interface** für Funkgeräte (aktueller Fokus: **Yaesu FT-991A**).

Ziel: Über **CAT** und die **eingebaute Soundkarte / USB-FT8-Schnittstelle** dein TRX steuern und darüber funken – **ohne** zusätzliche Adapter-Hardware bauen zu müssen. So kannst du direkt über die FT8/USB-Audio-Schnittstelle senden/empfangen und gleichzeitig per CAT (Frequenz/Mode/PTT) steuern.

---

## Warum?

Viele TRX (z. B. FT-991A) liefern über USB:

- **CAT** (Frequenz/Mode/PTT-Steuerung)
- **Audio In/Out** (wie bei FT8/WSJT-X)

Damit lässt sich Sprachbetrieb und Digitalbetrieb ohne extra Interface realisieren. Dieses Tool bündelt die Steuerung und das Audio-Handling in einer Oberfläche.

---

## Funktionen (aktueller Stand)

### CAT / Radio Control
- Frequenz lesen/setzen
- Mode / Split (je nach Rig)
- **Test CAT** direkt im Setup (grün/rot)

### PTT
- PTT-Methode wählbar (je nach Setup)
- **Test PTT** direkt im Setup (grün/rot)

### Audio / Routing
- Audio-Routing / Audio-Matrix (PC Mic ↔ TRX / TRX ↔ PC Speaker)
- Recording-Test (Start Rec / Stop & Play)
- Wave-Test (Abspielen einer Test-WAV, z. B. „Wilhelm Scream“)

---

## Logs (Debug / Support)

Pro Programmstart werden Session-Logs erzeugt:

- `logs/actions.log` → Klick-/Action-Kette (was wurde gedrückt/ausgelöst)
- `logs/error.log` → Exceptions/Tracebacks

Die Logs werden **bei jedem Start neu begonnen** (Session-Log).

---

## Ordnerstruktur (portable)

Das Tool ist als **portable** Anwendung gedacht (kein Installer nötig):


Hinweis: Konfiguration & Logs sollen extern bleiben, damit User (z. B. S-Meter-Mapping/Profiles) bei Bedarf nachjustieren können.

---

## Roadmap (kurz)
- Rig-Architektur: `rigs/` Ordner pro Rig (FT-991A, FT-710, später IC-705)
- S-Meter Profile pro Rig/Mode/AMP/IPO (user-editierbar)
- Safe Tune / ATU Ablauf (FT-991A)
- Stabiler EXE-Build + reproduzierbare Crashlogs

---

## Status
Aktuell: **funktionsfähiger Stand**, wird aktiv weiterentwickelt.