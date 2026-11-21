// DR -> Invoice: DR PDFs -> draft invoices -> check / number / verify -> send to Tally (bridge or PC server).
const DI = { data: null, filter: 'open', ticked: new Set() };
const BRIDGE = 'http://localhost:9001';
const ON_SITE = !['localhost', '127.0.0.1'].includes(location.hostname);
const BRIDGE_HELP = 'Tally bridge is not running on this computer. Download it from GRIN & Payments > Sources ' +
    '(SDEW-Tally-Bridge.exe), run it once, then try again.';
const n2 = v => (v === null || v === undefined || v === '') ? '' : inr(v);
const num = v => (v === null || v === undefined) ? '' : String(+v);
const FILTERS = [['open', 'Open'], ['draft', 'Draft'], ['verified', 'Verified'], ['sent', 'Sent to Tally'], ['all', 'All']];

function todayIso() { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }

async function loadDrafts(recheck = false) {
    try { DI.data = await api(`/api/drinv/drafts${recheck ? '?recheck=1' : ''}`); } catch (e) { return showToast(e.message, 'danger'); }
    const sn = document.getElementById('start-no');
    if (!sn.value || recheck) sn.value = DI.data.next_no || '';
    renderConfig(DI.data.config);
    render();
    renderHistory();
    if (recheck) showToast('Checked again against Tally and the PO data', 'success');
}

function renderConfig(c) {
    document.getElementById('t-vtype').textContent = c.vtype;
    document.getElementById('t-company').textContent = c.company ? `, company ${c.company}` : '';
    document.getElementById('t-parties').innerHTML = Object.entries(c.plants).map(([p, v]) =>
        `<b>${esc(p)}</b> ${esc(v.party)} (${v.inter ? 'IGST' : 'CGST + SGST'})`).join(' · ');
    const L = c.learned || {};
    document.getElementById('t-learned').innerHTML = Object.keys(c.plants).map(p => L[p]
        ? `<li>✅ <b>${esc(p)}</b>: format learned from invoice ${esc(L[p].from_inv)} — fields ${esc(L[p].fields.join(', ') || 'none')}</li>`
        : `<li>⚠️ <b>${esc(p)}</b>: format not learned yet (done automatically before the first send)</li>`).join('') +
        (c.last_learn ? `<li class="di-small">Last try: ${esc(c.last_learn)}</li>` : '');
}

function shown() {
    const ds = DI.data ? DI.data.drafts : [];
    if (DI.filter === 'all') return ds;
    if (DI.filter === 'open') return ds.filter(d => d.status !== 'sent');
    return ds.filter(d => d.status === DI.filter);
}

function render() {
    const c = DI.data.counts || {};
    const cnt = { open: (c.draft || 0) + (c.verified || 0), draft: c.draft || 0, verified: c.verified || 0, sent: c.sent || 0 };
    cnt.all = cnt.open + cnt.sent;
    document.getElementById('di-filter').innerHTML = FILTERS.map(([k, l]) =>
        `<button class="di-chip ${DI.filter === k ? 'on' : ''}" onclick="DI.filter='${k}';render()">${l} <b>${cnt[k]}</b></button>`).join('');
    const ds = shown();
    const ids = new Set(ds.map(d => d.id));
    DI.ticked = new Set([...DI.ticked].filter(i => ids.has(i)));
    const allOn = ds.length && ds.every(d => DI.ticked.has(d.id));
    const t = document.getElementById('di-table');
    if (!ds.length) {
        t.innerHTML = '<tr><td class="muted" style="padding:1rem">No invoices here. Upload DR PDFs above.</td></tr>';
        document.getElementById('di-foot').textContent = '';
        return;
    }
    const ed = (d, k, v, cls = '', w = '') => d.status === 'sent' ? esc(v ?? '')
        : `<input class="ed ${cls}" ${w} value="${esc(v ?? '')}" onchange="edit(${d.id}, '${k}', this.value)">`;
    t.innerHTML = `<thead><tr><th><input type="checkbox" ${allOn ? 'checked' : ''} onchange="tickAll(this.checked)"></th>
        <th>Invoice no</th><th>Date</th><th>Plant / DR / PO</th><th>Part · Tally item</th>
        <th title="TOTAL NOS in Tally">Total Nos</th><th title="NO OF PACKAGES in Tally">No of Packages</th>
        <th title="NO OF PICES in Tally">No of Pieces</th><th title="TOTAL KGS in Tally">Total Kgs</th><th>Title</th>
        <th>Rate</th><th>GST</th><th>Taxable</th><th>Total</th><th>Remarks</th><th>Status</th></tr></thead><tbody>` +
        ds.map(d => {
            const errs = d.issues.filter(i => i.level === 'error');
            return `<tr class="${d.status}">
            <td><input type="checkbox" ${DI.ticked.has(d.id) ? 'checked' : ''} onchange="tick(${d.id}, this.checked)"></td>
            <td style="min-width:110px">${ed(d, 'inv_no', d.inv_no, d.inv_no ? '' : 'miss', 'placeholder="15885/26-27"')}</td>
            <td>${d.status === 'sent' ? dmy(d.inv_date) : `<input class="ed" type="date" value="${esc(d.inv_date)}" onchange="edit(${d.id}, 'inv_date', this.value)">`}</td>
            <td><b>${esc(d.plant || '?')}</b><div class="di-small">DR ${esc(d.dr_no)}</div><div class="di-small">PO ${esc(d.po_no)}</div></td>
            <td style="min-width:200px"><b>${esc(d.part)}</b> <span class="di-small">${esc(d.descr || '')}</span>
                ${ed(d, 'item_name', d.item_name, d.item_name ? '' : 'miss', 'placeholder="Tally stock item name"')}
                <div class="di-small">DR: ${num(d.dr_req)} ${esc(d.bin || '')} × ${num(d.dr_size)} = ${num(d.dr_qty)}</div></td>
            <td style="width:70px">${ed(d, 'qty', num(d.qty), 'num' + (d.qty ? '' : ' miss'))}</td>
            <td style="width:70px">${ed(d, 'packages', num(d.packages), 'num' + (d.packages ? '' : ' miss'))}</td>
            <td style="width:70px">${ed(d, 'pieces', num(d.pieces), 'num' + (d.pieces ? '' : ' miss'))}</td>
            <td style="width:64px">${ed(d, 'kgs', d.kgs, 'num', 'placeholder="—"')}</td>
            <td style="width:80px">${ed(d, 'title', d.title ?? 'KANBAN')}</td>
            <td style="width:84px">${ed(d, 'rate', d.rate == null ? '' : (+d.rate).toFixed(2), 'num' + (d.rate ? '' : ' miss'))}
                ${d.rate_po != null && d.rate != null && Math.abs(d.rate - d.rate_po) >= .005 ? `<div class="di-small">PO ${n2(d.rate_po)}</div>` : ''}</td>
            <td style="min-width:150px">${gstCell(d)}</td>
            <td class="num">${n2(d.amount)}</td>
            <td class="num"><b>${n2(d.total)}</b>${d.round_off ? `<div class="di-small">Round off ${d.round_off > 0 ? '+' : ''}${(+d.round_off).toFixed(2)}</div>` : ''}</td>
            <td class="rem">${ed(d, 'remarks', d.remarks)}</td>
            <td><span class="di-b ${d.status}">${d.status === 'sent' ? 'In Tally' : d.status === 'verified' ? 'Verified' : 'Draft'}</span>
                ${d.verified_by && d.status !== 'draft' ? `<div class="di-small">by ${esc(d.verified_by)}</div>` : ''}
                ${d.tally_msg ? `<div class="di-small" style="color:${d.status === 'sent' ? '#166534' : '#b91c1c'}">${esc(d.tally_msg)}</div>` : ''}
                ${d.status !== 'sent' && d.issues.length ? `<ul class="di-iss">${d.issues.map(i => `<li class="${i.level}">${esc(i.text)}</li>`).join('')}</ul>` : ''}
                ${d.status !== 'sent' && !errs.length && d.status === 'draft' ? '<div class="di-small" style="color:#166534">Ready to verify</div>' : ''}</td>
            </tr>`;
        }).join('') + '</tbody>';
    const sum = ds.reduce((a, d) => a + (d.total || 0), 0);
    document.getElementById('di-foot').textContent = `${ds.length} invoice(s), total ₹${inr(sum)}. Ticked: ${DI.ticked.size}.`;
}

// GST shown the way the invoice prints it: CGST 2.5 % + SGST 2.5 % (MDU, Tamil Nadu) or IGST 5 % (DBR)
function gstCell(d) {
    const g = +d.gst_rate || 0;
    const rate = d.status === 'sent' ? `${num(g)} %` :
        `<input class="ed num" style="width:46px;display:inline-block" value="${num(g)}" onchange="edit(${d.id}, 'gst_rate', this.value)"> %`;
    const lines = d.igst
        ? `<div>IGST ${num(g)}% <b>₹${n2(d.igst)}</b></div>`
        : `<div>CGST ${num(g / 2)}% <b>₹${n2(d.cgst)}</b></div><div>SGST ${num(g / 2)}% <b>₹${n2(d.sgst)}</b></div>`;
    return `<div class="di-small">GST ${rate}</div>${lines}`;
}

function renderHistory() {
    const h = (DI.data && DI.data.history) || [];
    document.getElementById('di-history').innerHTML = h.length ? `<thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead><tbody>` +
        h.map(x => `<tr><td style="white-space:nowrap">${esc(when(x.at))}</td><td>${esc(x.user || '')}</td><td><b>${esc(x.action)}</b></td>
            <td>${esc(x.detail || '')}${x.invoices && x.invoices.length > 1 ? `<div class="di-small">${esc(x.invoices.join(', '))}</div>` : ''}</td></tr>`).join('') + '</tbody>'
        : '<tr><td class="muted" style="padding:.8rem">Nothing yet.</td></tr>';
}

function tick(id, on) { on ? DI.ticked.add(id) : DI.ticked.delete(id); render(); }
function tickAll(on) { shown().forEach(d => on ? DI.ticked.add(d.id) : DI.ticked.delete(d.id)); render(); }
function tickedIds() {
    const ids = shown().filter(d => DI.ticked.has(d.id)).map(d => d.id);
    if (!ids.length) showToast('Tick the invoices first', 'danger');
    return ids;
}

async function edit(id, field, value) {
    try {
        const r = await apiJson(`/api/drinv/drafts/${id}`, 'POST', { [field]: value });
        const ds = DI.data.drafts, i = ds.findIndex(d => d.id === id);
        if (i >= 0) ds[i] = r;
        await loadDrafts();
    } catch (e) { showToast(e.message, 'danger'); loadDrafts(); }
}

async function uploadDRs(files) {
    const box = document.getElementById('upload-msgs');
    box.innerHTML = '';
    const date = document.getElementById('inv-date').value || todayIso();
    let ok = 0, bad = 0;
    for (const f of [...files]) {
        const row = document.createElement('div');
        row.className = 'upload-row';
        row.innerHTML = `<span class="status-badge muted">…</span><span class="file">${esc(f.name)}</span><span class="msg">Reading…</span>`;
        box.appendChild(row);
        try {
            const r = await api(`/api/drinv/upload?name=${encodeURIComponent(f.name)}&date=${date}`, { method: 'POST', body: f });
            row.querySelector('.status-badge').className = 'status-badge active';
            row.querySelector('.status-badge').textContent = 'OK';
            row.querySelector('.msg').textContent = r.message;
            ok++;
        } catch (e) {
            row.classList.add('err');
            row.querySelector('.status-badge').className = 'status-badge inactive';
            row.querySelector('.status-badge').textContent = 'Error';
            row.querySelector('.msg').textContent = e.message;
            bad++;
        }
    }
    showToast(`${ok} DR file(s) read${bad ? `, ${bad} not read` : ''}`, bad ? 'danger' : 'success');
    DI.filter = 'open';
    loadDrafts();
}

async function giveNumbers() {
    const ids = tickedIds(); if (!ids.length) return;
    const start = document.getElementById('start-no').value.trim();
    // number in the order shown: plant, then DR
    const order = shown().filter(d => ids.includes(d.id)).sort((a, b) => (a.plant || '').localeCompare(b.plant || '') || a.dr_no.localeCompare(b.dr_no)).map(d => d.id);
    try { DI.data = await apiJson('/api/drinv/number', 'POST', { start, ids: order }); render(); showToast(`Numbered ${ids.length} invoice(s)`, 'success'); }
    catch (e) { showToast(e.message, 'danger'); }
}

async function verify(on) {
    const ids = tickedIds(); if (!ids.length) return;
    let force = false;
    const sent = shown().filter(d => ids.includes(d.id) && d.status === 'sent').map(d => d.inv_no);
    if (!on && sent.length) {
        if (!await confirmBox('Take back invoices already in Tally?', `${sent.join(', ')} ${sent.length > 1 ? 'are' : 'is'} marked as sent. ` +
            'Delete them in Tally first (Alt+D), then they can be corrected here and sent again.')) return;
        force = true;
    }
    try {
        DI.data = await apiJson('/api/drinv/verify', 'POST', { ids, on, force });
        render();
        renderHistory();
        const bad = DI.data.not_verified || [];
        showToast(bad.length ? `Not verified (fix the red points first): ${bad.join(', ')}` : (on ? 'Verified' : 'Back to draft'),
            bad.length ? 'danger' : 'success', bad.length ? 9000 : 3000);
    } catch (e) { showToast(e.message, 'danger'); }
}

async function removeDrafts() {
    const ids = tickedIds(); if (!ids.length) return;
    if (!await confirmBox('Delete drafts?', `${ids.length} draft invoice(s) will be removed from the hub (not from Tally).`)) return;
    try { DI.data = await apiJson('/api/drinv/delete', 'POST', { ids }); render(); } catch (e) { showToast(e.message, 'danger'); }
}

// ---------- Tally
function logLine(t) {
    const el = document.getElementById('di-log');
    el.style.display = 'block';
    el.textContent += `${new Date().toLocaleTimeString('en-GB')}  ${t}\n`;
    el.scrollTop = el.scrollHeight;
}

async function tallyCall(xml) {
    if (!ON_SITE) return (await apiJson('/api/drinv/tally', 'POST', { xml })).text;
    let r;
    try { r = await fetch(`${BRIDGE}/tally`, { method: 'POST', body: xml }); } catch (e) { throw new Error(BRIDGE_HELP); }
    const text = await r.text();
    if (!r.ok) { let m = text; try { m = JSON.parse(text).error; } catch (e) { /* text */ } throw new Error(m); }
    return text;
}

async function gzipB64(text) {
    if (typeof CompressionStream === 'undefined') return null;
    const stream = new Blob([text]).stream().pipeThrough(new CompressionStream('gzip'));
    const buf = new Uint8Array(await new Response(stream).arrayBuffer());
    let bin = '';
    for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    return btoa(bin);
}

async function learnFromTally(quiet = false) {
    try {
        const { requests } = await api('/api/drinv/learn-request');
        let msg = '', ok = false;
        const want = Object.keys(DI.data.config.plants), got = new Set();
        for (const x of requests) {
            const day = (x.match(/<SVFROMDATE[^>]*>([^<]+)</) || [])[1] || '';
            logLine(`Reading TAFE invoices of ${day} from Tally…`);
            const text = await tallyCall(x);
            const gz = await gzipB64(text);
            const r = await apiJson('/api/drinv/learn', 'POST', gz ? { gz } : { text });
            msg = r.message; ok = ok || r.ok;
            (r.learned || []).forEach(p => got.add(p));
            logLine(r.message);
            if (want.every(p => got.has(p))) break;
        }
        if (!quiet) showToast(msg, ok ? 'success' : 'danger', 7000);
        await loadDrafts();
        return ok;
    } catch (e) { logLine(`Error: ${e.message}`); showToast(e.message, 'danger', 9000); return false; }
}

async function sendToTally() {
    const sel = shown().filter(d => DI.ticked.has(d.id) && d.status === 'verified').map(d => d.id);
    const ids = sel.length ? sel : DI.data.drafts.filter(d => d.status === 'verified').map(d => d.id);
    if (!ids.length) return showToast('No verified invoices to send', 'danger');
    if (!await confirmBox('Send to Tally?', `${ids.length} verified invoice(s) will be created in Tally as ${DI.data.config.vtype}. ` +
        'Then generate the IRN (e-invoice) for them in Tally.')) return;
    const btn = document.getElementById('btn-send');
    btn.disabled = true;
    document.getElementById('di-log').textContent = '';
    try {
        let plan = await apiJson('/api/drinv/send-plan', 'POST', { ids });
        if (plan.need_learn.length) {
            logLine(`Learning the invoice format for ${plan.need_learn.join(', ')} first…`);
            await learnFromTally(true);
            plan = await apiJson('/api/drinv/send-plan', 'POST', { ids });
        }
        if (plan.no_fields.length && !await confirmBox('Tally fields will be empty',
            `The invoice format of ${plan.no_fields.join(', ')} is not learned from Tally, so NO OF PICES, NO OF PACKAGES, ` +
            'TOTAL NOS, Title and TOTAL KGS would reach Tally empty. Press Cancel and use "Learn invoice format from Tally" ' +
            '(see the message there), or Yes to send anyway and fill them in Tally.')) { btn.disabled = false; return; }
        if (plan.skipped.length) logLine(`Not verified, skipped: ${plan.skipped.join(', ')}`);
        let ok = 0, bad = 0;
        for (const it of plan.items) {
            try {
                const text = await tallyCall(it.xml);
                const r = await apiJson('/api/drinv/tally-result', 'POST', { id: it.id, text });
                if (r.ok) { ok++; logLine(`${it.inv_no}: created in Tally`); }
                else { bad++; logLine(`${it.inv_no}: Tally said: ${r.error}`); }
            } catch (e) { bad++; logLine(`${it.inv_no}: ${e.message}`); if (e.message === BRIDGE_HELP) break; }
        }
        showToast(`${ok} invoice(s) created in Tally${bad ? `, ${bad} not` : ''}. Now generate the IRN in Tally.`, bad ? 'danger' : 'success', 9000);
    } catch (e) { showToast(e.message, 'danger', 9000); }
    btn.disabled = false;
    loadDrafts();
}

// Refresh: start a new batch. The drafts not yet sent to Tally are removed (after asking), the upload box,
// Tally log and ticks are cleared, so the page is empty for the next DRs. Invoices already sent stay under
// "Sent to Tally".
async function refreshPage() {
    const open = (DI.data ? DI.data.drafts : []).filter(d => d.status !== 'sent').map(d => d.id);
    if (open.length) {
        if (!await confirmBox('Start a new batch?', `The ${open.length} invoice(s) not sent to Tally will be removed from this page. ` +
            'Invoices already sent to Tally are kept.')) return;
        try { await apiJson('/api/drinv/delete', 'POST', { ids: open }); } catch (e) { return showToast(e.message, 'danger'); }
    }
    document.getElementById('upload-msgs').innerHTML = '';
    const log = document.getElementById('di-log');
    log.textContent = ''; log.style.display = 'none';
    document.querySelectorAll('input[type=file]').forEach(i => { i.value = ''; });
    document.getElementById('inv-date').value = todayIso();
    document.getElementById('start-no').value = '';
    DI.ticked.clear();
    DI.filter = 'open';
    await loadDrafts();
    showToast('Page cleared — upload the new DRs', 'success');
}

document.getElementById('inv-date').value = todayIso();
loadDrafts();
