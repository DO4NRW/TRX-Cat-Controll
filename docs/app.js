/**
 * RigLink Demo — Liest Theme aus configs/theme.json, simuliert Wasserfall + S-Meter
 */

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
let displaySpectrum = new Float32Array(475);
let wfData = [];
const WF_LINES = 200;
let spectrumChanged = false;
let lastWfTime = 0;

// UI State
let freqLocked = false;
let muted = false;
let wfHoverX = -1;
let currentSmeterStyle = 'segment';

// Demo-Daten Playback
let demoData = null;
let demoIndex = 0;
let demoPlaying = true;
let demoStartTime = 0;
let demoBaseTime = 0;

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

    const specFrac = 0.35;  // aus waterfall.py
    const freqBarH = 18;   // aus waterfall.py
    const specH = Math.floor((h - freqBarH) * specFrac);
    const wfH = h - specH - freqBarH;

    // Farben aus Theme (CSS-Variablen)
    const cs = getComputedStyle(document.documentElement);
    const wfBg = cs.getPropertyValue('--wf-bg').trim() || 'rgb(18, 22, 30)';
    const wfGrid = cs.getPropertyValue('--wf-grid').trim() || 'rgb(30, 40, 55)';
    const wfFreqBar = cs.getPropertyValue('--wf-freq-bar').trim() || 'rgb(20, 25, 35)';
    const wfFreqText = cs.getPropertyValue('--wf-freq-text').trim() || 'rgb(160, 170, 180)';
    const wfFreqTick = cs.getPropertyValue('--wf-freq-tick').trim() || 'rgb(60, 70, 80)';
    const accent = cs.getPropertyValue('--accent').trim() || '#06c6a4';

    // Spectrum background
    ctx.fillStyle = wfBg;
    ctx.fillRect(0, 0, w, specH);

    // Grid (4x8 wie Desktop)
    ctx.strokeStyle = wfGrid;
    ctx.lineWidth = 1;
    const dbLabels = ['-20', '-40', '-60'];
    ctx.font = '8px Consolas, monospace';
    for (let i = 1; i < 4; i++) {
        const y = Math.floor(specH * i / 4);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
        // dB-Skala Labels links
        ctx.fillStyle = wfFreqText;
        ctx.fillText(dbLabels[i - 1] || '', 3, y - 2);
    }
    for (let i = 1; i < 8; i++) {
        const x = Math.floor(w * i / 8);
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, specH); ctx.stroke();
    }

    // Parse accent für RGB-Komponenten
    const accentRGB = accent.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    const [aR, aG, aB] = accentRGB ? [+accentRGB[1], +accentRGB[2], +accentRGB[3]] : [6, 198, 164];

    // Spectrum line + gradient fill (wie Desktop waterfall.py)
    const peak = Math.max(...displaySpectrum);
    if (peak > 0) {
        const scale = 0.85 / Math.max(peak, 1);

        // Gradient Fill (alpha 0.12 unten → 0 oben, wie Desktop waterfall.py fill_color.setAlpha(30))
        const grad = ctx.createLinearGradient(0, 0, 0, specH);
        grad.addColorStop(0, `rgba(${aR},${aG},${aB},0)`);
        grad.addColorStop(1, `rgba(${aR},${aG},${aB},0.12)`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.moveTo(0, specH);
        for (let px = 0; px < w; px++) {
            const idx = Math.min(474, Math.floor(px * 475 / w));
            const normed = Math.min(1, displaySpectrum[idx] * scale);
            const y = Math.max(1, Math.floor(specH * (1 - normed)));
            ctx.lineTo(px, y);
        }
        ctx.lineTo(w, specH);
        ctx.fill();

        // Line (2px für bessere Sichtbarkeit)
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let px = 0; px < w; px++) {
            const idx = Math.min(474, Math.floor(px * 475 / w));
            const normed = Math.min(1, displaySpectrum[idx] * scale);
            const y = Math.max(1, Math.floor(specH * (1 - normed)));
            if (px === 0) ctx.moveTo(px, y);
            else ctx.lineTo(px, y);
        }
        ctx.stroke();
    }

    // Freq bar
    const freqY = specH;
    ctx.fillStyle = wfFreqBar;
    ctx.fillRect(0, freqY, w, freqBarH);
    ctx.strokeStyle = wfFreqTick;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, freqY); ctx.lineTo(w, freqY); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, freqY + freqBarH); ctx.lineTo(w, freqY + freqBarH); ctx.stroke();

    const spanHz = currentSpanHz;
    const startFreq = currentFreq - spanHz / 2;
    const endFreq = currentFreq + spanHz / 2;
    ctx.font = '9px Roboto, sans-serif';
    ctx.fillStyle = wfFreqText;
    for (let i = 0; i <= 5; i++) {
        const freq = startFreq + (endFreq - startFreq) * i / 5;
        const x = Math.floor(w * i / 5);
        const label = (freq / 1e6).toFixed(3);
        if (i === 0) ctx.fillText(label, x + 3, freqY + 13);
        else if (i === 5) ctx.fillText(label, x - 48, freqY + 13);
        else ctx.fillText(label, x - 22, freqY + 13);
        // Tick
        ctx.strokeStyle = wfFreqTick;
        ctx.beginPath(); ctx.moveTo(x, freqY); ctx.lineTo(x, freqY + 4); ctx.stroke();
        ctx.fillStyle = wfFreqText;
    }

    // Waterfall
    const wfY = freqY + freqBarH;

    // Offscreen Wasserfall in Canvas-Breite (dynamische Höhe)
    const wfBufH = Math.max(60, Math.round(wfH * 0.4));
    if (!window._wfCanvas || window._wfCanvas.width !== w || window._wfCanvas.height !== wfBufH) {
        window._wfCanvas = document.createElement('canvas');
        window._wfCanvas.width = w;
        window._wfCanvas.height = wfBufH;
        const wc = window._wfCanvas.getContext('2d');
        wc.fillStyle = 'rgb(8, 12, 35)';
        wc.fillRect(0, 0, w, wfBufH);
    }
    const wfCtx = window._wfCanvas.getContext('2d');

    // Shift alles 1px nach unten (mit Smoothing wie auf Main-Canvas)
    wfCtx.imageSmoothingEnabled = true;
    wfCtx.imageSmoothingQuality = 'high';
    wfCtx.drawImage(window._wfCanvas, 0, 0, w, wfBufH - 1, 0, 1, w, wfBufH - 1);

    // Neue Zeile oben — interpoliert auf Canvas-Breite
    const lineData = wfCtx.createImageData(w, 1);
    const px = lineData.data;
    for (let x = 0; x < w; x++) {
        // Lineare Interpolation zwischen Scope-Punkten
        const fIdx = x * 474 / w;
        const idx0 = Math.floor(fIdx);
        const idx1 = Math.min(474, idx0 + 1);
        const t = fIdx - idx0;
        const val0 = displaySpectrum[idx0] || 0;
        const val1 = displaySpectrum[idx1] || 0;
        let val = val0 + t * (val1 - val0);
        val = Math.max(0, (val - wfBlackLevel) * wfColorGain);
        const ci = Math.min(255, Math.max(0, Math.floor(val)));
        const [r, g, b] = palette[ci];
        const off = x * 4;
        px[off] = r; px[off + 1] = g; px[off + 2] = b; px[off + 3] = 255;
    }
    wfCtx.putImageData(lineData, 0, 0);

    // Wasserfall auf Zielbereich skalieren (nur Höhe)
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(window._wfCanvas, 0, 0, w, wfBufH, 0, wfY, w, wfH);

    // Center marker + passband (aus Theme wie waterfall.py)
    const cx = Math.floor(w / 2);

    ctx.strokeStyle = `rgba(${aR},${aG},${aB},0.4)`;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();

    // Passband (Mode-abhängige Bandbreite)
    const bwHz = currentMode === 'FM' ? 15000 : currentMode === 'AM' ? 6000 : 2700;
    const bwPx = Math.floor(bwHz / spanHz * w);
    let bx;
    if (currentMode === 'USB' || currentMode === 'DATA') bx = cx;
    else if (currentMode === 'LSB') bx = cx - bwPx;
    else bx = cx - Math.floor(bwPx / 2);

    ctx.fillStyle = `rgba(${aR},${aG},${aB},0.15)`;
    ctx.fillRect(bx, 0, bwPx, h);
    ctx.strokeStyle = `rgba(${aR},${aG},${aB},0.5)`;
    ctx.beginPath(); ctx.moveTo(bx, 0); ctx.lineTo(bx, h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx + bwPx, 0); ctx.lineTo(bx + bwPx, h); ctx.stroke();

    // Hover-Cursor (gestrichelte Linie + Frequenz-Tooltip)
    if (wfHoverX >= 0 && wfHoverX < w) {
        ctx.save();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = `rgba(${aR},${aG},${aB},0.6)`;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(wfHoverX, 0); ctx.lineTo(wfHoverX, h); ctx.stroke();
        ctx.setLineDash([]);
        // Frequenz-Label am Cursor
        const hoverFreq = (currentFreq - spanHz / 2) + (wfHoverX / w) * spanHz;
        const hoverLabel = (hoverFreq / 1e6).toFixed(3) + ' MHz';
        ctx.font = '10px Consolas, monospace';
        ctx.fillStyle = `rgba(${aR},${aG},${aB},0.9)`;
        const labelW = ctx.measureText(hoverLabel).width + 8;
        const labelX = Math.min(wfHoverX + 6, w - labelW);
        ctx.fillRect(labelX, 2, labelW, 16);
        ctx.fillStyle = '#000';
        ctx.fillText(hoverLabel, labelX + 4, 14);
        ctx.restore();
    }
}

// S-Meter — gleiche Berechnung wie ic705_ui.py
const S9_RAW = 100;
const MAX_RAW = 241;
const S_SEGMENTS = 14;
const S9_STEPS = ['+10', '+20', '+40', '+60'];

function initSMeter() {
    // Tick-Marks erzeugen
    const ticks = document.getElementById('smeter-ticks');
    for (let i = 0; i < S_SEGMENTS; i++) {
        const t = document.createElement('div');
        t.className = 'tick';
        ticks.appendChild(t);
    }
}

function updateSMeter() {
    const val = smeterValue;
    let sStr, frac;

    if (val <= S9_RAW) {
        const sNum = val * 9 / Math.max(S9_RAW, 1);
        sStr = `S${Math.min(9, Math.round(sNum))}`;
        // 14 Segmente: S0-S9 = 10 Segmente, +10/+20/+40/+60 = 4 Segmente
        frac = (sNum + 1) / 14;  // +1 weil S0 = erstes Segment
    } else {
        const dbOver = (val - S9_RAW) / Math.max(MAX_RAW - S9_RAW, 1) * 60;
        sStr = 'S9';
        for (let i = 0; i < S9_STEPS.length; i++) {
            if (dbOver >= (i + 0.5) * (60 / S9_STEPS.length)) {
                sStr = S9_STEPS[i];
            }
        }
        frac = (10 + dbOver / 60 * 4) / 14;
    }

    document.getElementById('smeter-info').textContent = `S-METER: ${sStr} | P1`;

    // Segmentiertes S-Meter zeichnen (14 Segmente wie Desktop)
    const canvas = document.getElementById('smeter-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.parentElement.clientWidth;
    const h = 20;
    canvas.height = h;

    const cs = getComputedStyle(document.documentElement);
    const bgColor = cs.getPropertyValue('--bg-dark').trim() || '#1a1a1a';
    const borderColor = cs.getPropertyValue('--border').trim() || '#555';
    const barColor = cs.getPropertyValue('--smeter-bar').trim() || '#06c6a4';
    const errorColor = cs.getPropertyValue('--error').trim() || '#ff4444';

    const gap = 2;
    const segW = w / S_SEGMENTS;
    const fillSegs = frac * S_SEGMENTS;

    // LED Style — runde Punkte
    if (currentSmeterStyle === 'led') {
        ctx.clearRect(0, 0, w, h);
        for (let i = 0; i < S_SEGMENTS; i++) {
            const cx = Math.floor(i * segW + segW / 2);
            const cy = h / 2;
            const r = Math.min(segW / 2 - 2, h / 2 - 2);
            const isOver = i >= 10;
            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, Math.PI * 2);
            ctx.fillStyle = i < fillSegs ? (isOver ? errorColor : barColor) : bgColor;
            ctx.fill();
            ctx.strokeStyle = borderColor;
            ctx.stroke();
        }
        return;
    }

    // Digit Style — große Zahl im Canvas
    if (currentSmeterStyle === 'digit') {
        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, w, h);
        ctx.font = 'bold 16px Consolas, monospace';
        ctx.fillStyle = barColor;
        ctx.textAlign = 'center';
        ctx.fillText(sStr, w / 2, h - 3);
        ctx.textAlign = 'start';
        return;
    }

    // Default: Segment Style
    for (let i = 0; i < S_SEGMENTS; i++) {
        const x = Math.floor(i * segW) + gap / 2;
        const sw = Math.floor(segW) - gap;
        const isOver = i >= 10;
        const activeColor = isOver ? errorColor : barColor;

        if (i < Math.floor(fillSegs)) {
            ctx.fillStyle = activeColor;
        } else if (i < fillSegs) {
            ctx.fillStyle = activeColor;
            ctx.fillRect(x, 0, Math.floor(sw * (fillSegs - Math.floor(fillSegs))), h);
            ctx.fillStyle = bgColor;
            ctx.fillRect(x + Math.floor(sw * (fillSegs - Math.floor(fillSegs))), 0,
                sw - Math.floor(sw * (fillSegs - Math.floor(fillSegs))), h);
            ctx.strokeStyle = borderColor;
            ctx.strokeRect(x, 0, sw, h);
            continue;
        } else {
            ctx.fillStyle = bgColor;
        }
        ctx.fillRect(x, 0, sw, h);
        ctx.strokeStyle = borderColor;
        ctx.strokeRect(x, 0, sw, h);
    }
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
            if (rigSocket) { rigSocket.close(); rigSocket = null; }
            connected = false;
            liveScope = false;
            btn.classList.remove('connected');
            bar.classList.remove('connected');
            status.textContent = 'SYSTEM READY';
            // Demo-Playback zurücksetzen
            demoStartTime = 0;
            return;
        }

        // Automatisch zum Server verbinden (gleicher Host wie die Seite)
        const host = document.getElementById('cfg-server-host')?.value.trim() || window.location.host;
        status.textContent = `Verbinde mit ${host}...`;
        connectWebSocket(host);
    });
}

let liveScope = false;
let rigSocket = null;

// WebSocket Verbindung zum RigLink Server
function connectWebSocket(host) {
    const wsUrl = `ws://${host}/ws`;
    rigSocket = new WebSocket(wsUrl);

    rigSocket.onopen = () => {
        console.log('WebSocket connected to', wsUrl);
        connected = true;
        liveScope = true;
        document.getElementById('btn-connect').classList.add('connected');
        document.querySelector('.status-bar').classList.add('connected');
        document.getElementById('status-text').textContent = `CAT: Verbunden (${host})`;
    };

    rigSocket.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            if (data.freq) { currentFreq = data.freq; updateFreqDisplay(); }
            if (data.mode) {
                currentMode = data.mode;
                document.querySelectorAll('.mode-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.mode === data.mode);
                });
            }
            if (data.smeter !== undefined) {
                smeterValue = smeterValue * 0.8 + data.smeter * 0.2;
            }
            if (data.power !== undefined) {
                const slider = document.getElementById('pwr-slider');
                const label = document.getElementById('pwr-label');
                if (slider) slider.value = data.power;
                if (label) label.textContent = `PWR: ${(data.power * 10 / 255).toFixed(1)}W`;
            }
            if (data.spectrum && data.spectrum.length === 475) {
                for (let i = 0; i < 475; i++) spectrum[i] = data.spectrum[i];
            }
            if (data.scope_center > 0) currentFreq = data.scope_center;
            if (data.scope_span > 0) currentSpanHz = data.scope_span;
        } catch (err) {}
    };

    rigSocket.onclose = () => {
        connected = false;
        liveScope = false;
        rigSocket = null;
        document.getElementById('btn-connect').classList.remove('connected');
        document.querySelector('.status-bar').classList.remove('connected');
        document.getElementById('status-text').textContent = 'Verbindung verloren';
        setTimeout(() => {
            document.getElementById('status-text').textContent = 'SYSTEM READY';
        }, 3000);
    };
}

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

    // Overlays schließen sich per Klick außerhalb (kein Close-Button nötig)

    // Overlay schließen bei Klick außerhalb
    [settingsOverlay, audioOverlay, themeOverlay].forEach(ov => {
        ov.addEventListener('click', (e) => { if (e.target === ov) ov.style.display = 'none'; });
    });

    // Rig-Auswahl → CI-V Adresse
    rigSelect.addEventListener('change', () => {
        const addr = IcomCIV.RIG_ADDRESSES[rigSelect.value] || 0xA4;
        civInput.value = '0x' + addr.toString(16).toUpperCase();
    });

    // Preset-Popup Logik ist jetzt in theme_editor.js
}





function getSerialConfig() {
    return {
        rig: document.getElementById('cfg-rig').value,
        baud: parseInt(document.getElementById('cfg-baud').value),
    };
}

// Step buttons
function setupStepButtons() {
    document.getElementById('btn-step-down').addEventListener('click', () => {
        if (freqLocked) return;
        const step = parseInt(document.getElementById('step-select').value);
        currentFreq -= step;
        updateFreqDisplay();
    });
    document.getElementById('btn-step-up').addEventListener('click', () => {
        if (freqLocked) return;
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
    { hz: 2500, label: '2.5k' },
    { hz: 5000, label: '5k' },
    { hz: 10000, label: '10k' },
    { hz: 25000, label: '25k' },
    { hz: 50000, label: '50k' },
    { hz: 100000, label: '100k' },
    { hz: 250000, label: '250k' },
    { hz: 500000, label: '500k' },
];
let currentSpanHz = 50000;

function setupSpan() {
    const slider = document.getElementById('span-slider');
    const label = document.getElementById('span-label');
    slider.addEventListener('input', () => {
        const idx = parseInt(slider.value);
        currentSpanHz = SPAN_VALUES[idx].hz;
        label.textContent = SPAN_VALUES[idx].label;
    });
}

// Lock-Button (Frequenz sperren)
function setupLock() {
    const btn = document.getElementById('btn-lock');
    btn.addEventListener('click', () => {
        freqLocked = !freqLocked;
        btn.classList.toggle('locked', freqLocked);
        const img = btn.querySelector('.lock-icon');
        if (img) img.src = freqLocked
            ? 'icons/lock.svg'
            : 'icons/lock_open.svg';
    });
}

// PBT Slider Labels
function setupPBT() {
    const inner = document.getElementById('pbt-inner');
    const outer = document.getElementById('pbt-outer');
    const bwLabel = document.getElementById('pbt-bw-label');
    const sftLabel = document.getElementById('pbt-sft-label');
    inner.addEventListener('input', () => {
        bwLabel.textContent = `BW: ${inner.value - 128}`;
    });
    outer.addEventListener('input', () => {
        sftLabel.textContent = `SFT: ${outer.value - 128}`;
    });
}

// VOX Slider Labels
function setupVoxSliders() {
    const thrSlider = document.getElementById('slider-vox-thr');
    const holdSlider = document.getElementById('slider-vox-hold');
    const thrLabel = document.getElementById('lbl-vox-thr');
    const holdLabel = document.getElementById('lbl-vox-hold');
    if (thrSlider && thrLabel) {
        thrSlider.addEventListener('input', () => {
            thrLabel.textContent = `THR:${thrSlider.value}dB`;
        });
    }
    if (holdSlider && holdLabel) {
        holdSlider.addEventListener('input', () => {
            holdLabel.textContent = `H:${holdSlider.value * 100}ms`;
        });
    }
}

// REC Toggle
function setupREC() {
    const tglRec = document.getElementById('tgl-rec');
    if (tglRec) {
        tglRec.addEventListener('click', function() {
            const active = this.classList.toggle('active');
            const img = this.querySelector('.toggle-icon');
            img.src = active
                ? 'icons/toggle_on.svg'
                : 'icons/toggle_off.svg';
        });
    }
}

// Mute Button
function setupMute() {
    const btn = document.getElementById('btn-mute');
    if (btn) {
        btn.addEventListener('click', () => {
            muted = !muted;
            const img = btn.querySelector('.mute-icon');
            if (img) img.src = muted
                ? 'icons/volume_off.svg'
                : 'icons/volume_up.svg';
            btn.classList.toggle('muted', muted);
        });
    }
}

// Waterfall SIG/NF Slider
let wfColorGain = 3.0;
let wfBlackLevel = 18;

function setupWfSliders() {
    const sigEl = document.getElementById('slider-sig');
    const nfEl = document.getElementById('slider-nf');
    const valSig = document.getElementById('val-sig');
    const valNf = document.getElementById('val-nf');

    if (sigEl) {
        sigEl.addEventListener('input', () => {
            wfColorGain = sigEl.value / 10.0;
            if (valSig) valSig.textContent = wfColorGain.toFixed(1);
        });
    }
    if (nfEl) {
        nfEl.addEventListener('input', () => {
            wfBlackLevel = parseInt(nfEl.value);
            if (valNf) valNf.textContent = wfBlackLevel;
        });
    }
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
        if (freqLocked) return;
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
        if (freqLocked) return;
        e.preventDefault();
        const step = parseInt(document.getElementById('step-select').value);
        const dir = e.deltaY < 0 ? 1 : -1;
        currentFreq += dir * step;
        updateFreqDisplay();
    });
    // Hover-Cursor Tracking
    canvas.addEventListener('mousemove', e => {
        const rect = canvas.getBoundingClientRect();
        wfHoverX = (e.clientX - rect.left) * (canvas.width / rect.width);
    });
    canvas.addEventListener('mouseleave', () => { wfHoverX = -1; });
}

// TX meter during PTT (vertikal links neben Wasserfall)
function updateTXMeter() {
    const bar = document.getElementById('tx-bar-v');
    const label = document.getElementById('tx-bar-v-label');
    if (pttActive) {
        const level = 30 + Math.random() * 40;
        bar.style.height = level + '%';
        label.textContent = Math.round(-60 + level * 0.6) + 'dB';
    } else {
        bar.style.height = '0%';
        label.textContent = '---';
    }
}

// Bug Report
function setupContact() {
    const overlay = document.getElementById('contact-overlay');
    const link = document.getElementById('link-contact');
    const closeBtn = document.getElementById('btn-contact-close');
    const sendBtn = document.getElementById('btn-contact-send');
    const status = document.getElementById('contact-status');
    const sysInfo = document.getElementById('report-sysinfo');

    function openReport() {
        if (sysInfo) sysInfo.textContent = getBrowserInfo();
        overlay.style.display = 'flex';
    }

    if (link) link.addEventListener('click', (e) => { e.preventDefault(); openReport(); });
    closeBtn.addEventListener('click', () => { overlay.style.display = 'none'; });
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.style.display = 'none'; });

    sendBtn.addEventListener('click', async () => {
        const msg = document.getElementById('contact-msg').value.trim();
        if (!msg) { status.textContent = 'Bitte Beschreibung eingeben.'; return; }

        sendBtn.disabled = true;
        sendBtn.textContent = 'Sende...';

        const body = `## Bug Report (Web Demo)\n\n## Beschreibung\n${msg}\n\n## System\n\`\`\`\n${getBrowserInfo()}\n\`\`\``;
        const result = await sendWebReport('[BUG] Web Demo', body);

        sendBtn.disabled = false;
        sendBtn.textContent = 'Report senden';

        if (result && result.ok) {
            status.textContent = 'Report gesendet! Danke.';
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

// Demo-Frame abspielen (zeitgesteuert wie echte App)
let lastDemoTick = 0;

function playDemoFrame() {
    if (!demoData || demoData.length === 0) {
        generateSpectrum();
        return;
    }

    // 1 Frame alle 80ms (gleiche Geschwindigkeit wie App scroll_timer)
    const now = performance.now();
    if (now - lastDemoTick < 80) return;
    lastDemoTick = now;

    // Nächsten Frame abspielen
    demoIndex = (demoIndex + 1) % demoData.length;
    const frame = demoData[demoIndex];

    if (frame.sp) {
        // Target-Spektrum setzen (wie _last_spectrum in Python)
        for (let i = 0; i < Math.min(475, frame.sp.length); i++) {
            spectrum[i] = frame.sp[i];
        }
        spectrumChanged = true;
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
        // Span-Slider synchronisieren
        for (let i = 0; i < SPAN_VALUES.length; i++) {
            if (SPAN_VALUES[i].hz === frame.ss) {
                const slider = document.getElementById('span-slider');
                if (slider) slider.value = i;
                const label = document.getElementById('span-label');
                if (label) label.textContent = SPAN_VALUES[i].label;
                break;
            }
        }
    }
}

// Main loop — wie Python _scroll_tick (80ms Interval)
function tick() {
    const now = performance.now();

    // Demo-Daten NUR wenn NICHT verbunden
    if (!connected && !rigSocket) {
        playDemoFrame();
    }

    // Blend: exponentieller gleitender Mittelwert (alpha=0.10 wie Desktop waterfall.py)
    for (let i = 0; i < 475; i++) {
        displaySpectrum[i] = displaySpectrum[i] * 0.90 + spectrum[i] * 0.10;
    }

    // Wasserfall: neue Zeile nur alle 80ms (wie App scroll_timer)
    if (now - lastWfTime >= 80) {
        lastWfTime = now;
        drawWaterfall();
    }

    updateSMeter();
    updateTXMeter();
    requestAnimationFrame(tick);
}

// Theme aus configs/theme.json laden (aktuelles Theme des Repos)
async function loadThemeFromConfig() {
    try {
        const resp = await fetch('https://raw.githubusercontent.com/DO4NRW/RigLink/main/configs/theme.json');
        const theme = await resp.json();
        const root = document.documentElement;
        for (const [key, val] of Object.entries(theme)) {
            if (typeof val !== 'string' || !val.startsWith('rgba')) continue;
            const m = val.match(/rgba?\((\d+),\s*(\d+),\s*(\d+),?\s*(\d*)\)/);
            if (!m) continue;
            root.style.setProperty('--' + key.replace(/_/g, '-'),
                `rgba(${m[1]},${m[2]},${m[3]},${m[4] ? +m[4]/255 : 1})`);
        }
    } catch(e) { applyTheme('dark'); }
}

// Init
async function init() {
    buildPalette();
    for (let i = 0; i < WF_LINES; i++) wfData.push(new Uint8Array(475));
    await loadThemeFromConfig();
    await loadDemoData();
    initSMeter();
    updateFreqDisplay();
    // VOX Toggle (nutzt SVG Icons aus dem Repo)
    const tglVox = document.getElementById('tgl-vox');
    tglVox.addEventListener('click', function() {
        const active = this.classList.toggle('active');
        const img = this.querySelector('.toggle-icon');
        img.src = active
            ? 'icons/toggle_on.svg'
            : 'icons/toggle_off.svg';
    });

    // Welcome-Popup
    document.getElementById('btn-welcome-close').addEventListener('click', () => {
        document.getElementById('welcome-overlay').style.display = 'none';
    });

    setupSettings();
    setupToggleGroups();
    setupManufacturerCascade();
    setupThemeTabs();
    setupAudioDemo();
    setupModeButtons();
    setupDSPButtons();
    setupPTT();
    setupConnect();
    setupStepButtons();
    setupSpan();
    setupLock();
    setupPBT();
    setupVoxSliders();
    setupREC();
    setupMute();
    setupWfSliders();
    setupPower();
    setupWaterfallClick();
    setupContact();

    // Web Serial Hinweis
    const verLabel = document.getElementById('version-text');
    if (hasWebSerial) {
        verLabel.textContent = 'v2.1.2 — Web Serial Ready';
    } else {
        verLabel.textContent = 'v2.1.2 — DEMO (Chrome/Edge für CAT)';
    }

    tick();
}

init();
