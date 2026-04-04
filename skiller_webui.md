# Builder-Plan: RigLink Web-UI Fix

## Kontext
Die aktuelle Web-UI (`/opt/riglink/templates/index.html`) ist funktional, aber weicht
von der Demo-Vorgabe ab. Es fehlen die CSS-Klassen `toggle-group`, `setup-card` und
`setup-columns`. Außerdem zeigt das Audio-Setup zu viele Felder und der `/api/theme`
Endpoint fehlt in `server.py`.

## IST-Zustand (geprüft)
| Kriterium | Soll | Ist |
|-----------|------|-----|
| `toggle-group` Elemente | > 10 | 0 |
| `setup-card` Elemente | > 0 | 0 |
| `setup-columns` Elemente | > 0 | 0 |
| Hamburger Position | LINKS | LINKS (OK) |
| Audio-Felder | 2 (TRX Mic, TRX Speaker) | 4 (PC Mic, TRX Mic, TRX Spk, PC Spk) |
| `/api/theme` Endpoint | vorhanden | fehlt |
| Dynamic Theme (JS -> CSS-Vars) | ja | nein (hardcoded THEMES-Objekt) |

## Dateien die geändert werden müssen
1. `/opt/riglink/templates/index.html` — HTML + CSS + JS
2. `/opt/riglink/server.py` — neuer `/api/theme` Endpoint

---

## Aufgabe 1: `/api/theme` Endpoint in server.py

**Datei:** `/opt/riglink/server.py`
**Wo:** Nach dem bestehenden `/api/config` Block (ca. Zeile 695), VOR dem `if __name__` Block.

**Code einfügen:**
```python
@app.route("/api/theme")
def get_theme():
    """Theme-Farben als JSON — wird von der UI beim Laden abgerufen."""
    cfg = load_config()
    theme = cfg.get("theme", {})
    return jsonify({
        "teal":    theme.get("teal", "#06c6a4"),
        "bg":      theme.get("bg", "#0d0d1a"),
        "bg_card": theme.get("bg_card", "#151528"),
        "bg_input": theme.get("bg_input", "#1a1a30"),
        "border":  theme.get("border", "#2a2a45"),
        "text":    theme.get("text", "#e0e0e0"),
        "dim":     theme.get("dim", "#888888"),
    })


@app.route("/api/theme/save", methods=["POST"])
def save_theme():
    """Theme-Farben speichern."""
    data = request.get_json(silent=True) or {}
    ok = save_config({"theme": data})
    return jsonify({"ok": ok})
```

---

## Aufgabe 2: CSS-Klassen in index.html hinzufügen

**Datei:** `/opt/riglink/templates/index.html`
**Wo:** Im `<style>` Block, am Ende (vor `</style>`).

**Folgende CSS-Klassen hinzufügen:**

```css
/* ── Setup-Columns (2-Spalten-Layout im Radio-Setup) ── */
.setup-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
@media (max-width: 540px) {
  .setup-columns { grid-template-columns: 1fr; }
}

/* ── Setup-Card (Untergruppen in Setup-Overlays) ── */
.setup-card {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.setup-card .card-label {
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

/* ── Toggle-Group (On/Off Schalter-Gruppen) ── */
.toggle-group {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.toggle-group:last-child { border-bottom: none; }
.toggle-group .tg-label {
  font-size: 0.88rem;
  color: var(--text);
}
.toggle-group .tg-hint {
  font-size: 0.7rem;
  color: var(--dim);
  margin-top: 2px;
}
.toggle-group .tg-switch {
  position: relative;
  width: 44px; height: 24px;
  background: var(--border);
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.2s;
  border: none;
  flex-shrink: 0;
}
.toggle-group .tg-switch::after {
  content: '';
  position: absolute;
  top: 3px; left: 3px;
  width: 18px; height: 18px;
  background: var(--text);
  border-radius: 50%;
  transition: transform 0.2s;
}
.toggle-group .tg-switch.on {
  background: var(--teal);
}
.toggle-group .tg-switch.on::after {
  transform: translateX(20px);
}
```

**Gleichzeitig:** Die bestehende `.two-col` Klasse und `.col-title` NICHT entfernen —
sie kann als Alias bleiben. Aber im HTML die neuen Klassen verwenden.

---

## Aufgabe 3: Radio-Setup Overlay umbauen

**Datei:** `/opt/riglink/templates/index.html`
**Wo:** Den Inhalt von `<div class="overlay" id="ov-radio">` ersetzen.

**Neues HTML (innerhalb overlay-box):**

```html
<button class="overlay-x" onclick="closeAll()">&times;</button>
<div class="overlay-head">Radio Setup</div>

<div class="setup-columns">
  <!-- Linke Spalte: CAT Control -->
  <div>
    <div class="setup-card">
      <div class="card-label">CAT Control</div>

      <div class="field">
        <label>Serial Port</label>
        <select id="cfg-port"><option value="">Lade&hellip;</option></select>
      </div>
      <div class="field">
        <label>Baud Rate</label>
        <select id="cfg-baud">
          <option value="4800">4800</option>
          <option value="9600">9600</option>
          <option value="19200">19200</option>
          <option value="38400">38400</option>
          <option value="57600">57600</option>
          <option value="115200" selected>115200</option>
        </select>
      </div>
      <div class="field">
        <label>Data Bits</label>
        <select id="cfg-databits">
          <option value="7">7</option>
          <option value="8" selected>8</option>
        </select>
      </div>
      <div class="field">
        <label>Stop Bits</label>
        <select id="cfg-stopbits">
          <option value="1" selected>1</option>
          <option value="2">2</option>
        </select>
      </div>
    </div>

    <div class="setup-card">
      <div class="card-label">Erweitert</div>
      <div class="toggle-group">
        <div>
          <div class="tg-label">Handshake RTS/CTS</div>
          <div class="tg-hint">Hardware Flow Control</div>
        </div>
        <button class="tg-switch" id="tg-rts" onclick="tgToggle(this)"></button>
      </div>
      <div class="toggle-group">
        <div>
          <div class="tg-label">XON/XOFF</div>
          <div class="tg-hint">Software Flow Control</div>
        </div>
        <button class="tg-switch" id="tg-xonxoff" onclick="tgToggle(this)"></button>
      </div>
      <div class="field" style="margin-top:10px">
        <label>CI-V Adresse</label>
        <input type="text" id="cfg-civ" value="0xA4" placeholder="0xA4 (IC-705)" />
      </div>
    </div>
  </div>

  <!-- Rechte Spalte: Transceiver + PTT -->
  <div>
    <div class="setup-card">
      <div class="card-label">Transceiver</div>
      <div class="field">
        <label>Hersteller</label>
        <select id="cfg-manufacturer">
          <option value="icom" selected>Icom</option>
          <option value="yaesu">Yaesu</option>
          <option value="kenwood">Kenwood</option>
          <option value="elecraft">Elecraft</option>
        </select>
      </div>
      <div class="field">
        <label>Modell</label>
        <input type="text" id="cfg-model" value="IC-705" />
      </div>
      <div class="field">
        <label>Hamlib Model-ID</label>
        <input type="text" id="cfg-hamlib-id" value="3085" />
      </div>
    </div>

    <div class="setup-card">
      <div class="card-label">PTT Konfiguration</div>
      <div class="toggle-group">
        <div>
          <div class="tg-label">CAT PTT</div>
          <div class="tg-hint">Software-PTT via CI-V</div>
        </div>
        <button class="tg-switch on" id="tg-ptt-cat" onclick="tgToggle(this)"></button>
      </div>
      <div class="toggle-group">
        <div>
          <div class="tg-label">VOX</div>
          <div class="tg-hint">Voice-Activated Transmit</div>
        </div>
        <button class="tg-switch" id="tg-ptt-vox" onclick="tgToggle(this)"></button>
      </div>
      <div class="toggle-group">
        <div>
          <div class="tg-label">RTS Signal</div>
          <div class="tg-hint">Hardware-PTT via RTS-Pin</div>
        </div>
        <button class="tg-switch" id="tg-ptt-rts" onclick="tgToggle(this)"></button>
      </div>
      <div class="toggle-group">
        <div>
          <div class="tg-label">DTR Signal</div>
          <div class="tg-hint">Hardware-PTT via DTR-Pin</div>
        </div>
        <button class="tg-switch" id="tg-ptt-dtr" onclick="tgToggle(this)"></button>
      </div>
    </div>
  </div>
</div>

<div class="btn-row">
  <button class="btn btn-save" onclick="cfgSave()">Speichern</button>
  <button class="btn" onclick="cfgTestCAT()">Test CAT</button>
  <button class="btn" onclick="cfgTestPTT()">Test PTT</button>
  <span class="btn-msg" id="radio-msg"></span>
</div>
```

**Toggle-Logik (im `<script>` Block hinzufügen):**
```javascript
function tgToggle(el) {
  el.classList.toggle('on');
}
```

---

## Aufgabe 4: Audio-Setup auf TRX-only reduzieren

**Datei:** `/opt/riglink/templates/index.html`
**Wo:** `<div class="overlay" id="ov-audio">` — Inhalt ersetzen.

**Neues HTML:**
```html
<button class="overlay-x" onclick="closeAll()">&times;</button>
<div class="overlay-head">Audio Setup</div>

<div class="setup-card">
  <div class="card-label">TRX Audio-Routing (PipeWire / ALSA)</div>

  <div class="toggle-group">
    <div>
      <div class="tg-label">Auto-Detect</div>
      <div class="tg-hint">USB-Soundkarte automatisch erkennen</div>
    </div>
    <button class="tg-switch on" id="tg-audio-auto" onclick="tgToggle(this)"></button>
  </div>

  <div class="field" style="margin-top:14px">
    <label>TRX Mikrofon-Eingang (TX-Ziel)</label>
    <select id="a-trx-mic"><option value="">Lade&hellip;</option></select>
  </div>
  <div class="field">
    <label>TRX Lautsprecher (RX-Quelle)</label>
    <select id="a-trx-spk"><option value="">Lade&hellip;</option></select>
  </div>
</div>

<div class="setup-card">
  <div class="card-label">Streaming</div>
  <div class="toggle-group">
    <div>
      <div class="tg-label">RX-Audio aktiv</div>
      <div class="tg-hint">TRX-Empfang aufnehmen</div>
    </div>
    <button class="tg-switch" id="tg-rx-active" onclick="toggleRxStream(this)"></button>
  </div>
  <div class="toggle-group">
    <div>
      <div class="tg-label">TX-Audio aktiv</div>
      <div class="tg-hint">Audio an TRX senden</div>
    </div>
    <button class="tg-switch" id="tg-tx-active" onclick="toggleTxStream(this)"></button>
  </div>
</div>

<div class="btn-row">
  <button class="btn btn-save" onclick="audioSave()">Speichern</button>
  <span class="btn-msg" id="audio-msg"></span>
</div>
```

**JS für Audio-Streaming-Toggles (im `<script>` Block):**
```javascript
async function toggleRxStream(el) {
  const on = !el.classList.contains('on');
  el.classList.toggle('on', on);
  await fetch('/api/audio/rx/' + (on ? 'start' : 'stop'), { method: 'POST' });
}

async function toggleTxStream(el) {
  const on = !el.classList.contains('on');
  el.classList.toggle('on', on);
  await fetch('/api/audio/tx/' + (on ? 'start' : 'stop'), { method: 'POST' });
}
```

**JS `loadNodes()` anpassen — nur noch 2 Selects befüllen:**
```javascript
async function loadNodes() {
  try {
    const d = await (await fetch('/api/audio/nodes')).json();
    fillSel('a-trx-mic', d.sinks||[],   '-- Nicht zugewiesen --');
    fillSel('a-trx-spk', d.sources||[], '-- Nicht zugewiesen --');
    try {
      const c = await (await fetch('/api/config')).json();
      const a = c.audio || {};
      if (a.trx_mic) setSel('a-trx-mic', a.trx_mic);
      if (a.trx_spk) setSel('a-trx-spk', a.trx_spk);
    } catch(e) {}
  } catch(e) {
    ['a-trx-mic','a-trx-spk'].forEach(id =>
      $(id).innerHTML = '<option>Fehler</option>');
  }
}
```

**JS `audioSave()` anpassen — nur TRX-Felder:**
```javascript
async function audioSave() {
  try {
    const d = await (await fetch('/api/config/save', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ audio: {
        trx_mic: $('a-trx-mic').value,
        trx_spk: $('a-trx-spk').value,
      }}),
    })).json();
    msg('audio-msg', d.ok ? 'Gespeichert!' : 'Fehler', d.ok);
  } catch(e) { msg('audio-msg', 'Verbindungsfehler', false); }
}
```

---

## Aufgabe 5: Dynamic Theme via /api/theme

**Datei:** `/opt/riglink/templates/index.html`
**Wo:** Im `<script>` Block — `applyTheme()` und THEMES-Objekt ersetzen.

**Neuer Code:**
```javascript
/* ── Theme — dynamisch via /api/theme ────────────────────────────────────── */
async function loadTheme() {
  try {
    const d = await (await fetch('/api/theme')).json();
    const r = document.documentElement.style;
    if (d.teal)     r.setProperty('--teal', d.teal);
    if (d.bg)       r.setProperty('--bg', d.bg);
    if (d.bg_card)  r.setProperty('--bg-card', d.bg_card);
    if (d.bg_input) r.setProperty('--bg-input', d.bg_input);
    if (d.border)   r.setProperty('--border', d.border);
    if (d.text)     r.setProperty('--text', d.text);
    if (d.dim)      r.setProperty('--dim', d.dim);
  } catch(e) {
    console.warn('Theme konnte nicht geladen werden:', e);
  }
}

function applyTheme(t) {
  const presets = {
    dark:  { teal:'#06c6a4', bg:'#0d0d1a', bg_card:'#151528', bg_input:'#1a1a30',
             border:'#2a2a45', text:'#e0e0e0', dim:'#888' },
    light: { teal:'#06c6a4', bg:'#f0f0f5', bg_card:'#ffffff', bg_input:'#f5f5fa',
             border:'#d0d0d8', text:'#1a1a2e', dim:'#666' },
  };
  const v = presets[t];
  const r = document.documentElement.style;
  Object.entries(v).forEach(([k, val]) => {
    const prop = k === 'teal' ? '--teal' : '--' + k.replace(/_/g, '-');
    r.setProperty(prop, val);
  });
  $('t-dark').classList.toggle('active', t === 'dark');
  $('t-light').classList.toggle('active', t === 'light');
  // Speichern
  fetch('/api/theme/save', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(v),
  });
}

// Beim Laden Theme von API holen
loadTheme();
```

**Das bestehende `THEMES`-Objekt und die alte `applyTheme()`-Funktion entfernen.**

---

## Aufgabe 6: Willkommens-Text korrigieren

**Datei:** `/opt/riglink/templates/index.html`
**Wo:** `<div class="welcome-hint">` — den Text "oben rechts" auf "oben links" ändern,
da der Hamburger links ist.

```html
Über das <strong>Menü &#9776;</strong> oben links konfigurierst du ...
```

---

## Zusammenfassung der Änderungen

| # | Datei | Was | Typ |
|---|-------|-----|-----|
| 1 | server.py | `/api/theme` + `/api/theme/save` Endpoints | Neu |
| 2 | index.html CSS | `.setup-columns`, `.setup-card`, `.toggle-group` Klassen | Neu |
| 3 | index.html HTML | Radio-Setup mit neuen Klassen + toggle-groups | Umbau |
| 4 | index.html HTML | Audio-Setup: nur TRX Mic + TRX Speaker + Streaming-Toggles | Umbau |
| 5 | index.html JS | Dynamic Theme via `/api/theme`, alte THEMES entfernen | Umbau |
| 6 | index.html HTML | "oben rechts" -> "oben links" | Fix |

## Verifikation (Tester-Kriterien)

```bash
# Nach dem Build muss gelten:
curl -s http://localhost/ | grep -c 'toggle-group'    # >= 10
curl -s http://localhost/ | grep -c 'setup-card'      # >= 4
curl -s http://localhost/ | grep -c 'setup-columns'   # >= 1
curl -s http://localhost/ | grep 'hamburger'           # im Header, erstes Kind
curl -s http://localhost/ | grep -c 'a-pc-mic'         # == 0 (entfernt!)
curl -s http://localhost/ | grep -c 'a-pc-spk'         # == 0 (entfernt!)
curl -s http://localhost/api/theme | python3 -m json.tool  # JSON mit teal, bg, etc.
```

## Kette
- **Skiller** (dieses Dokument) -> DONE
- **Builder** -> Setzt die 6 Aufgaben um
- **Tester** -> Verifiziert mit den curl-Befehlen oben und meldet in `/mnt/watcher/riglink_server/TODO.md`
