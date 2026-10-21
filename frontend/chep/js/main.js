// Start-up and page switching (same pattern as SDEW Quote / Supplementary Bill).

document.addEventListener('DOMContentLoaded', async () => {
    initDropzone();
    await refreshBootstrap();
    api('/api/auth').then(a => { if (a.login) document.getElementById('nav-logout-btn').style.display = ''; }).catch(() => {});
    if (appState.lastBatch) openBatch(appState.lastBatch, true);
    pollLeap();
});

async function refreshBootstrap() {
    try {
        const d = await api('/api/chep/bootstrap');
        appState.settings = d.settings;
        appState.template = d.template;
        appState.counts = d.counts;
        appState.lastBatch = d.last_batch;
        const dm = document.getElementById('db-mode');
        dm.style.display = '';
        dm.textContent = d.db_mode === 'cloud' ? 'Live data (cloud database)' : 'Data on this PC (SDEW Hub)';
        dm.className = 'status-badge ' + (d.db_mode === 'cloud' ? 'active' : 'warn');
        dm.title = d.db_mode === 'cloud' ? 'Reading and saving in the Turso cloud database, like the website'
            : 'Reading and saving in data\\sdew_hub.db on this PC';
        document.getElementById('runs-count-badge').textContent = d.counts.runs;
        document.getElementById('parts-count-badge').textContent = d.counts.parts;
    } catch (e) {
        showToast(`Could not load data: ${e.message}`, 'danger');
    }
}

function switchView(name) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(`${name}-view`).classList.add('active');
    document.getElementById(`nav-${name}-btn`).classList.add('active');
    if (name === 'history') loadRuns();
    else if (name === 'parts') loadParts();
    else if (name === 'settings') loadSettingsPage();
    else if (name === 'leap') loadLeapPage();
    else if (name === 'create' && appState.batch) schedulePreview(0);
}

// CHEP size code -> "Size 2 · A399014402"
function sizeLabel(code) {
    const t = (appState.settings?.types || []).find(t => String(t.code) === String(code));
    return t && t.pallet ? `Size ${code} · ${t.pallet}` : `Size ${code}`;
}
function sizeOptions(selected, blank = true) {
    const types = (appState.settings?.types || []).filter(t => t.pallet);
    return (blank ? `<option value="">— choose —</option>` : '') +
        types.map(t => `<option value="${esc(t.code)}" ${String(t.code) === String(selected) ? 'selected' : ''}>${esc(sizeLabel(t.code))}</option>`).join('');
}

async function logout() {
    try { await apiJson('/api/logout', 'POST'); } catch (e) { /* ignore */ }
    location.replace('/login.html');
}
