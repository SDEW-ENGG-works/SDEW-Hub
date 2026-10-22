// Settings page.

async function loadSettingsPage() {
    try {
        const d = await api('/api/pay/settings');
        const s = d.settings;
        appState.settings = s;
        document.getElementById('set-credit-debit').checked = !!s.mark_credit_debit;
        document.getElementById('set-amount-differs').checked = !!s.mark_amount_differs;
        document.getElementById('set-min-ratio').value = s.min_ratio;
        document.getElementById('set-max-ratio').value = s.max_ratio;
        document.getElementById('set-fill').value = s.fill_color;
        document.getElementById('set-ignore').value = (s.ignore_doc_types || []).join(', ');
        previewFill();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function previewFill() {
    const v = document.getElementById('set-fill').value.replace('#', '');
    document.getElementById('fill-swatch').style.background = /^[0-9a-fA-F]{6}$/.test(v) ? `#${v}` : 'transparent';
}

async function saveSettings() {
    try {
        const d = await apiJson('/api/pay/settings', 'PUT', {
            mark_credit_debit: document.getElementById('set-credit-debit').checked,
            mark_amount_differs: document.getElementById('set-amount-differs').checked,
            min_ratio: document.getElementById('set-min-ratio').value,
            max_ratio: document.getElementById('set-max-ratio').value,
            fill_color: document.getElementById('set-fill').value,
            ignore_doc_types: document.getElementById('set-ignore').value,
        });
        appState.settings = d.settings;
        showToast('Saved. Press <b>Check payments</b> again to use the new settings.', 'success');
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function clearData(what) {
    const label = { payments: 'all loaded payment lines', runs: 'all payment checks', sales: 'all sales checks' }[what];
    if (!await confirmBox('Clear data?', `This removes ${label} from the app.`)) return;
    try {
        await apiJson('/api/pay/settings/reset-data', 'POST', { what });
        await refreshBootstrap();
        renderSources();
        renderSummary();
        loadLines(0);
        await refreshSales();
        renderSales();
        loadSalesLines(0);
        showToast('Cleared.', 'success');
    } catch (e) {
        showToast(e.message, 'danger');
    }
}
