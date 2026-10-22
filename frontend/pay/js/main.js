// Start-up and page switching (same pattern as the other hub modules).

document.addEventListener('DOMContentLoaded', async () => {
    initDropzones();
    await Promise.all([refreshBootstrap(), refreshSales()]);
    renderSources();
    renderSummary();
    loadLines(0);
    renderSales();
});

async function refreshBootstrap() {
    try {
        const d = await api('/api/pay/bootstrap');
        appState.register = d.register;
        appState.payments = d.payments;
        appState.vouchers = d.vouchers;
        appState.run = d.run;
        appState.settings = d.settings;
    } catch (e) {
        showToast(`Could not load data: ${e.message}`, 'danger');
    }
}

function switchView(name) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(`${name}-view`).classList.add('active');
    document.getElementById(`nav-${name}-btn`).classList.add('active');
    if (name === 'check') { renderSources(); renderSummary(); loadLines(appState.offset); }
    else if (name === 'sales') { renderSales(); loadSalesLines(salesState.offset); }
    else if (name === 'uploads') loadFiles();
    else if (name === 'settings') loadSettingsPage();
}
