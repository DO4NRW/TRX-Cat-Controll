/**
 * RigLink Demo — Liest Theme aus configs/theme.json, simuliert Wasserfall + S-Meter
 */

const THEME_URL = 'https://raw.githubusercontent.com/DO4NRW/RigLink/main/configs/theme.json';
const REPORT_URL = 'https://raport.pcore.de/api/report';
const HMAC_SECRET = 'RigLink_Report_V2_DO4NRW';

// Web-Report an den Server senden
async function sendWebReport(title, body) {
    try {
        // HMAC-SHA256 signieren
        const ts = Math.floor(Date.now() / 1000).toString();
        const enc = new TextEncoder();
        const key = await crypto.subtle.importKey('raw', enc.encode(HMAC_SECRET),
            { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
        const sigBuf = await crypto.subtle.sign('HMAC', key, enc.encode(`${ts}:${body}`));
        const sig = Array.from(new Uint8Array(sigBuf)).map(b => b.toString(16).padStart(2, '0')).join('').substring(0, 16);

        const resp = await fetch(REPORT_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, body, ts, sig })
        });
        return await resp.json();
    } catch (e) {
        console.warn('Report senden fehlgeschlagen:', e);
        return null;
    }
}

// Browser-Info sammeln
function getBrowserInfo() {
    return [
        `Browser: ${navigator.userAgent}`,
        `Platform: ${navigator.platform}`,
        `WebSerial: ${('serial' in navigator) ? 'ja' : 'nein'}`,
        `Sprache: ${navigator.language}`,
        `Bildschirm: ${screen.width}x${screen.height}`,
        `Fenster: ${window.innerWidth}x${window.innerHeight}`,
    ].join('\n');
}

// Error-Handler: fängt alle unbehandelten Fehler
let errorLog = [];
window.addEventListener('error', e => {
    errorLog.push(`[${new Date().toISOString()}] ${e.message} (${e.filename}:${e.lineno})`);
});
window.addEventListener('unhandledrejection', e => {
    errorLog.push(`[${new Date().toISOString()}] Promise: ${e.reason}`);
});

// State
let currentFreq = 14200000;
let currentMode = 'USB';
let connected = false;
let pttActive = false;
let smeterValue = 0;
let spectrum = new Float32Array(475);
let wfData = [];
const WF_LINES = 200;

// Demo-Daten Playback
let demoData = null;
let demoIndex = 0;
let demoPlaying = true;

// Waterfall Palette (SDR-Style)
const PALETTE_STOPS = [
    [0.00, [8, 12, 35]],
    [0.05, [10, 20, 70]],
    [0.15, [0, 40, 160]],
    [0.30, [0, 150, 180]],
    [0.45, [0, 220, 100]],
    [0.60, [180, 220, 0]],
    [0.75, [255, 140, 0]],
    [0.88, [255, 40, 0]],
    [1.00, [255, 255, 255]],
];

let palette = [];

function buildPalette() {
    palette = [];
    for (let i = 0; i < 256; i++) {
        const frac = i / 255;
        let lo = PALETTE_STOPS[0], hi = PALETTE_STOPS[PALETTE_STOPS.length - 1];
        for (let j = 0; j < PALETTE_STOPS.length - 1; j++) {
            if (frac >= PALETTE_STOPS[j][0] && frac <= PALETTE_STOPS[j + 1][0]) {
                lo = PALETTE_STOPS[j];
                hi = PALETTE_STOPS[j + 1];
                break;
            }
        }
        const t = hi[0] === lo[0] ? 0 : (frac - lo[0]) / (hi[0] - lo[0]);
        palette.push([
            Math.round(lo[1][0] + t * (hi[1][0] - lo[1][0])),
            Math.round(lo[1][1] + t * (hi[1][1] - lo[1][1])),
            Math.round(lo[1][2] + t * (hi[1][2] - lo[1][2]))
        ]);
    }
}

// Parse rgba string → [r,g,b,a]
function parseRGBA(s) {
    const m = s.match(/rgba?\((\d+),\s*(\d+),\s*(\d+),?\s*(\d*)\)/);
    if (!m) return [128, 128, 128, 255];
    return [+m[1], +m[2], +m[3], m[4] ? +m[4] : 255];
}

// Load theme.json and apply as CSS variables
async function loadTheme() {
    try {
        const resp = await fetch(THEME_URL);
        const theme = await resp.json();
        const root = document.documentElement;
        for (const [key, val] of Object.entries(theme)) {
            if (key.startsWith('_')) continue;
            const [r, g, b, a] = parseRGBA(val);
            const cssKey = '--' + key.replace(/_/g, '-');
            root.style.setProperty(cssKey, `rgba(${r},${g},${b},${a / 255})`);
        }
    } catch (e) {
        console.warn('Theme laden fehlgeschlagen, nutze Defaults:', e);
        applyDefaultTheme();
    }
}

function applyDefaultTheme() {
    const defaults = {
        '--bg-dark': '#1a1a1a', '--bg-mid': '#2a2a2a', '--bg-light': '#3a3a3a',
        '--bg-button': '#3d3d3d', '--bg-button-hover': '#4a4a4a',
        '--border': '#555', '--border-hover': '#888',
        '--accent': '#06c6a4', '--text': '#fff', '--text-secondary': '#ccc',
        '--text-muted': '#aaa', '--smeter-bar': '#06c6a4', '--tx-bar': '#06c6a4',
        '--smeter-label-inactive': '#888',
        '--ptt-rx-bg': '#3d3d3d', '--ptt-rx-border': '#555',
        '--ptt-tx-bg': '#d32f2f', '--ptt-tx-border': '#ff6659',
        '--slider-handle': '#06c6a4',
    };
    const root = document.documentElement;
    for (const [k, v] of Object.entries(defaults)) root.style.setProperty(k, v);
}

// Simulate spectrum with random signals
function generateSpectrum() {
    const noise = 3;
    for (let i = 0; i < 475; i++) {
        spectrum[i] = spectrum[i] * 0.7 + (Math.random() * noise) * 0.3;
    }
    // Simulate some signals
    const signals = [
        { pos: 100, width: 5, strength: 80 + Math.random() * 40 },
        { pos: 237, width: 3, strength: 120 + Math.random() * 30 },
        { pos: 350, width: 8, strength: 50 + Math.random() * 60 },
        { pos: 180, width: 2, strength: 30 + Math.random() * 20 },
    ];
    for (const sig of signals) {
        for (let i = -sig.width; i <= sig.width; i++) {
            const idx = sig.pos + i;
            if (idx >= 0 && idx < 475) {
                const falloff = 1 - Math.abs(i) / (sig.width + 1);
                spectrum[idx] = Math.max(spectrum[idx],
                    sig.strength * falloff * (0.8 + Math.random() * 0.4));
            }
        }
    }
}

// Draw waterfall + spectrum
function drawWaterfall() {
    const canvas = document.getElementById('waterfall');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    // Canvas nur resizen wenn sich die Größe ändert (verhindert Buffer-Verlust)
    const cw = canvas.parentElement.clientWidth;
    const ch = canvas.parentElement.clientHeight;
    if (canvas.width !== cw || canvas.height !== ch) {
        canvas.width = cw;
        canvas.height = ch;
        // Wasserfall-Buffer zurücksetzen bei Resize
        window._wfCanvas = null;
    }
    const w = canvas.width;
    const h = canvas.height;
    if (w <= 0 || h <= 0) return;
    ctx.imageSmoothingEnabled = true;

    const specFrac = 0.35;
    const freqBarH = 18;
    const specH = Math.floor((h - freqBarH) * specFrac);
    const wfH = h - specH - freqBarH;

    // Spectrum background
    ctx.fillStyle = 'rgb(18, 22, 30)';
    ctx.fillRect(0, 0, w, specH);

    // Grid
    ctx.strokeStyle = 'rgb(30, 40, 55)';
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i++) {
        const y = Math.floor(specH * i / 4);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }
    for (let i = 1; i < 8; i++) {
        const x = Math.floor(w * i / 8);
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, specH); ctx.stroke();
    }

    // Spectrum line + fill
    const peak = Math.max(...spectrum);
    if (peak > 0) {
        const scale = 0.85 / Math.max(peak, 1);
        const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#06c6a4';

        // Fill
        ctx.fillStyle = accent + '30';
        ctx.beginPath();
        ctx.moveTo(0, specH);
        for (let px = 0; px < w; px++) {
            const idx = Math.min(474, Math.floor(px * 475 / w));
            const normed = Math.min(1, spectrum[idx] * scale);
            const y = Math.max(1, Math.floor(specH * (1 - normed)));
            ctx.lineTo(px, y);
        }
        ctx.lineTo(w, specH);
        ctx.fill();

        // Line
        ctx.strokeStyle = accent;
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let px = 0; px < w; px++) {
            const idx = Math.min(474, Math.floor(px * 475 / w));
            const normed = Math.min(1, spectrum[idx] * scale);
            const y = Math.max(1, Math.floor(specH * (1 - normed)));
            if (px === 0) ctx.moveTo(px, y);
            else ctx.lineTo(px, y);
        }
        ctx.stroke();
    }

    // Freq bar
    const freqY = specH;
    ctx.fillStyle = 'rgb(20, 25, 35)';
    ctx.fillRect(0, freqY, w, freqBarH);

    const spanHz = currentSpanHz;
    const startFreq = currentFreq - spanHz / 2;
    const endFreq = currentFreq + spanHz / 2;
    ctx.font = '9px Roboto, sans-serif';
    ctx.fillStyle = 'rgb(160, 170, 180)';
    for (let i = 0; i <= 5; i++) {
        const freq = startFreq + (endFreq - startFreq) * i / 5;
        const x = Math.floor(w * i / 5);
        const label = (freq / 1e6).toFixed(3);
        if (i === 0) ctx.fillText(label, x + 3, freqY + 13);
        else if (i === 5) ctx.fillText(label, x - 48, freqY + 13);
        else ctx.fillText(label, x - 22, freqY + 13);
    }

    // Waterfall
    const wfY = freqY + freqBarH;

    // Offscreen Wasserfall in Scope-Auflösung (475 x 200)
    const WF_W = 475;
    const WF_H = 200;
    if (!window._wfCanvas) {
        window._wfCanvas = document.createElement('canvas');
        window._wfCanvas.width = WF_W;
        window._wfCanvas.height = WF_H;
        const wc = window._wfCanvas.getContext('2d');
        wc.fillStyle = 'rgb(8, 12, 35)';
        wc.fillRect(0, 0, WF_W, WF_H);
    }
    const wfCtx = window._wfCanvas.getContext('2d');

    // Shift alles 1px nach unten (in nativer Auflösung)
    wfCtx.drawImage(window._wfCanvas, 0, 0, WF_W, WF_H - 1, 0, 1, WF_W, WF_H - 1);

    // Neue Zeile oben — 1 Pixel pro Scope-Punkt (475px breit)
    const lineData = wfCtx.createImageData(WF_W, 1);
    const px = lineData.data;
    for (let i = 0; i < WF_W; i++) {
        let val = spectrum[i] || 0;
        val = Math.max(0, (val - 3) * 3.0);
        const ci = Math.min(255, Math.max(0, Math.floor(val)));
        const [r, g, b] = palette[ci];
        const off = i * 4;
        px[off] = r; px[off + 1] = g; px[off + 2] = b; px[off + 3] = 255;
    }
    wfCtx.putImageData(lineData, 0, 0);

    // Skaliert auf Canvas blitten (Browser interpoliert smooth)
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(window._wfCanvas, 0, 0, WF_W, WF_H, 0, wfY, w, wfH);

    // Center marker + passband
    const cx = Math.floor(w / 2);
    ctx.strokeStyle = 'rgba(6, 198, 164, 0.4)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();

    // Passband
    const bwHz = currentMode === 'FM' ? 15000 : 2700;
    const bwPx = Math.floor(bwHz / spanHz * w);
    let bx;
    if (currentMode === 'USB' || currentMode === 'DATA') bx = cx;
    else if (currentMode === 'LSB') bx = cx - bwPx;
    else bx = cx - Math.floor(bwPx / 2);

    ctx.fillStyle = 'rgba(6, 198, 164, 0.15)';
    ctx.fillRect(bx, 0, bwPx, h);
    ctx.strokeStyle = 'rgba(6, 198, 164, 0.5)';
    ctx.beginPath(); ctx.moveTo(bx, 0); ctx.lineTo(bx, h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx + bwPx, 0); ctx.lineTo(bx + bwPx, h); ctx.stroke();
}

// S-Meter — gleiche Berechnung wie ic705_ui.py
const S9_RAW = 130;
const MAX_RAW = 241;
const S9_STEPS = ['S9+20', 'S9+40', 'S9+60'];

function updateSMeter() {
    // smeterValue = Raw-Wert vom TRX (0-241)
    const val = smeterValue;
    let sStr, frac;

    if (val <= S9_RAW) {
        const sNum = val * 9 / Math.max(S9_RAW, 1);
        sStr = `S${Math.min(9, Math.round(sNum))}`;
        frac = sNum / 13;
    } else {
        const dbOver = (val - S9_RAW) / Math.max(MAX_RAW - S9_RAW, 1) * 60;
        sStr = 'S9';
        for (let i = 0; i < S9_STEPS.length; i++) {
            if (dbOver >= (i + 0.5) * (60 / S9_STEPS.length)) {
                sStr = S9_STEPS[i];
            }
        }
        frac = (9 + dbOver / 60 * 4) / 13;
    }

    const barPct = Math.min(100, frac * 100);
    document.getElementById('smeter-bar').style.width = barPct + '%';
    document.getElementById('smeter-info').textContent = `S-METER: ${sStr} | P1`;
}

// Frequency display
function updateFreqDisplay() {
    const mhz = Math.floor(currentFreq / 1e6);
    const khz = Math.floor((currentFreq % 1e6) / 1e3);
    const hz = currentFreq % 1000;
    document.getElementById('freq-input').placeholder =
        `${mhz}.${String(khz).padStart(3, '0')}.${String(hz).padStart(3, '0')}`;
}

// Mode buttons
function setupModeButtons() {
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMode = btn.dataset.mode;
        });
    });
}

// DSP buttons (toggle)
function setupDSPButtons() {
    document.querySelectorAll('.dsp-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            btn.classList.toggle('active');
        });
    });
}

// PTT
function setupPTT() {
    const btn = document.getElementById('btn-ptt');
    btn.addEventListener('mousedown', () => {
        pttActive = true;
        btn.textContent = 'TX';
        btn.classList.add('tx');
    });
    btn.addEventListener('mouseup', () => {
        pttActive = false;
        btn.textContent = 'RX (SPACE)';
        btn.classList.remove('tx');
    });
    // Space key
    document.addEventListener('keydown', e => {
        if (e.code === 'Space' && !e.repeat && document.activeElement.tagName !== 'INPUT') {
            e.preventDefault();
            pttActive = true;
            btn.textContent = 'TX';
            btn.classList.add('tx');
        }
    });
    document.addEventListener('keyup', e => {
        if (e.code === 'Space') {
            pttActive = false;
            btn.textContent = 'RX (SPACE)';
            btn.classList.remove('tx');
        }
    });
}

// Connect button — Web Serial wenn verfügbar, sonst Demo-Mode
let civ = null;
const hasWebSerial = 'serial' in navigator;

function setupConnect() {
    const btn = document.getElementById('btn-connect');
    const status = document.getElementById('status-text');
    const bar = document.querySelector('.status-bar');

    btn.addEventListener('click', async () => {
        if (connected) {
            // Disconnect
            if (civ) await civ.disconnect();
            connected = false;
            btn.classList.remove('connected');
            bar.classList.remove('connected');
            status.textContent = 'SYSTEM READY';
            return;
        }

        if (hasWebSerial) {
            // Echte Serial-Verbindung
            const cfg = getSerialConfig();
            status.textContent = `Verbinde (${cfg.baud} baud)...`;
            civ = new IcomCIV();
            civ.civAddress = cfg.civAddress;

            civ.onFrequency = (hz) => {
                currentFreq = hz;
                updateFreqDisplay();
            };
            civ.onMode = (mode) => {
                currentMode = mode;
                document.querySelectorAll('.mode-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.mode === mode);
                });
            };
            civ.onSMeter = (raw) => {
                smeterValue = smeterValue * 0.8 + raw * 0.2; // Smoothing wie App
            };
            civ.onPower = (raw) => {
                const slider = document.getElementById('pwr-slider');
                const label = document.getElementById('pwr-label');
                slider.value = raw;
                label.textContent = `PWR: ${(raw * 10 / 255).toFixed(1)}W`;
            };
            civ.onSpectrum = (data, center, span) => {
                // Echte Scope-Daten statt simulierte
                for (let i = 0; i < 475; i++) spectrum[i] = data[i];
                if (center > 0) currentFreq = center;
                liveScope = true;
            };
            civ.onConnect = () => {
                connected = true;
                btn.classList.add('connected');
                bar.classList.add('connected');
                status.textContent = 'CAT: Verbunden (Web Serial) — READ ONLY';
            };
            civ.onDisconnect = () => {
                connected = false;
                liveScope = false;
                btn.classList.remove('connected');
                bar.classList.remove('connected');
                status.textContent = 'SYSTEM READY';

                // Errors während der Session? Automatisch reporten
                if (errorLog.length > 0) {
                    const body = `## Web Demo Fehler\n\n## Browser\n\`\`\`\n${getBrowserInfo()}\n\`\`\`\n\n## Errors\n\`\`\`\n${errorLog.join('\n')}\n\`\`\``;
                    sendWebReport('[WEB] Fehler in Browser-Demo', body);
                    errorLog = [];
                }
            };

            const ok = await civ.connect(cfg.baud, cfg.stopBits);
            if (!ok) {
                status.textContent = 'Verbindung fehlgeschlagen';
                setTimeout(() => { status.textContent = 'SYSTEM READY'; }, 3000);
            }
        } else {
            // Demo-Mode (kein Web Serial)
            connected = !connected;
            btn.classList.toggle('connected', connected);
            bar.classList.toggle('connected', connected);
            status.textContent = connected ? 'DEMO MODE (kein Web Serial)' : 'SYSTEM READY';
        }
    });
}

let liveScope = false;

// Menu + Overlays
function setupSettings() {
    const menuBtn = document.querySelector('.menu-btn');
    const menuOverlay = document.getElementById('menu-overlay');
    const settingsOverlay = document.getElementById('settings-overlay');
    const audioOverlay = document.getElementById('audio-overlay');
    const themeOverlay = document.getElementById('theme-overlay');
    const rigSelect = document.getElementById('cfg-rig');
    const civInput = document.getElementById('cfg-civ');

    // Menü toggle
    menuBtn.addEventListener('click', () => {
        menuOverlay.style.display = menuOverlay.style.display === 'none' ? 'flex' : 'none';
    });
    menuOverlay.addEventListener('click', (e) => {
        if (e.target === menuOverlay) menuOverlay.style.display = 'none';
    });

    // Menü-Items → Overlays
    function openOverlay(overlay) {
        menuOverlay.style.display = 'none';
        overlay.style.display = 'flex';
    }
    document.getElementById('menu-radio').addEventListener('click', () => openOverlay(settingsOverlay));
    document.getElementById('menu-audio').addEventListener('click', () => openOverlay(audioOverlay));
    document.getElementById('menu-theme').addEventListener('click', () => openOverlay(themeOverlay));
    document.getElementById('menu-report').addEventListener('click', () => {
        menuOverlay.style.display = 'none';
        document.getElementById('contact-overlay').style.display = 'flex';
    });

    // Close Buttons
    document.getElementById('btn-settings-close').addEventListener('click', () => settingsOverlay.style.display = 'none');
    document.getElementById('btn-audio-close').addEventListener('click', () => audioOverlay.style.display = 'none');
    document.getElementById('btn-theme-close').addEventListener('click', () => themeOverlay.style.display = 'none');

    // Overlay schließen bei Klick außerhalb
    [settingsOverlay, audioOverlay, themeOverlay].forEach(ov => {
        ov.addEventListener('click', (e) => { if (e.target === ov) ov.style.display = 'none'; });
    });

    // Rig-Auswahl → CI-V Adresse
    rigSelect.addEventListener('change', () => {
        const addr = IcomCIV.RIG_ADDRESSES[rigSelect.value] || 0xA4;
        civInput.value = '0x' + addr.toString(16).toUpperCase();
    });

    // Theme-Wechsel live
    document.getElementById('cfg-theme').addEventListener('change', async (e) => {
        const themeName = e.target.value;
        const url = `https://raw.githubusercontent.com/DO4NRW/RigLink/main/configs/theme.json`;
        // Lade alle Presets aus theme.py? Nein — wir nutzen die theme.json + Override
        // Für die Demo: Theme-Name als Query an die URL oder hardcoded Presets
        try {
            const resp = await fetch(`https://raw.githubusercontent.com/DO4NRW/RigLink/main/core/theme.py`);
            const text = await resp.text();
            // Parse das Preset aus dem Python-Code (quick & dirty)
            const presetMatch = text.match(new RegExp(`"${themeName}":\\s*\\{([^}]+(?:\\{[^}]*\\}[^}]*)*)\\}`, 's'));
            if (presetMatch) {
                const block = presetMatch[1];
                const root = document.documentElement;
                const pairs = block.matchAll(/"(\w+)":\s*"(rgba\([^)]+\))"/g);
                for (const m of pairs) {
                    const cssKey = '--' + m[1].replace(/_/g, '-');
                    root.style.setProperty(cssKey, m[2]);
                }
            }
        } catch (err) {
            console.warn('Theme laden fehlgeschlagen:', err);
        }
    });
}

function getSerialConfig() {
    return {
        rig: document.getElementById('cfg-rig').value,
        baud: parseInt(document.getElementById('cfg-baud').value),
        stopBits: parseInt(document.getElementById('cfg-stopbits').value),
        civAddress: parseInt(document.getElementById('cfg-civ').value),
    };
}

// Step buttons
function setupStepButtons() {
    document.getElementById('btn-step-down').addEventListener('click', () => {
        const step = parseInt(document.getElementById('step-select').value);
        currentFreq -= step;
        updateFreqDisplay();
    });
    document.getElementById('btn-step-up').addEventListener('click', () => {
        const step = parseInt(document.getElementById('step-select').value);
        currentFreq += step;
        updateFreqDisplay();
    });
    document.getElementById('btn-set').addEventListener('click', () => {
        const input = document.getElementById('freq-input');
        const txt = input.value.trim().replace(/,/g, '.');
        const parts = txt.split('.');
        if (parts.length === 3) {
            currentFreq = parseInt(parts[0]) * 1e6 + parseInt(parts[1]) * 1e3 + parseInt(parts[2]);
        } else if (txt) {
            currentFreq = Math.round(parseFloat(txt) * 1e6);
        }
        input.value = '';
        updateFreqDisplay();
    });
}

// Span slider
const SPAN_VALUES = [
    { hz: 2500, label: '2.5 kHz' },
    { hz: 5000, label: '5 kHz' },
    { hz: 10000, label: '10 kHz' },
    { hz: 50000, label: '50 kHz' },
    { hz: 100000, label: '100 kHz' },
    { hz: 250000, label: '250 kHz' },
    { hz: 500000, label: '500 kHz' },
];
let currentSpanHz = 50000;

function setupSpan() {
    const slider = document.getElementById('span-slider');
    const label = document.getElementById('span-label');
    slider.addEventListener('input', () => {
        const idx = parseInt(slider.value);
        currentSpanHz = SPAN_VALUES[idx].hz;
        label.textContent = `SPAN: ${SPAN_VALUES[idx].label}`;
    });
}

// Power slider
function setupPower() {
    const slider = document.getElementById('pwr-slider');
    const label = document.getElementById('pwr-label');
    slider.addEventListener('input', () => {
        const w = (slider.value * 10 / 255).toFixed(1);
        label.textContent = `PWR: ${w}W`;
    });
}

// Waterfall click-to-tune
function setupWaterfallClick() {
    const canvas = document.getElementById('waterfall');
    canvas.style.cursor = 'crosshair';
    canvas.addEventListener('click', e => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const w = canvas.width;
        const spanHz = currentSpanHz;
        const startFreq = currentFreq - spanHz / 2;
        const step = parseInt(document.getElementById('step-select').value);
        let freq = startFreq + (x / w) * spanHz;
        freq = Math.round(freq / step) * step;
        currentFreq = freq;
        updateFreqDisplay();
    });
    canvas.addEventListener('wheel', e => {
        e.preventDefault();
        const step = parseInt(document.getElementById('step-select').value);
        const dir = e.deltaY < 0 ? 1 : -1;
        currentFreq += dir * step;
        updateFreqDisplay();
    });
}

// TX meter during PTT
function updateTXMeter() {
    const bar = document.getElementById('tx-bar');
    if (pttActive) {
        bar.style.width = (30 + Math.random() * 40) + '%';
    } else {
        bar.style.width = '0%';
    }
}

// Kontaktformular
function setupContact() {
    const overlay = document.getElementById('contact-overlay');
    const link = document.getElementById('link-contact');
    const closeBtn = document.getElementById('btn-contact-close');
    const sendBtn = document.getElementById('btn-contact-send');
    const status = document.getElementById('contact-status');

    link.addEventListener('click', (e) => { e.preventDefault(); overlay.style.display = 'flex'; });
    closeBtn.addEventListener('click', () => { overlay.style.display = 'none'; });
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.style.display = 'none'; });

    sendBtn.addEventListener('click', async () => {
        const name = document.getElementById('contact-name').value.trim();
        const email = document.getElementById('contact-email').value.trim();
        const msg = document.getElementById('contact-msg').value.trim();
        if (!msg) { status.textContent = 'Bitte Nachricht eingeben.'; return; }

        sendBtn.disabled = true;
        sendBtn.textContent = 'Sende...';

        const body = `## Kontaktformular (Web Demo)\n\n**Von:** ${name || 'Anonym'}\n**E-Mail:** ${email || 'nicht angegeben'}\n\n## Nachricht\n${msg}\n\n## Browser\n\`\`\`\n${getBrowserInfo()}\n\`\`\``;
        const result = await sendWebReport('[KONTAKT] ' + (name || 'Web Demo'), body);

        sendBtn.disabled = false;
        sendBtn.textContent = 'Senden';

        if (result && result.ok) {
            status.textContent = 'Nachricht gesendet! Danke.';
            document.getElementById('contact-msg').value = '';
            setTimeout(() => { overlay.style.display = 'none'; status.textContent = ''; }, 2000);
        } else {
            status.textContent = 'Fehler beim Senden. Bitte per E-Mail kontaktieren.';
        }
    });
}

// Demo-Daten laden
async function loadDemoData() {
    try {
        const resp = await fetch('demo_data.json');
        demoData = await resp.json();
        console.log(`Demo-Daten geladen: ${demoData.length} Frames`);
    } catch (e) {
        console.warn('Demo-Daten nicht verfügbar, nutze Simulation');
        demoData = null;
    }
}

// Demo-Frame abspielen
function playDemoFrame() {
    if (!demoData || demoData.length === 0) {
        generateSpectrum();
        return;
    }

    const frame = demoData[demoIndex];
    demoIndex = (demoIndex + 1) % demoData.length;

    if (frame.sp) {
        for (let i = 0; i < Math.min(475, frame.sp.length); i++) {
            spectrum[i] = spectrum[i] * 0.3 + frame.sp[i] * 0.7;
        }
    }
    if (frame.f) {
        currentFreq = frame.f;
        updateFreqDisplay();
    }
    if (frame.s !== undefined) {
        // Raw-Wert direkt (0-241, gleich wie ic705_ui.py)
        smeterValue = smeterValue * 0.8 + frame.s * 0.2; // Smoothing
    }
    if (frame.m) {
        currentMode = frame.m;
        document.querySelectorAll('.mode-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.mode === frame.m);
        });
    }
    if (frame.sc && frame.ss) {
        currentSpanHz = frame.ss;
    }
}

// Main loop
let frameSkip = 0;
function tick() {
    frameSkip++;
    if (!connected) {
        // Demo-Mode: echte aufgenommene Daten (alle 3 Frames = ~80ms wie App)
        if (frameSkip % 3 === 0) playDemoFrame();
        drawWaterfall();
    } else {
        if (frameSkip % 3 === 0) drawWaterfall();
    }
    updateSMeter();
    if (frameSkip % 2 === 0) updateTXMeter();
    requestAnimationFrame(tick);
}

// Init
async function init() {
    buildPalette();
    for (let i = 0; i < WF_LINES; i++) wfData.push(new Uint8Array(475));
    await loadTheme();
    await loadDemoData();
    updateFreqDisplay();
    setupSettings();
    setupModeButtons();
    setupDSPButtons();
    setupPTT();
    setupConnect();
    setupStepButtons();
    setupSpan();
    setupPower();
    setupWaterfallClick();
    // Kontaktformular
    setupContact();

    // Web Serial Hinweis
    const verLabel = document.getElementById('version-text');
    if (hasWebSerial) {
        verLabel.textContent = 'v2.0.8 — Web Serial Ready';
    } else {
        verLabel.textContent = 'v2.0.8 — DEMO (Chrome/Edge für CAT)';
    }

    tick();
}

init();
