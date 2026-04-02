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
let currentFreq = 14200000; // Hz
let currentMode = 'USB';
let connected = false;
let pttActive = false;
let smeterValue = 0;
let spectrum = new Float32Array(475);
let wfData = [];
const WF_LINES = 200;

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
    const w = canvas.width = canvas.parentElement.clientWidth;
    const h = canvas.height = canvas.parentElement.clientHeight;
    if (w <= 0 || h <= 0) return;

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

    const spanHz = 50000;
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

    // Add new line
    const newLine = new Uint8ClampedArray(w * 4);
    for (let px = 0; px < w; px++) {
        const idx = Math.min(474, Math.floor(px * 475 / w));
        let val = spectrum[idx];
        val = Math.max(0, (val - 3) * 3);
        const ci = Math.min(255, Math.max(0, Math.floor(val)));
        const [r, g, b] = palette[ci];
        const off = px * 4;
        newLine[off] = r; newLine[off + 1] = g; newLine[off + 2] = b; newLine[off + 3] = 255;
    }

    // Shift waterfall down
    if (wfH > 1) {
        const existing = ctx.getImageData(0, wfY, w, wfH - 1);
        ctx.putImageData(existing, 0, wfY + 1);
    }
    const lineData = new ImageData(newLine, w, 1);
    ctx.putImageData(lineData, 0, wfY);

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

// S-Meter animation
function updateSMeter() {
    const target = connected ? 30 + Math.random() * 40 : 0;
    smeterValue = smeterValue * 0.8 + target * 0.2;
    const pct = Math.min(100, smeterValue);
    document.getElementById('smeter-bar').style.width = pct + '%';

    const sNum = Math.min(9, Math.floor(pct / 100 * 13));
    const label = sNum <= 9 ? `S${sNum}` : `S9+${(sNum - 9) * 10}`;
    document.getElementById('smeter-info').textContent = `S-METER: ${label} | P1`;
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
                smeterValue = raw / 2.55; // 0-255 → 0-100
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

            const ok = await civ.connect(cfg.baud);
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

// Settings overlay
function setupSettings() {
    const overlay = document.getElementById('settings-overlay');
    const menuBtn = document.querySelector('.menu-btn');
    const closeBtn = document.getElementById('btn-settings-close');
    const rigSelect = document.getElementById('cfg-rig');
    const civInput = document.getElementById('cfg-civ');

    menuBtn.addEventListener('click', () => {
        overlay.style.display = overlay.style.display === 'none' ? 'flex' : 'none';
    });
    closeBtn.addEventListener('click', () => {
        overlay.style.display = 'none';
    });
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.style.display = 'none';
    });

    // Rig-Auswahl → CI-V Adresse updaten
    rigSelect.addEventListener('change', () => {
        const addr = IcomCIV.RIG_ADDRESSES[rigSelect.value] || 0xA4;
        civInput.value = '0x' + addr.toString(16).toUpperCase();
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
        const spanHz = 50000;
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

// Main loop
function tick() {
    if (!liveScope) generateSpectrum();
    drawWaterfall();
    updateSMeter();
    updateTXMeter();
    requestAnimationFrame(tick);
}

// Init
async function init() {
    buildPalette();
    for (let i = 0; i < WF_LINES; i++) wfData.push(new Uint8Array(475));
    await loadTheme();
    updateFreqDisplay();
    setupSettings();
    setupModeButtons();
    setupDSPButtons();
    setupPTT();
    setupConnect();
    setupStepButtons();
    setupPower();
    setupWaterfallClick();
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
