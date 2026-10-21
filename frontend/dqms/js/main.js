// Start-up and page switching (same pattern as SDEW Quote / Supplementary Bill / CHEP Transfer).

document.addEventListener('DOMContentLoaded', async () => {
    initDropzone();
    await refreshBootstrap();
    api('/api/auth').then(a => { if (a.login) document.getElementById('nav-logout-btn').style.display = ''; }).catch(() => {});
    schedulePreview(0);
});

async function refreshBootstrap() {
    try {
        const d = await api('/api/dqms/bootstrap');
        appState.settings = d.settings;
        appState.counts = d.counts;
        document.getElementById('runs-count-badge').textContent = d.counts.runs;
        document.getElementById('pos-count-badge').textContent = d.counts.pos;
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
    else if (name === 'pos') loadPos();
    else if (name === 'settings') loadSettingsPage();
    else if (name === 'create') schedulePreview(0);
}

async function logout() {
    try { await apiJson('/api/logout', 'POST'); } catch (e) { /* ignore */ }
    location.replace('/login.html');
}
