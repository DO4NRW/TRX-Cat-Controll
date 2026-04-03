/**
 * RigLink Demo — Theme Editor
 * Tabs, Farbliste und Digi-Modes Farben für das Theme Editor Overlay.
 */

// Color-Dots nach Theme-Wechsel aktualisieren
function refreshColorDots() {
    const cs = getComputedStyle(document.documentElement);
    document.querySelectorAll('#color-list .color-item').forEach(item => {
        const key = item.querySelector('.color-value')?.textContent;
        if (key) {
            const cssKey = '--' + key.replace(/_/g, '-');
            const val = cs.getPropertyValue(cssKey).trim();
            const dot = item.querySelector('.color-dot');
            if (dot && val) dot.style.background = val;
        }
    });
}

// Theme Editor Tabs
function setupThemeTabs() {
    document.querySelectorAll('.theme-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.theme-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.theme-tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
        });
    });

    // Farbliste befüllen
    const THEME_COLORS = [
        ['accent', 'Akzentfarbe'], ['accent_dark', 'Akzent dunkel'], ['error', 'Fehler'],
        ['bg_dark', 'Hintergrund dunkel'], ['bg_mid', 'Hintergrund mittel'], ['bg_light', 'Hintergrund hell'],
        ['border', 'Rahmen'], ['border_hover', 'Rahmen Hover'],
        ['text', 'Text'], ['text_secondary', 'Text sekundär'], ['text_muted', 'Text gedimmt'],
        ['slider_handle', 'Slider Punkt'], ['slider_fill', 'Slider Spur'],
        ['smeter_bar', 'S-Meter Balken'], ['tx_bar', 'TX-Meter Balken'],
        ['ptt_tx_bg', 'PTT TX Hintergrund'], ['ptt_tx_border', 'PTT TX Rahmen'],
        ['wf_color_1', 'Wasserfall 1'], ['wf_color_2', 'Wasserfall 2'], ['wf_color_3', 'Wasserfall 3'],
        ['wf_color_4', 'Wasserfall 4'], ['wf_color_5', 'Wasserfall 5'], ['wf_color_6', 'Wasserfall 6'],
        ['wf_color_7', 'Wasserfall 7'], ['wf_color_8', 'Wasserfall 8'], ['wf_color_9', 'Wasserfall 9'],
    ];
    const colorList = document.getElementById('color-list');
    if (colorList) {
        const cs = getComputedStyle(document.documentElement);
        THEME_COLORS.forEach(([key, label]) => {
            const cssKey = '--' + key.replace(/_/g, '-');
            const val = cs.getPropertyValue(cssKey).trim() || '#888';
            const item = document.createElement('div');
            item.className = 'color-item';
            item.innerHTML = `<div class="color-dot" style="background:${val}"></div><span class="color-name">${label}</span><span class="color-value">${key}</span><button class="color-edit-btn"><img src="icons/build.svg" width="20" height="20"></button>`;
            colorList.appendChild(item);
        });
    }

    // Digi-Farben
    const DIGI_COLORS = [
        ['digi_cq', 'CQ', '#00ff00'],
        ['digi_reply', 'Reply', '#ff6666'],
        ['digi_own_call', 'Own Call', '#ff0000'],
        ['digi_worked', 'Worked', '#888888'],
        ['digi_new_dxcc', 'New DXCC', '#ff00ff'],
        ['digi_new_grid', 'New Grid', '#ffaa00'],
        ['digi_new_call', 'New Callsign', '#00ccff'],
        ['digi_alert', 'Alert', '#ffff00'],
        ['digi_bg', 'Hintergrund', '#1a1a2e'],
        ['digi_text', 'Text', '#ffffff'],
        ['digi_time', 'Zeitstempel', '#aaaaaa'],
        ['digi_freq', 'Frequenz', '#66ccff'],
        ['digi_snr', 'SNR', '#88ff88'],
    ];
    const digiList = document.getElementById('digi-color-list');
    if (digiList) {
        DIGI_COLORS.forEach(([key, label, color]) => {
            const item = document.createElement('div');
            item.className = 'color-item';
            item.innerHTML = `<div class="color-dot" style="background:${color}"></div><span class="color-name">${label}</span><span class="color-value">${key}</span><button class="color-edit-btn"><img src="icons/build.svg" width="20" height="20"></button>`;
            digiList.appendChild(item);
        });
    }

    // S-Meter Style Auswahl
    document.querySelectorAll('.smeter-style-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.smeter-style-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
        });
    });
}
