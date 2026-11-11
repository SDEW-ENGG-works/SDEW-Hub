// Start-up and tab switching (same pattern as the other hub pages).

document.addEventListener('DOMContentLoaded', async () => {
    initDropzone();
    // Pull from Tally / Fetch GRIN / Fetch payments / notes: the dates start empty - the user picks them
    try { appState.grinSettings = (await api('/api/grin/settings')).settings; } catch (e) { /* shown later */ }
    loadStatus(0);
    loadBalance();
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


// Fetch dates start empty: the user picks From and To every time (nothing is pre-filled).
function pickDates(fromId, toId) {
    const f = document.getElementById(fromId), t = document.getElementById(toId);
    const from = f.value, to = t.value;
    if (!from || !to) {
        showToast('Pick the From date and the To date first', 'danger', 5000);
        (from ? t : f).focus();
        return null;
    }
    if (from > to) { showToast('From date is after To date', 'danger', 5000); f.focus(); return null; }
    return { from, to };
}
