/**
 * RigLink Demo — Radio Setup
 * Toggle-Gruppen und Hersteller/Modell-Kaskade für das Radio Setup Overlay.
 */

// Toggle-Gruppen (Radio Setup)
function setupToggleGroups() {
    document.querySelectorAll('.toggle-group').forEach(group => {
        group.querySelectorAll('.toggle-option').forEach(opt => {
            opt.addEventListener('click', () => {
                group.querySelectorAll('.toggle-option').forEach(o => {
                    o.classList.remove('active');
                    const img = o.querySelector('img');
                    if (img) img.src = 'icons/toggle_off.svg';
                });
                opt.classList.add('active');
                const img = opt.querySelector('img');
                if (img) img.src = 'icons/toggle_on.svg';
            });
        });
    });
}

// Hersteller → Modell Kaskade
const RIG_MODELS = {
    icom: [['ic705','IC-705'],['ic7100','IC-7100'],['ic7300','IC-7300'],['ic7610','IC-7610'],['ic9700','IC-9700']],
    yaesu: [['ft991a','FT-991A'],['ft710','FT-710'],['ftdx101d','FTDX101D'],['ftdx101mp','FTDX101MP'],['ftdx10','FTDX10'],['ft891','FT-891'],['ft857','FT-857'],['ft818','FT-818'],['ft950','FT-950'],['ft450','FT-450'],['ft2000','FT-2000']],
    kenwood: [['ts890s','TS-890S'],['ts590sg','TS-590SG'],['ts480','TS-480'],['ts2000','TS-2000']],
    elecraft: [['k3','K3'],['k3s','K3S'],['kx3','KX3'],['kx2','KX2']],
    xiegu: [['g90','G90'],['g106','G106'],['x5105','X5105'],['x6100','X6100'],['x6200','X6200']],
};

function setupManufacturerCascade() {
    const mfr = document.getElementById('cfg-manufacturer');
    const model = document.getElementById('cfg-rig');
    if (!mfr || !model) return;
    mfr.addEventListener('change', () => {
        const models = RIG_MODELS[mfr.value] || [];
        model.innerHTML = models.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
        // CI-V update
        const civInput = document.getElementById('cfg-civ');
        if (civInput && mfr.value === 'icom') {
            const addr = IcomCIV.RIG_ADDRESSES[model.value] || 0xA4;
            civInput.value = '0x' + addr.toString(16).toUpperCase();
        } else if (civInput) {
            civInput.value = 'N/A';
        }
    });
}
