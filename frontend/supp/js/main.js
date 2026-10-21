// Start-up and page switching (same pattern as SDEW Quote).

document.addEventListener('DOMContentLoaded', async () => {
    initDropzone();
    initGrinDates();
    await refreshBootstrap();
    renderUploadStats();
    renderBillSummary();
    loadBillLines();
});

async function refreshBootstrap() {
    try {
        const d = await api('/api/supp/bootstrap');
        appState.counts = d.counts;
        appState.settings = d.settings;
        appState.run = d.run;
        if (!d.portal.available) {
            const b = document.getElementById('portal-status');
            b.className = 'status-badge warn';
            b.textContent = 'Playwright not installed';
        }
    } catch (e) {
        showToast(`Could not load data: ${e.message}`, 'danger');
    }
}

function switchView(name) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(`${name}-view`).classList.add('active');
    document.getElementById(`nav-${name}-btn`).classList.add('active');
    if (name === 'bill') { renderBillSummary(); loadBillLines(appState.billOffset); }
    else if (name === 'uploads') { renderUploadStats(); loadFiles(); }
    else if (name === 'pos') loadPos();
    else if (name === 'grin') loadGrin();
    else if (name === 'review') { renderReviewPills(); loadReview(0); }
    else if (name === 'settings') loadSettingsPage();
}
