// Create page: invoice PDFs + DQMS batch report in, TAFE DQMS bulk upload template (.csv) out.

let _previewTimer = null;
appState.lineFilter = 'todo';
appState.selected = null;   // null = let the server tick every invoice not yet in a file
appState.edits = {};        // inv_no -> {dr, reason, remarks, unit} typed but not yet saved

async function uploadFiles(fileList, poPage) {
    const files = [...fileList];
    if (!files.length) return;
    const sub = document.getElementById('dropzone-sub');
    const said = [];
    let newInvoices = [];
    for (const [i, f] of files.entries()) {
        sub.textContent = `Reading ${f.name} (${i + 1} of ${files.length})…`;
        try {
            const r = await api(`/api/dqms/upload?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
            if (r.kind === 'invoices') {
                newInvoices = newInvoices.concat(r.new);
                if (r.updated.length) said.push(`${r.updated.join(', ')} read again`);
            } else if (r.kind === 'report') {
                said.push(`DQMS report: ${r.batches} batches of ${r.parts} parts`);
            } else if (r.kind === 'drs') {
                said.push(`Delivery Request ${r.drs.join(', ')}`);
            } else if (r.kind === 'po') {
                said.push(`PO ${r.po_no}: ${r.items} line items`);
            } else if (r.kind === 'status') {
                said.push(`Portal status file: ${r.invoices} invoice(s), ${r.failed_rows} row(s) not accepted`);
            } else if (r.kind === 'template') {
                said.push(`Blank template saved (${r.columns} columns)`);
            }
        } catch (e) {
            showToast(e.message, 'danger', 8000);
        }
    }
    if (newInvoices.length) {
        said.unshift(`${newInvoices.length} new invoice(s)`);
        if (appState.selected) newInvoices.forEach(n => appState.selected.add(n));
    }
    if (said.length) showToast(said.map(esc).join('<br>'), 'success', 6000);
    sub.textContent = 'Many files at once is fine. Also takes a PO (.htm) and the portal\'s status file (templateStatus.csv).';
    document.getElementById('file-input').value = '';
    await refreshBootstrap();
    if (poPage) loadPos();
    schedulePreview(0);
}

function requestBody() {
    return { selected: appState.selected ? [...appState.selected] : null, edits: appState.edits };
}

function schedulePreview(ms = 250) {
    clearTimeout(_previewTimer);
    _previewTimer = setTimeout(runPreview, ms);
}

async function runPreview() {
    try {
        appState.preview = await apiJson('/api/dqms/preview', 'POST', requestBody());
    } catch (e) {
        showToast(e.message, 'danger');
        return;
    }
    appState.selected = new Set(appState.preview.selected);
    const s = appState.preview.summary;
    document.getElementById('btn-generate').disabled = !s.invoices || s.blocked > 0;
    renderReport();
    renderStats();
    renderWarnings();
    renderLinePills();
    renderLines();
    renderPreview();
}

function renderReport() {
    const r = appState.preview.report || {};
    const el = document.getElementById('report-strip');
    el.innerHTML = r.name
        ? `<span class="status-badge active">DQMS report</span> <b>${esc(r.name)}</b> · report time ${esc((r.report_time || '').slice(0, 16))} ·
           ${inr(r.batches, 0)} batches of ${inr(r.parts, 0)} parts · loaded ${esc(when(r.uploaded_at))}`
        : `<span class="status-badge inactive">No DQMS report</span> Download "DQMS Batch Details Report" (Part Number ALL) from TAFE Channel and drop it above.`;
    el.innerHTML += ` <button class="btn btn-outline btn-sm" id="btn-dqms-fetch" onclick="fetchDqms()" title="Logs in to TAFE Channel, opens Batch Details Report (DQMS), Part Number ALL, Fetch, Export as Excel">⟳ Get latest DQMS report from TAFE Channel</button>`;
    if (_dqmsPoll) setDqmsBusy(true);
}

// "Get latest DQMS report": logs in to TAFE Channel with plain web requests (no browser), on the PC and the website.
// If the website cannot reach TAFE Channel, the SDEW PC does it and this page follows its progress.
let _dqmsPoll = null;
function setDqmsBusy(on, text) {
    const b = document.getElementById('btn-dqms-fetch');
    if (!b) return;
    b.disabled = on;
    b.textContent = on ? (text || 'Getting DQMS report from TAFE Channel…') : '⟳ Get latest DQMS report from TAFE Channel';
}
async function dqmsFetchDone(s) {
    clearInterval(_dqmsPoll); _dqmsPoll = null;
    setDqmsBusy(false);
    if (s.error) { showToast(`DQMS report not fetched: ${esc(s.error)}`, 'danger', 10000); return; }
    const r = s.result || {};
    showToast(`Latest DQMS report loaded from TAFE Channel — ${esc(String(r.batches ?? ''))} batches of ${esc(String(r.parts ?? ''))} parts.`, 'success', 6000);
    if (typeof refreshBootstrap === 'function') await refreshBootstrap();
    schedulePreview(0);
}
async function fetchDqms() {
    setDqmsBusy(true);
    let r;
    try {
        r = await apiJson('/api/dqms/dqms/fetch', 'POST', {});
    } catch (e) {
        setDqmsBusy(false);
        showToast(`DQMS report not fetched: ${esc(e.message)}`, 'danger', 10000);
        return;
    }
    if (r.done) return dqmsFetchDone(r);
    clearInterval(_dqmsPoll);
    _dqmsPoll = setInterval(async () => {        // the SDEW PC is doing it
        let s;
        try { s = await api('/api/dqms/dqms/fetch'); } catch (e) { return; }
        const last = (s.log || []).slice(-1)[0] || '';
        setDqmsBusy(true, last ? last.replace(/^\S+\s+/, '') : null);
        if (!s.running) dqmsFetchDone(s);
    }, 2000);
}

function renderStats() {
    const s = appState.preview.summary;
    const set = (id, v) => { document.getElementById(id).textContent = v; };
    set('st-invoices', inr(s.invoices, 0));
    set('st-invoices-sub', `of ${s.total_invoices} loaded` + (s.items !== s.invoices ? ` · ${s.items} part lines` : ''));
    set('st-rows', inr(s.rows, 0));
    set('st-rows-sub', `${s.items} invoice + ${s.rows - s.items} batch rows`);
    set('st-value', rupees(s.value));
    set('st-blocked', inr(s.blocked, 0));
    set('st-blocked-sub', s.blocked ? 'red rows — fix or untick them' : 'all ticked lines are complete');
    const card = document.getElementById('st-attn-card');
    card.classList.toggle('bad', s.blocked > 0);
    card.classList.toggle('good', !s.blocked);
}

function renderWarnings() {
    const w = appState.preview.warnings || [];
    document.getElementById('warn-card').style.display = w.length ? '' : 'none';
    document.getElementById('warn-list').innerHTML = w.map(x => `<li>${esc(x)}</li>`).join('');
}

const LINE_FILTERS = [
    ['todo', 'Not in a file'], ['attn', 'Need attention'], ['ticked', 'Ticked'], ['done', 'In a file'], ['portal', 'Portal said'], ['', 'All'],
];
function lineMatches(l, f) {
    if (f === 'todo') return !l.run_id;
    if (f === 'attn') return l.problems.length > 0;
    if (f === 'ticked') return l.selected;
    if (f === 'done') return !!l.run_id;
    if (f === 'portal') return (l.portal || []).length > 0;
    return true;
}
function renderLinePills() {
    const lines = appState.preview.lines;
    document.getElementById('line-pills').innerHTML = LINE_FILTERS
        .map(([f, label]) => {
            const n = lines.filter(l => lineMatches(l, f)).length;
            if (f && f !== 'todo' && !n) return '';
            return `<button class="cat-pill ${appState.lineFilter === f ? 'active' : ''}" onclick="setLineFilter('${f}')">${label}<span class="pill-count">${n}</span></button>`;
        }).join('');
}
function setLineFilter(f) { appState.lineFilter = f; renderLinePills(); renderLines(); }

function shownLines() {
    const q = document.getElementById('line-search').value.trim().toLowerCase();
    let lines = appState.preview.lines.filter(l => lineMatches(l, appState.lineFilter));
    if (q) lines = lines.filter(l => `${l.inv_no} ${l.part} ${l.descr} ${l.dr} ${l.order_no}`.toLowerCase().includes(q));
    return lines;
}

function reasonOptions(sel) {
    const list = appState.settings?.reasons || [];
    const opts = sel && !list.includes(sel) ? list.concat([sel]) : list;
    return `<option value="">—</option>` + opts.map(r => `<option ${r === sel ? 'selected' : ''}>${esc(r)}</option>`).join('');
}

function renderLines() {
    const lines = shownLines();
    const tb = document.getElementById('lines-tbody');
    const all = document.getElementById('inv-all');
    all.checked = lines.length > 0 && lines.every(l => l.selected);
    if (!lines.length) {
        tb.innerHTML = `<tr><td colspan="13" class="muted-cell">${appState.preview.lines.length ? 'Nothing in this list' : 'Drop the invoice PDFs above'}</td></tr>`;
        return;
    }
    let lastInv = null;
    tb.innerHTML = lines.map(l => {
        const first = l.inv_no !== lastInv;
        lastInv = l.inv_no;
        const inv = esc(l.inv_no);
        const tax = l.igst ? `IGST ${inr(l.igst)}` : [l.cgst ? `CGST ${inr(l.cgst)}` : '', l.sgst ? `SGST ${inr(l.sgst)}` : ''].filter(Boolean).join(' · ');
        // DR: one on the invoice -> shown; none or several -> type / choose
        let dr;
        if (l.drs.length > 1) {
            dr = `<select class="cell-input ${l.dr ? '' : 'need'}" data-inv="${inv}" onchange="setEdit(this.dataset.inv, 'dr', this.value)">
                <option value="">— choose —</option>${l.drs.map(d => `<option ${d === l.dr ? 'selected' : ''}>${esc(d)}</option>`).join('')}</select>`;
        } else if (!l.drs.length || l.edits.dr) {
            dr = `<input class="cell-input w-dr ${l.dr ? '' : 'need'}" value="${esc(l.dr)}" placeholder="DR No" data-inv="${inv}" onchange="setEdit(this.dataset.inv, 'dr', this.value)">`;
        } else {
            dr = `<span class="click-edit" title="Click to change" data-inv="${inv}" onclick="editDr(this.dataset.inv)">${esc(l.dr)}</span>`;
        }
        const lineCell = `<input class="cell-input w-line ${l.line == null ? 'need' : ''} ${l.line_src === 'typed' ? 'typed' : ''}" value="${l.line ?? ''}" placeholder="?"
            data-po="${esc(l.order_no)}" data-part="${esc(l.part)}" onchange="setLine(this.dataset.po, this.dataset.part, this.value)"
            title="${l.line_src === 'typed' ? 'Typed by hand (clear it to use the PO again)' : l.line_src === 'PO' ? 'From PO ' + esc(l.order_no) : 'Not in the PO - type it'}">`;
        const unitCell = `<input class="cell-input w-unit ${l.unit === null || l.unit === '' ? 'need' : ''} ${l.unit_src === 'packages' ? 'typed' : ''}" value="${l.unit ?? ''}" title="${l.unit_src === 'DR' ? 'From the DR: qty / unit size' : l.unit_src === 'typed' ? 'Typed by hand (clear it to use the DR)' : 'No of Packeges on the invoice - drop the DR PDF to check it'}" data-inv="${inv}" onchange="setEdit(this.dataset.inv, 'unit', this.value)">`;
        const batches = l.selected
            ? (l.batches.length ? l.batches.map(b => `<div class="batch-line"><span class="mono">${esc(b.batch_no)}</span><br>→ <b>${qty(b.qty)}</b> <span class="muted">of ${qty(b.balance)} left · ${esc((b.created || '').slice(0, 10))}</span></div>`).join('')
                : `<span class="muted">${l.batch_count ? '' : 'no batch in report'}</span>`)
              + (l.short > 0 ? `<div class="bad-text">short ${qty(l.short)}</div>` : '')
            : `<span class="muted">${l.batch_count} batch(es) in report</span>`;
        const checks = [];
        l.problems.forEach(p => checks.push(`<li class="bad-text">${esc(p)}</li>`));
        if (l.deferred) checks.push(`<li class="hold-text">Held for the 2nd upload: an earlier invoice in this file uses the same batch. Upload this file, drop a fresh DQMS report, then download again.</li>`);
        (l.notes || []).forEach(n => checks.push(`<li class="warn-text">${esc(n)}</li>`));
        if (first) (l.portal || []).filter(m => m.message).forEach(m => checks.push(
            `<li class="${(m.status || '').toUpperCase() === 'SUCCESS' ? 'ok-text' : 'portal-text'}">Last portal upload (${esc(m.record === 'BATCH_DTLS' ? 'batch row' : 'invoice row')}): ${esc(m.message)}</li>`));
        if (l.run_id) checks.push(`<li class="muted">In file #${l.run_id}</li>`);
        const rowCls = [l.problems.length ? 'row-missing' : '', !l.selected ? 'row-off' : '', first ? 'inv-first' : ''].join(' ');
        const main = `<tr class="${rowCls}">
            <td>${first ? `<input type="checkbox" ${l.selected ? 'checked' : ''} data-inv="${inv}" onchange="tickInvoice(this.dataset.inv, this.checked)">` : ''}</td>
            <td class="nowrap">${first ? `<span class="strong">${inv}</span><span class="note">${shortDate(l.inv_date)}</span>` : ''}</td>
            <td class="nowrap">${first ? esc(l.order_no) + (l.plant ? `<span class="note">${esc(l.plant)}</span>` : '') : ''}</td>
            <td class="nowrap"><span class="mono">${esc(l.part)}</span><span class="note" title="${esc(l.descr)}">${esc(l.descr)}</span></td>
            <td class="num">${qty(l.qty)}</td>
            <td>${first ? dr : ''}</td>
            <td>${lineCell}</td>
            <td class="num">${first ? unitCell : ''}</td>
            <td class="num nowrap">${first ? `${inr(l.total)}<span class="note">${tax}</span>` : ''}</td>
            <td>${batches}</td>
            <td>${first ? `<select class="cell-input w-reason ${l.problems.some(p => p.includes('Reason for Gap')) ? 'need' : ''}" data-inv="${inv}" onchange="setEdit(this.dataset.inv, 'reason', this.value)">${reasonOptions(l.reason)}</select>` : ''}</td>
            <td>${first ? `<input class="cell-input w-rem" value="${esc(l.remarks)}" data-inv="${inv}" onchange="setEdit(this.dataset.inv, 'remarks', this.value)">` +
                (l.total > 50000 || l.eway ? `<input class="cell-input w-rem ${l.total > 50000 && !/^\d{12}$/.test(l.eway || '') ? 'need' : ''}" style="margin-top:.3rem" value="${esc(l.eway || '')}" placeholder="E-way bill no" title="E-way Bill No. (12 digits) - needed above ₹50,000" data-inv="${inv}" onchange="setEdit(this.dataset.inv, 'eway', this.value)">` : '') : ''}</td>
            <td>${first ? `<button class="btn btn-danger-text btn-sm" title="Remove this invoice from the app" data-inv="${inv}" onclick="removeInvoice(this.dataset.inv)">✕</button>` : ''}</td></tr>`;
        const sub = checks.length ? `<tr class="check-row ${rowCls.replace('inv-first', '')}"><td></td><td colspan="12"><ul class="check-list">${checks.join('')}</ul></td></tr>` : '';
        return main + sub;
    }).join('');
}

function tickInvoice(inv, on) {
    if (on) appState.selected.add(inv); else appState.selected.delete(inv);
    schedulePreview(0);
}
function tickAll(on) {
    shownLines().forEach(l => { if (on) appState.selected.add(l.inv_no); else appState.selected.delete(l.inv_no); });
    schedulePreview(0);
}

async function setEdit(inv, key, val) {
    try {
        await apiJson('/api/dqms/invoices/edits', 'PUT', { inv_no: inv, edits: { [key]: val } });
    } catch (e) {
        showToast(e.message, 'danger');
    }
    schedulePreview(0);
}
function editDr(inv) {
    const l = appState.preview.lines.find(x => x.inv_no === inv);
    const v = prompt(`DR No. for invoice ${inv}`, l ? l.dr : '');
    if (v !== null) setEdit(inv, 'dr', v.trim());
}

async function setLine(po, part, val) {
    try {
        await apiJson('/api/dqms/pos/line', 'PUT', { po_no: po, part, item: val.trim() });
        if (val.trim()) showToast(`Line item ${esc(val.trim())} saved for ${esc(part)} on PO ${esc(po)} — used from now on.`, 'info');
    } catch (e) {
        showToast(e.message, 'danger');
    }
    schedulePreview(0);
}

async function removeInvoice(inv) {
    if (!await confirmBox(`Remove invoice ${inv}?`, 'It is taken out of this app. Drop the PDF again to bring it back.')) return;
    await apiJson('/api/dqms/invoices/delete', 'POST', { inv_no: inv });
    appState.selected?.delete(inv);
    await refreshBootstrap();
    schedulePreview(0);
}

function renderPreview() {
    const rows = appState.preview.rows;
    document.getElementById('preview-sub').textContent = rows.length ? `· ${rows.length} rows (+ heading row) — same columns as TAFE's template.csv` : '';
    const c = r => r.cells;
    const IDX = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17, 25, 26, 27, 28];
    document.getElementById('preview-tbody').innerHTML = rows.length ? rows.map((r, i) =>
        `<tr class="${r.kind === 'batch' ? 'batch-row' : 'inv-row'}"><td class="rn">${i + 2}</td>${IDX.map(k => `<td>${esc(c(r)[k])}</td>`).join('')}</tr>`
    ).join('') : `<tr><td colspan="20" class="muted-cell">Nothing to put in the template yet</td></tr>`;
}

async function generateFile() {
    const btn = document.getElementById('btn-generate');
    setBusy(btn, true, 'Making file…');
    try {
        const r = await apiJson('/api/dqms/generate', 'POST', requestBody());
        downloadRun(r.run_id);
        showToast(`<b>${esc(r.file_name)}</b> — ${r.summary.invoices} invoices, ${r.summary.rows} rows. Upload it on TAFE Channel, then drop the status file here if any row fails.`, 'success', 8000);
        appState.selected = null;
        appState.edits = {};
        await refreshBootstrap();
        schedulePreview(0);
    } catch (e) {
        showToast(e.message, 'danger', 6000);
    } finally {
        setBusy(btn, false);
    }
}

function downloadRun(id) {
    const a = document.createElement('a');
    a.href = `/api/dqms/runs/${id}/file`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function initDropzone() {
    const dz = document.getElementById('dropzone');
    ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('over'); }));
    dz.addEventListener('drop', e => uploadFiles(e.dataTransfer.files));
}

// "Start fresh": empty the Create page (invoices, DQMS report, portal messages).
// History files, POs, typed line items and settings are kept.
async function startFresh() {
    if (!await confirmBox('Start fresh?',
        'All loaded invoices, the DQMS report and the portal messages are cleared, so the page is empty. ' +
        'History files, POs, typed line items and settings are kept.')) return;
    try {
        await apiJson('/api/dqms/settings/reset-data', 'POST', { what: 'fresh' });
        appState.selected = null;
        appState.edits = {};
        appState.lineFilter = 'todo';
        document.getElementById('line-search').value = '';
        await refreshBootstrap();
        schedulePreview(0);
        showToast('Cleared — drop today\'s invoices and DQMS report.', 'success');
    } catch (e) {
        showToast(e.message, 'danger');
    }
}
