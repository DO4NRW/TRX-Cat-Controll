# Skiller-Aufgabe: riglink-server Web-UI Fix

## Was fehlt (geprüft per curl)
- toggle-group: 0 (Demo hat viele)
- setup-card: 0
- setup-columns: 0  
- Hamburger muss LINKS in der Nav sein (wie Demo)

## Builder-Aufgaben

### 1. style.css von Demo kopieren
cp /mnt/watcher/../RigLink/docs/style.css /opt/riglink/static/style.css
# Falls /mnt/watcher/../RigLink nicht existiert:
find /mnt/watcher -name 'style.css' 2>/dev/null
# Oder einfach die CSS-Variablen aus der Demo-Seite übernehmen

### 2. index.html neu schreiben
Die Seite braucht:
- Hamburger-Button LINKS (nicht rechts!)
- 4 Overlays: Radio Setup, Audio Setup, Status, Theme
- Radio Setup mit .setup-columns + .setup-card + .toggle-group (wie Demo)
- Audio Setup: NUR TRX Mic + TRX Speaker (KEIN PC-Audio)
- Dynamic Theme: JS lädt /api/theme und setzt CSS-Variablen

### 3. Flask /api/theme Endpoint
@app.route('/api/theme')
def get_theme():
    return jsonify({'teal': '#06c6a4', 'bg': '#0d0d1a', 'bg_card': '#151528'})

## Verifikation
curl http://localhost/ | grep -c toggle-group  # soll > 10 sein
curl http://localhost/ | grep hamburger         # soll links im nav sein

## Tester meldet in /mnt/watcher/riglink_server/TODO.md
