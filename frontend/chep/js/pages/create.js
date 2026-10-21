// Create page: packing list in, CHEP Bulk Transfer template out.

let _previewTimer = null;
appState.lineFilter = '';

async function uploadPacking(fileList) {
    const f = [...fileList][0];
    if (!f) return;
    const sub = document.getElementById('dropzone-sub');
    sub.textContent = `Reading ${f.name}…`;
    try {
        const r = await api(`/api/chep/upload?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
        if (r.kind === 'template') {
            showToast('That file is a blank CHEP template — saved as the template to fill (see Settings).', 'success', 5000);
            await refreshBootstrap();
        } else {
            await refreshBootstrap();
            await openBatch(r.batch_id);
            if (r.learned) showToast(`${r.learned} part size(s) learned from this packing list.`, 'info');
        }
    } catch (e) {
        showToast(e.message, 'danger', 6000);
    } finally {
        sub.textContent = 'e.g. 05-10-2026 packing list.xls — the sheets of the latest day are ticked for you';
        document.getElementById('file-input').value = '';
    }
}

async function openBatch(id, quiet) {
    try {
        const b = await api(`/api/chep/batches/${id}`);
        appState.batch = b;
        appState.choices = {};
        appState.resend = new Set();
        appState.showOlder = false;
        appState.selected = new Set(b.sheets.filter(s => s.selected).map(s => s.name));
        document.getElementById('create-body').style.display = '';
        document.getElementById('batch-name').textContent = b.name;
        document.getElementById('batch-sub').textContent = `uploaded ${when(b.uploaded_at)}` +
            (b.skipped.length ? ` · not a packing list: ${b.skipped.join(', ')}` : '');
        document.getElementById('create-desc').textContent = `${b.name} — tick the sheets, check the CHEP sizes, then Save (or download).`;
        setDefaultDocDate();
        renderSheets();
        schedulePreview(0);
    } catch (e) {
        if (!quiet) showToast(e.message, 'danger');
    }
}

// Refresh = start fresh: the page goes back to empty, ready for the next packing list
// (like "Start fresh" in the DQMS Upload app). History, Parts and Settings are kept.
async function refreshCreate() {
    const btn = document.getElementById('btn-create-refresh');
    setBusy(btn, true, 'Refreshing…');
    try {
        await apiJson('/api/chep/batches/clear', 'POST', {});
        clearTimeout(_previewTimer);
        appState.batch = null;
        appState.preview = null;
        appState.saved = null;
        appState.choices = {};
        appState.resend = new Set();
        appState.selected = new Set();
        appState.showOlder = false;
        document.getElementById('create-body').style.display = 'none';
        document.getElementById('file-input').value = '';
        document.getElementById('create-desc').textContent = "Upload the day's packing list — the app fills the CHEP portal template from it.";
        ['f-transporter', 'f-vehicle', 'f-lr', 'f-doc-date'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        ['btn-save', 'btn-save-leap', 'btn-generate'].forEach(id => { document.getElementById(id).disabled = true; });
        await refreshBootstrap();
        showToast("Cleared — drop today's packing list.", 'success');
    } catch (e) {
        showToast(e.message, 'danger');
    } finally {
        setBusy(btn, false);
    }
}

function selectedDates() {
    return appState.batch.sheets.filter(s => appState.selected.has(s.name) && s.date).map(s => s.date).sort();
}
function setDefaultDocDate() {
    const d = selectedDates();
    document.getElementById('f-doc-date').value = d.length ? d[d.length - 1] : (appState.batch.latest || '');
}

// The packing list workbook also keeps old days' sheets (21-09, 29-04, ...). Only the sheets
// of the latest day are shown; the old ones stay behind "Show older sheets".
function isCurrentSheet(s) {
    const latest = appState.batch.latest;
    return !latest || s.date === latest || appState.selected.has(s.name);
}

function renderSheets() {
    const el = document.getElementById('sheet-list');
    const older = appState.batch.sheets.filter(s => !isCurrentSheet(s)).length;
    el.innerHTML = appState.batch.sheets.map((s, i) => {
        if (!appState.showOlder && !isCurrentSheet(s)) return '';
        const on = appState.selected.has(s.name);
        return `<label class="sheet-item ${on ? 'on' : ''} ${s.plant ? '' : 'noplant'}">
            <input type="checkbox" ${on ? 'checked' : ''} onchange="toggleSheet(${i}, this.checked)">
            <div>
                <div class="s-name">${esc(s.name)}</div>
                <div class="s-sub"><b>${esc(s.plant || '?')}</b> · ${s.date ? shortDate(s.date) : 'no date'} · ${s.lines} invoices · ${s.cheps} CHEP</div>
                <div class="s-sub">${esc(s.title)}</div>
            </div></label>`;
    }).join('');
    const more = document.getElementById('sheet-more');
    more.style.display = older ? '' : 'none';
    more.textContent = appState.showOlder ? 'Hide older sheets' : `Show ${older} older sheet${older > 1 ? 's' : ''} in this file`;
}

function toggleOlder() { appState.showOlder = !appState.showOlder; renderSheets(); }

function toggleSheet(i, on) {
    const name = appState.batch.sheets[i].name;
    if (on) appState.selected.add(name); else appState.selected.delete(name);
    setDefaultDocDate();
    renderSheets();
    schedulePreview(0);
}

function requestBody() {
    return {
        sheets: [...appState.selected],
        choices: appState.choices,
        resend: [...appState.resend],
        doc_date: document.getElementById('f-doc-date').value || null,
        transporter: document.getElementById('f-transporter').value,
        vehicle: document.getElementById('f-vehicle').value,
        lr: document.getElementById('f-lr').value,
    };
}

function schedulePreview(ms = 300) {
    if (!appState.batch) return;
    clearTimeout(_previewTimer);
    _previewTimer = setTimeout(runPreview, ms);
}

async function runPreview() {
    if (!appState.batch) return;
    const btn = document.getElementById('btn-generate');
    if (!appState.selected.size) {
        appState.preview = { lines: [], rows: [], warnings: ['Tick at least one sheet.'], summary: { invoices: 0, cheps: 0, rows: 0, missing: 0, carton_only: 0, from_history: 0, by_plant: {} } };
    } else {
        try {
            appState.preview = await apiJson(`/api/chep/batches/${appState.batch.id}/preview`, 'POST', requestBody());
        } catch (e) {
            showToast(e.message, 'danger');
            return;
        }
    }
    const s = appState.preview.summary;
    btn.disabled = !s.rows || s.missing > 0;
    ['btn-save', 'btn-save-leap'].forEach(id => { const b = document.getElementById(id); if (b) b.disabled = btn.disabled; });
    renderStats();
    renderWarnings();
    renderLinePills();
    renderLines();
    renderPreview();
}

function renderStats() {
    const s = appState.preview.summary;
    const set = (id, v) => { document.getElementById(id).textContent = v; };
    set('st-invoices', inr(s.invoices, 0));
    set('st-invoices-sub', [s.carton_only ? `${s.carton_only} carton-only` : '', s.already ? `${s.already} already sent` : '']
        .filter(Boolean).join(' · ') + (s.carton_only || s.already ? ' left out' : ''));
    set('st-cheps', inr(s.cheps, 0));
    set('st-cheps-sub', Object.entries(s.by_plant || {}).map(([p, n]) => `${p} ${n}`).join(' · '));
    set('st-rows', inr(s.rows, 0));
    set('st-missing', inr(s.missing, 0));
    set('st-missing-sub', s.from_history ? `${s.from_history} taken from part history` : (s.missing ? 'choose below' : 'all sizes known'));
    const card = document.getElementById('st-attn-card');
    card.classList.toggle('bad', s.missing > 0);
    card.classList.toggle('good', !s.missing);
}

function renderWarnings() {
    const w = appState.preview.warnings || [];
    const missing = appState.preview.summary.missing;
    const s = appState.preview.summary;
    const all = (missing ? [`${missing} invoice(s) need a CHEP size — pick it in the "CHEP size" column (red rows). It is remembered for the part.`] : []).concat(w);
    let html = all.map(x => `<li>${esc(x)}</li>`).join('');
    if (s.already) {
        html = `<li>${s.already} invoice(s) in these sheets were already sent in an earlier CHEP file (History) — they are left out, so nothing is transferred twice.
            <button class="sheet-more" type="button" onclick="setLineFilter('already')">See them</button> ·
            <button class="sheet-more" type="button" onclick="resendAll()">Send them again anyway</button></li>` + html;
    }
    if (s.resent) {
        html = `<li>${s.resent} invoice(s) already sent before will be sent AGAIN.
            <button class="sheet-more" type="button" onclick="undoResend()">Leave them out again</button></li>` + html;
    }
    document.getElementById('warn-card').style.display = html ? '' : 'none';
    document.getElementById('warn-list').innerHTML = html;
}

const LINE_FILTERS = [
    ['', 'All'], ['missing', 'Choose size'], ['part history', 'Part history'], ['chosen', 'Chosen'],
    ['packing list', 'Packing list'], ['carton', 'Carton only'], ['already', 'Already sent'],
];
function renderLinePills() {
    const lines = appState.preview.lines;
    const count = h => h ? lines.filter(l => l.how === h).length : lines.length;
    document.getElementById('line-pills').innerHTML = LINE_FILTERS
        .filter(([h]) => !h || count(h))
        .map(([h, label]) => `<button class="cat-pill ${appState.lineFilter === h ? 'active' : ''}" onclick="setLineFilter('${h}')">${label}<span class="pill-count">${count(h)}</span></button>`)
        .join('');
}
function setLineFilter(h) { appState.lineFilter = h; renderLinePills(); renderLines(); }

function skuText(types) {
    return Object.entries(types || {}).map(([code, n]) => {
        const t = (appState.settings.types || []).find(t => String(t.code) === String(code)) || {};
        return [t.pallet, t.lid].filter(Boolean).map(s => `${s} × ${n}`).join(', ');
    }).join('; ');
}

function renderLines() {
    const q = document.getElementById('line-search').value.trim().toLowerCase();
    let lines = appState.preview.lines;
    if (appState.lineFilter) lines = lines.filter(l => l.how === appState.lineFilter);
    if (q) lines = lines.filter(l => `${l.invoice} ${l.part_name} ${l.dr}`.toLowerCase().includes(q));
    const tb = document.getElementById('lines-tbody');
    if (!lines.length) { tb.innerHTML = `<tr><td colspan="12" class="muted-cell">No invoices</td></tr>`; return; }
    tb.innerHTML = lines.map(l => {
        const codes = Object.keys(l.types || {});
        let sizeCell = '';
        if (l.how === 'carton') sizeCell = '<span class="muted">—</span>';
        else if (l.how === 'already') sizeCell = `<button class="btn btn-outline btn-sm" data-key="${esc(l.key)}" onclick="resendLine(this.dataset.key)">Send again</button>`;
        else if (codes.length > 1) sizeCell = codes.map(c => `${esc(c)} × ${l.types[c]}`).join(', ');
        else sizeCell = `<select class="size-select ${l.how === 'missing' ? 'need' : ''}" data-key="${esc(l.key)}" onchange="setChoice(this.dataset.key, this.value)">${sizeOptions(codes[0] || appState.choices[l.key] || '')}</select>`;
        const rowCls = { missing: 'row-missing', 'part history': 'row-history', carton: 'row-carton', already: 'row-carton' }[l.how] || '';
        return `<tr class="${rowCls}">
            <td>${esc(l.plant)}</td><td>${esc(l.sno)}</td><td>${esc(l.dr)}</td>
            <td class="wrap">${esc(l.part_name)}</td><td class="num">${qty(l.qty)}</td>
            <td class="strong">${esc(l.invoice)}</td><td>${shortDate(l.inv_date)}</td>
            <td class="num">${l.chep || ''}</td><td class="num">${l.carton || ''}</td>
            <td>${sizeCell}</td>
            <td>${howBadge(l.how)}${l.note ? `<span class="note">${esc(l.note)}</span>` : ''}</td>
            <td class="sku-list">${l.how === 'already' ? '' : esc(skuText(l.types))}</td></tr>`;
    }).join('');
}

function setChoice(key, val) {
    if (val) appState.choices[key] = val; else delete appState.choices[key];
    schedulePreview(0);
}

function renderPreview() {
    const rows = appState.preview.rows;
    document.getElementById('preview-sub').textContent = rows.length ? `· ${rows.length} rows, same layout as the CHEP portal file` : '';
    const longDate = iso => {
        if (!iso) return '';
        const d = new Date(`${iso}T00:00:00`);
        return d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: '2-digit', year: 'numeric' });
    };
    document.getElementById('preview-tbody').innerHTML = rows.length ? rows.map((r, i) => {
        const t = (appState.settings.types || []).find(t => String(t.code) === String(r.type)) || {};
        const isLid = r.sku === t.lid && r.sku !== t.pallet;
        return `<tr class="${isLid ? 'lid' : ''}"><td class="rn">${i + 2}</td><td>${esc(r.bp_code)}</td><td>${esc(r.customer)}</td>
            <td>${esc(r.sku)}</td><td class="num">${r.qty}</td><td>${esc(longDate(r.doc_date))}</td>
            <td>${esc(r.transporter)}</td><td>${esc(r.vehicle)}</td><td>${esc(r.lr)}</td>
            <td>${esc(r.invoice)}</td><td>${esc(r.remarks)}</td></tr>`;
    }).join('') : `<tr><td colspan="11" class="muted-cell">Nothing to put in the template yet</td></tr>`;
}

// Saves the file in History (once per packing list + choices: pressing Save, then Download or
// Send to LEAP with nothing changed reuses the same History file instead of making a copy).
async function saveRun() {
    const body = requestBody();
    const key = appState.batch.id + '|' + JSON.stringify(body);
    if (appState.saved && appState.saved.key === key) return { ...appState.saved.r, reused: true };
    const r = await apiJson(`/api/chep/batches/${appState.batch.id}/generate`, 'POST', body);
    appState.saved = { key, r };
    await refreshBootstrap();
    return r;
}

function savedText(r) {
    return `<b>${esc(r.file_name)}</b> — ${r.summary.invoices} invoices, ${r.summary.cheps} CHEP, ${r.summary.rows} rows.`;
}

async function generateFile() {
    const btn = document.getElementById('btn-generate');
    setBusy(btn, true, 'Making file…');
    try {
        const r = await saveRun();
        downloadRun(r.run_id);
        showToast(savedText(r), 'success', 6000);
    } catch (e) {
        showToast(e.message, 'danger', 6000);
    } finally {
        setBusy(btn, false);
    }
}

async function saveFile(toLeap) {
    const btn = document.getElementById(toLeap ? 'btn-save-leap' : 'btn-save');
    setBusy(btn, true, 'Saving…');
    try {
        const r = await saveRun();
        if (toLeap) {
            appState.leapRun = r.run_id;
            switchView('leap');
            showToast(`${savedText(r)} Ready on the LEAP page.`, 'success', 6000);
        } else {
            showToast(`${r.reused ? 'Already saved' : 'Saved in History'}: ${savedText(r)} ` +
                `<a href="#" onclick="appState.leapRun=${r.run_id}; switchView('leap'); return false;">Send to LEAP</a>`, 'success', 8000);
        }
    } catch (e) {
        showToast(e.message, 'danger', 6000);
    } finally {
        setBusy(btn, false);
    }
}

function downloadRun(id) {
    const a = document.createElement('a');
    a.href = `/api/chep/runs/${id}/excel`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function initDropzone() {
    const dz = document.getElementById('dropzone');
    ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('over'); }));
    dz.addEventListener('drop', e => uploadPacking(e.dataTransfer.files));
}

// Invoices already sent in an earlier CHEP file are left out; these put them back in.
function resendLine(key) { appState.resend.add(key); schedulePreview(0); }
function resendAll() {
    appState.preview.lines.filter(l => l.how === 'already').forEach(l => appState.resend.add(l.key));
    schedulePreview(0);
}
function undoResend() { appState.resend.clear(); schedulePreview(0); }
