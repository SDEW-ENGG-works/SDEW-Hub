// Settings page.

async function loadSettingsPage() {
    const d = await api('/api/dqms/settings');
    const s = d.settings;
    appState.settings = s;
    document.getElementById('set-transporter').value = s.transporter;
    document.getElementById('set-batch-app').value = s.batch_applicable;
    document.getElementById('set-batch-cons').value = s.batch_considerable;
    document.getElementById('set-batch-order').value = s.batch_order;
    document.getElementById('set-inv-unit').value = s.invoice_unit || 'packages';
    document.getElementById('set-fname').value = s.file_name;
    document.getElementById('set-reasons').value = (s.reasons || []).join('\n');
    document.getElementById('header-chips').innerHTML = (s.header || []).map((h, i) => `<span class="chip">${i + 1}. ${esc(h)}</span>`).join('');
}

async function saveSettings(extra = {}) {
    try {
        const d = await apiJson('/api/dqms/settings', 'PUT', Object.assign({
            transporter: document.getElementById('set-transporter').value,
            batch_applicable: document.getElementById('set-batch-app').value,
            batch_considerable: document.getElementById('set-batch-cons').value,
            batch_order: document.getElementById('set-batch-order').value,
            invoice_unit: document.getElementById('set-inv-unit').value,
            file_name: document.getElementById('set-fname').value,
            reasons: document.getElementById('set-reasons').value.split('\n'),
        }, extra));
        appState.settings = d.settings;
        showToast('Settings saved', 'success');
        loadSettingsPage();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function resetHeader() { saveSettings({ reset_header: true }); }

async function clearData(what) {
    const label = { invoices: 'all invoices', runs: 'the history', report: 'the DQMS report', typed: 'all typed line items' }[what];
    if (!await confirmBox(`Clear ${label}?`, 'This cannot be undone.')) return;
    await apiJson('/api/dqms/settings/reset-data', 'POST', { what });
    showToast('Cleared', 'success');
    await refreshBootstrap();
    if (what === 'invoices') appState.selected = null;
    schedulePreview(0);
}
