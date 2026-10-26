// Start-up and tab switching (same pattern as the other hub pages).

document.addEventListener('DOMContentLoaded', async () => {
    initDropzone();
    const today = new Date();
    const iso = d => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    const back = new Date(today.getTime() - 45 * 86400000);
    ['tally', 'grin', 'pay'].forEach(k => {
        document.getElementById(`${k}-from`).value = iso(back);
        document.getElementById(`${k}-to`).value = iso(today);
    });
    try { appState.grinSettings = (await api('/api/grin/settings')).settings; } catch (e) { /* shown later */ }
    loadStatus(0);
    api(`/api/grin/mails/plan`).then(p => { document.getElementById('mail-badge').textContent = p.drafts.length; }).catch(() => { });
});

function switchView(name) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(`${name}-view`).classList.add('active');
    document.getElementById(`nav-${name}-btn`).classList.add('active');
    if (name === 'status') loadStatus();
    else if (name === 'monthly') loadMonthly();
    else if (name === 'dcn') loadDcn();
    else if (name === 'mails') loadMails();
    else if (name === 'sources') loadSources();
    else if (name === 'buyers') loadBuyers();
    else if (name === 'settings') loadSettingsPage();
}
