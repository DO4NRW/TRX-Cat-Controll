/**
 * RigLink Demo — Audio Setup
 * VU-Meter Simulation für das Audio Setup Overlay.
 */

// Audio Setup VU-Meter Simulation
function setupAudioDemo() {
    const waveBtn = document.getElementById('btn-wave-test');
    const recBtn = document.getElementById('btn-rec-test');
    const vuBar = document.getElementById('vu-bar');
    if (!waveBtn || !vuBar) return;

    let vuInterval = null;
    function startVU(duration) {
        let t = 0;
        vuInterval = setInterval(() => {
            const level = 20 + Math.random() * 60;
            vuBar.style.width = level + '%';
            vuBar.style.background = level > 85 ? 'var(--vu-red, #f44336)' : level > 60 ? 'var(--vu-yellow, #ffeb3b)' : 'var(--vu-green, #4caf50)';
            t += 50;
            if (t >= duration) { clearInterval(vuInterval); vuBar.style.width = '0%'; }
        }, 50);
    }
    waveBtn.addEventListener('click', () => startVU(2000));
    recBtn.addEventListener('click', () => startVU(3000));
}
