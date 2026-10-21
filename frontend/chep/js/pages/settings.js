// Settings page: BP code, plants, CHEP sizes, portal template.

let _set = null;

async function loadSettingsPage() {
    try {
        const d = await api('/api/chep/settings');
        _set = JSON.parse(JSON.stringify(d.settings));
        appState.template = d.template;
        document.getElementById('set-bp').value = _set.bp_code;
        document.getElementById('set-fname').value = _set.file_name;
        renderPlants();
        renderTypes();
        renderTemplateInfo();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function cellInput(list, i, key, ph = '') {
    return `<input type="text" value="${esc(list[i][key] ?? '')}" placeholder="${esc(ph)}" oninput="_set.${list === _set.plants ? 'plants' : 'types'}[${i}].${key} = this.value">`;
}

function renderPlants() {
    document.getElementById('plants-tbody').innerHTML = _set.plants.map((p, i) => `
        <tr><td>${cellInput(_set.plants, i, 'code', 'MDU')}</td><td>${cellInput(_set.plants, i, 'customer', '0019165124')}</td>
            <td>${cellInput(_set.plants, i, 'note')}</td>
            <td class="row-actions">
                <button class="btn btn-outline btn-sm" ${i === 0 ? 'disabled' : ''} onclick="movePlant(${i}, -1)">↑</button>
                <button class="btn btn-danger-text btn-sm" onclick="_set.plants.splice(${i}, 1); renderPlants()">Remove</button></td></tr>`).join('');
}
function addPlant() { _set.plants.push({ code: '', customer: '', note: '' }); renderPlants(); }
function movePlant(i, d) { const [p] = _set.plants.splice(i, 1); _set.plants.splice(i + d, 0, p); renderPlants(); }

function renderTypes() {
    document.getElementById('types-tbody').innerHTML = _set.types.map((t, i) => `
        <tr><td style="width:90px">${cellInput(_set.types, i, 'code', '2')}</td><td>${cellInput(_set.types, i, 'names', '2, 14402')}</td>
            <td>${cellInput(_set.types, i, 'pallet', 'not set')}</td><td>${cellInput(_set.types, i, 'lid', 'not set')}</td>
            <td class="row-actions"><button class="btn btn-danger-text btn-sm" onclick="_set.types.splice(${i}, 1); renderTypes()">Remove</button></td></tr>`).join('');
}
function addType() { _set.types.push({ code: '', names: '', pallet: '', lid: '' }); renderTypes(); }

function renderTemplateInfo() {
    const t = appState.template || {};
    const el = document.getElementById('template-info');
    if (t.error) { el.innerHTML = `<p class="hint" style="color:var(--danger)">${esc(t.error)}</p>`; return; }
    const r = t.date_range;
    const now = new Date();
    const today = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);  // local date
    const old = r && r.end && r.end < today;
    const ref = t.reference || {};
    el.innerHTML = `<div class="tpl-info">
            <div><span class="k">In use</span><span class="v">${esc(t.name)}</span></div>
            <div><span class="k">Uploaded</span><span class="v">${t.uploaded_at ? esc(when(t.uploaded_at)) : 'came with the app'}</span></div>
            <div><span class="k">Doc Date allowed</span><span class="v ${old ? 'bad' : ''}">${r ? `${dmy(r.start)} to ${dmy(r.end)}` : '—'}${old ? ' (old — get a fresh one)' : ''}</span></div>
            <div><span class="k">Sheet</span><span class="v">${esc(t.sheet || '')}</span></div>
        </div>
        <div class="ref-chips">
            <p class="hint">Reference lists in the template (the portal's drop-downs):</p>
            <div class="chip-list"><span class="chip"><b>BP Code</b></span>${(ref.bp_codes || []).map(x => `<span class="chip">${esc(x)}</span>`).join('')}</div>
            <div class="chip-list"><span class="chip"><b>To Customer</b></span>${(ref.customers || []).map(x => `<span class="chip">${esc(x)}</span>`).join('')}</div>
            <div class="chip-list"><span class="chip"><b>SKUs</b></span>${(ref.skus || []).map(x => `<span class="chip">${esc(x)}</span>`).join('')}</div>
        </div>`;
}

async function saveSettings() {
    _set.bp_code = document.getElementById('set-bp').value;
    _set.file_name = document.getElementById('set-fname').value;
    try {
        const d = await apiJson('/api/chep/settings', 'PUT', { bp_code: _set.bp_code, file_name: _set.file_name, plants: _set.plants, types: _set.types });
        _set = JSON.parse(JSON.stringify(d.settings));
        appState.settings = d.settings;
        renderPlants();
        renderTypes();
        if (appState.batch) { await apiJson(`/api/chep/batches/${appState.batch.id}/reread`, 'POST'); await openBatch(appState.batch.id, true); }
        showToast('Settings saved.', 'success');
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function uploadTemplate(fileList) {
    const f = [...fileList][0];
    if (!f) return;
    try {
        appState.template = await api(`/api/chep/template?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
        renderTemplateInfo();
        showToast('New CHEP template saved — it is used for every file from now on.', 'success');
    } catch (e) {
        showToast(e.message, 'danger', 6000);
    }
}

async function clearData(what) {
    const text = { runs: 'All files in History are removed.', parts: 'All learned and hand-set part sizes are removed.',
        template: 'The uploaded templates are removed; the template that came with the app is used again.' }[what];
    if (!await confirmBox('Are you sure?', text)) return;
    await apiJson('/api/chep/settings/reset-data', 'POST', { what });
    await refreshBootstrap();
    loadSettingsPage();
    showToast('Done.', 'success');
}
