// Settings page: revision dates, rules, fixed Reversed Rates, plants.

async function loadSettingsPage() {
    try {
        const d = await api('/api/supp/settings');
        appState.settings = d.settings;
        const s = d.settings;
        document.getElementById('set-old-date').value = s.old_date;
        document.getElementById('set-new-date').value = s.new_date;
        document.getElementById('set-diff-basis').value = s.diff_basis;
        document.getElementById('set-remove-billed').checked = !!s.remove_billed_at_revised;
        document.getElementById('set-exclude-old').checked = !!s.exclude_old_date_invoices;
        renderOverrides(s.overrides);
        renderCorrections(s.part_corrections || []);
        document.getElementById('set-rate-pending').value = (s.rate_pending_pos || []).join(', ');
        renderPlants(s.plants);
        document.getElementById('tafe-login-status').innerHTML = d.tafe_login
            ? `<span class="status-badge active">Set</span> &nbsp;GRIN fetch logs in as <b>${esc(d.tafe_user)}</b> (from the .env file next to server.py).`
            : `<span class="status-badge warn">Not set</span> &nbsp;Copy <code>.env.example</code> to <code>.env</code> next to server.py and type TAFE_USER and TAFE_PASS in it. The password is never stored in the app's database.`;
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function renderOverrides(list) {
    document.getElementById('overrides-tbody').innerHTML = list.map(o => `
        <tr><td><input type="text" class="ov-part" value="${esc(o.part)}"></td>
        <td><input type="number" step="0.01" class="ov-existing" placeholder="from PO" value="${esc(o.existing ?? '')}"></td>
        <td><input type="number" step="0.01" class="ov-rate" value="${esc(o.revised)}"></td>
        <td><input type="text" class="ov-note" value="${esc(o.note || '')}"></td>
        <td><button class="btn-icon btn-icon-danger" onclick="this.closest('tr').remove()" title="Remove">&times;</button></td></tr>`).join('');
}
function addOverride() {
    const list = readOverrides();
    list.push({ part: '', existing: '', revised: '', note: '' });
    renderOverrides(list);
}
function readOverrides() {
    return [...document.querySelectorAll('#overrides-tbody tr')].map(tr => ({
        part: tr.querySelector('.ov-part').value.trim(),
        revised: tr.querySelector('.ov-rate').value,
        existing: tr.querySelector('.ov-existing').value,
        note: tr.querySelector('.ov-note').value.trim(),
    }));
}

function renderCorrections(list) {
    document.getElementById('corrections-tbody').innerHTML = list.map(c => `
        <tr><td><input type="text" class="pc-plant" value="${esc(c.plant || '')}" placeholder="all"></td>
        <td><input type="text" class="pc-from" value="${esc(c.from || '')}"></td>
        <td><input type="text" class="pc-to" value="${esc(c.to || '')}"></td>
        <td><input type="text" class="pc-note" value="${esc(c.note || '')}"></td>
        <td><button class="btn-icon btn-icon-danger" onclick="this.closest('tr').remove()" title="Remove">&times;</button></td></tr>`).join('');
}
function addCorrection() {
    const list = readCorrections();
    list.push({});
    renderCorrections(list);
}
function readCorrections() {
    return [...document.querySelectorAll('#corrections-tbody tr')].map(tr => ({
        plant: tr.querySelector('.pc-plant').value.trim(),
        from: tr.querySelector('.pc-from').value.trim(),
        to: tr.querySelector('.pc-to').value.trim(),
        note: tr.querySelector('.pc-note').value.trim(),
    }));
}

const PLANT_FIELDS = ['code', 'party', 'grin_plant', 'main_po', 'bill_to'];
function renderPlants(list) {
    document.getElementById('plants-tbody').innerHTML = list.map(p => `<tr>${PLANT_FIELDS.map(f =>
        `<td><input type="text" data-f="${f}" value="${esc(p[f] || '')}"></td>`).join('')}
        <td><button class="btn-icon btn-icon-danger" onclick="this.closest('tr').remove()" title="Remove">&times;</button></td></tr>`).join('');
}
function addPlant() {
    const list = readPlants();
    list.push({});
    renderPlants(list);
}
function readPlants() {
    return [...document.querySelectorAll('#plants-tbody tr')].map(tr => {
        const p = {};
        tr.querySelectorAll('input').forEach(i => { p[i.dataset.f] = i.value.trim(); });
        return p;
    });
}

async function saveSettings() {
    const body = {
        old_date: document.getElementById('set-old-date').value,
        new_date: document.getElementById('set-new-date').value,
        diff_basis: document.getElementById('set-diff-basis').value,
        remove_billed_at_revised: document.getElementById('set-remove-billed').checked,
        exclude_old_date_invoices: document.getElementById('set-exclude-old').checked,
        overrides: readOverrides().filter(o => o.part),
        part_corrections: readCorrections().filter(c => c.from && c.to),
        rate_pending_pos: document.getElementById('set-rate-pending').value,
        plants: readPlants().filter(p => p.code),
    };
    try {
        const d = await apiJson('/api/supp/settings', 'PUT', body);
        appState.settings = d.settings;
        renderOverrides(d.settings.overrides);
        renderCorrections(d.settings.part_corrections || []);
        renderPlants(d.settings.plants);
        showToast('Settings saved. Press <b>Calculate bill</b> to apply them.', 'success', 5000);
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function clearData(what) {
    const names = { sales: 'all sales lines', grin: 'all GRIN lines', pos: 'all POs', runs: 'all calculated bills' };
    if (!(await confirmBox(`Clear ${names[what]}?`, 'This cannot be undone. You can upload the files again.'))) return;
    try {
        await apiJson('/api/supp/settings/reset-data', 'POST', { what });
        await refreshBootstrap();
        renderUploadStats();
        renderBillSummary();
        showToast(`Cleared ${names[what]}`, 'success');
    } catch (e) {
        showToast(e.message, 'danger');
    }
}
