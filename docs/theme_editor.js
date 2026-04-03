/**
 * RigLink Demo — Theme Editor
 * Tabs, Farbliste, Color-Picker, Digi-Modes Farben, S-Meter Styles.
 */

// Hilfsfunktion: rgba → hex
function rgbaToHex(rgba) {
    const m = rgba.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!m) return '#888888';
    return '#' + [m[1],m[2],m[3]].map(x => (+x).toString(16).padStart(2,'0')).join('');
}

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

    // Farbliste befüllen mit Color-Picker
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

            const dot = document.createElement('div');
            dot.className = 'color-dot';
            dot.style.background = val;

            const nameSpan = document.createElement('span');
            nameSpan.className = 'color-name';
            nameSpan.textContent = label;

            const keySpan = document.createElement('span');
            keySpan.className = 'color-value';
            keySpan.textContent = key;

            // Color-Picker (versteckt)
            const colorInput = document.createElement('input');
            colorInput.type = 'color';
            colorInput.style.display = 'none';

            const editBtn = document.createElement('button');
            editBtn.className = 'color-edit-btn';
            editBtn.innerHTML = '<img src="icons/build.svg" width="20" height="20">';
            editBtn.addEventListener('click', () => {
                colorInput.value = rgbaToHex(val);
                colorInput.click();
            });
            colorInput.addEventListener('input', () => {
                const hex = colorInput.value;
                const r = parseInt(hex.slice(1,3),16);
                const g = parseInt(hex.slice(3,5),16);
                const b = parseInt(hex.slice(5,7),16);
                document.documentElement.style.setProperty(cssKey, `rgba(${r},${g},${b},1)`);
                dot.style.background = hex;
            });

            item.append(dot, nameSpan, keySpan, colorInput, editBtn);
            colorList.appendChild(item);
        });
    }

    // Digi-Farben mit Color-Picker
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
            const cssKey = '--' + key.replace(/_/g, '-');
            const item = document.createElement('div');
            item.className = 'color-item';

            const dot = document.createElement('div');
            dot.className = 'color-dot';
            dot.style.background = color;

            const nameSpan = document.createElement('span');
            nameSpan.className = 'color-name';
            nameSpan.textContent = label;

            const keySpan = document.createElement('span');
            keySpan.className = 'color-value';
            keySpan.textContent = key;

            const colorInput = document.createElement('input');
            colorInput.type = 'color';
            colorInput.style.display = 'none';

            const editBtn = document.createElement('button');
            editBtn.className = 'color-edit-btn';
            editBtn.innerHTML = '<img src="icons/build.svg" width="20" height="20">';
            editBtn.addEventListener('click', () => {
                colorInput.value = color;
                colorInput.click();
            });
            colorInput.addEventListener('input', () => {
                const hex = colorInput.value;
                const r = parseInt(hex.slice(1,3),16);
                const g = parseInt(hex.slice(3,5),16);
                const b = parseInt(hex.slice(5,7),16);
                document.documentElement.style.setProperty(cssKey, `rgba(${r},${g},${b},1)`);
                dot.style.background = hex;
            });

            item.append(dot, nameSpan, keySpan, colorInput, editBtn);
            digiList.appendChild(item);
        });
    }

    // S-Meter Style Auswahl → setzt globale Variable
    document.querySelectorAll('.smeter-style-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.smeter-style-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            if (typeof currentSmeterStyle !== 'undefined') {
                currentSmeterStyle = item.dataset.style;
            }
        });
    });

    // Preset-Pfeil Toggle
    const presetBtn = document.getElementById('btn-theme-presets');
    const presetPopup = document.getElementById('theme-preset-popup');
    if (presetBtn && presetPopup) {
        presetBtn.addEventListener('click', () => {
            const isOpen = presetPopup.style.display !== 'none';
            presetPopup.style.display = isOpen ? 'none' : 'block';
            presetBtn.classList.toggle('open', !isOpen);
        });
        presetPopup.querySelectorAll('.preset-item').forEach(item => {
            item.addEventListener('click', () => {
                const themeName = item.dataset.theme;
                const nameInput = document.getElementById('theme-name');
                if (nameInput) nameInput.value = item.textContent;
                presetPopup.style.display = 'none';
                presetBtn.classList.remove('open');
                applyTheme(themeName);
                refreshColorDots();
            });
        });
    }
}
