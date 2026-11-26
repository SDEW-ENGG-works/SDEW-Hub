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
    document.getElementById('t-learned').innerHTML =
        `<li>✅ Invoice format taken from SDEW's own Tally invoices (read 25 Nov): Title, NO OF PICES, NO OF PACKAGES, TOTAL NOS, ` +
        'Party Name (TAFE/MDU, TAFE/DBR), PO NUMBER, TAFE Key ID, buyer / consignee address, Round Off, order date 1-Jul-17.</li>';
}

function shown() {
    let ds = DI.data ? DI.data.drafts : [];
    const q = (DI.q || '').trim().toLowerCase();
    if (q) ds = ds.filter(d => [d.inv_no, d.dr_no, d.part, d.po_no, d.item_name, d.remarks].some(x => (x || '').toLowerCase().includes(q)));
    if (DI.filter === 'all' || q) return ds;          // a search looks in every status
    if (DI.filter === 'open') return ds.filter(d => d.status !== 'sent');
    return ds.filter(d => d.status === DI.filter);
}

// "DR 12070477" in a message -> show that invoice (any status)
function findInvoice(q) {
    DI.q = q;
    const box = document.getElementById('di-q');
    if (box) box.value = q;
    render();
}

function render() {
    const c = DI.data.counts || {};
    const cnt = { open: (c.draft || 0) + (c.verified || 0), draft: c.draft || 0, verified: c.verified || 0, sent: c.sent || 0 };
    cnt.all = cnt.open + cnt.sent;
    document.getElementById('di-filter').innerHTML = FILTERS.map(([k, l]) =>
        `<button class="di-chip ${DI.filter === k ? 'on' : ''}" onclick="DI.filter='${k}';DI.q='';render()">${l} <b>${cnt[k]}</b></button>`).join('') +
        `<input type="search" id="di-q" placeholder="Find invoice no, DR, part, PO…" value="${esc(DI.q || '')}"
            style="margin-left:auto;min-width:220px;padding:.35rem .55rem;border:1px solid #cbd5e1;border-radius:8px"
            oninput="DI.q=this.value;render();const b=document.getElementById('di-q');b.focus();b.setSelectionRange(b.value.length,b.value.length)">`;
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
    const ed = (d, k, v, cls = '', w = '') => d.status === 'sent' ? `<span class="ro ${cls}">${esc(v ?? '')}</span>`
        : `<input class="ed ${cls}" ${w} value="${esc(v ?? '')}" onchange="edit(${d.id}, '${k}', this.value)">`;
    const box = (d, k, v, label, hint) => `<label class="mini"><span>${label}</span>${ed(d, k, v, 'num' + (v ? '' : ' miss'),
        `placeholder="enter" data-nav="${d.id}:${k}"${hint ? ` title="${esc(hint)}"` : ''}`)}</label>`;
    // one compact line per invoice (fits the page width, no sideways scrolling); the points to check go in a
    // thin line under it
    const was = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.nav
        ? { nav: document.activeElement.dataset.nav, val: document.activeElement.value,
            typed: document.activeElement.value !== document.activeElement.defaultValue } : null;
    t.innerHTML = `<colgroup><col style="width:2.5%"><col style="width:10%"><col style="width:8%"><col style="width:14.5%">
        <col style="width:14%"><col style="width:7%"><col style="width:8.5%"><col style="width:10%"><col style="width:7.5%">
        <col style="width:13%"><col style="width:5%"></colgroup>
        <thead><tr><th><input type="checkbox" ${allOn ? 'checked' : ''} onchange="tickAll(this.checked)"></th>
        <th>Invoice no · date</th><th>Plant · DR · PO</th><th>Part · Tally item</th>
        <th title="TOTAL NOS / NO OF PACKAGES / NO OF PICES in Tally">Total nos · Packages · Pieces</th><th>Title</th>
        <th class="num">Rate</th><th>GST</th><th class="num">Taxable · Total</th><th>Remarks</th><th>Status</th></tr></thead><tbody>` +
        ds.map(d => {
            const errs = d.issues.filter(i => i.level === 'error');
            const notes = d.status === 'sent' ? [] : d.issues;
            const sub = notes.length || (d.tally_msg && d.status !== 'sent');
            const st = d.status === 'sent' ? 'In Tally' : d.status === 'verified' ? 'Verified' : (errs.length ? 'Draft' : 'Ready');
            return `<tr class="${d.status} main${sub ? ' has-sub' : ''}">
            <td><input type="checkbox" ${DI.ticked.has(d.id) ? 'checked' : ''} onchange="tick(${d.id}, this.checked)"></td>
            <td>${ed(d, 'inv_no', d.inv_no, '', 'placeholder="auto from Tally"')}
                ${d.status === 'sent' ? `<div class="di-small">${dmy(d.inv_date)}</div>` : `<input class="ed small" type="date" value="${esc(d.inv_date)}" onchange="edit(${d.id}, 'inv_date', this.value)">`}</td>
            <td><b>${esc(d.plant || '?')}</b> <span class="di-dr">DR ${esc(d.dr_no)}</span><div class="di-small">PO ${esc(d.po_no)}</div></td>
            <td class="clip"><b>${esc(d.part)}</b> <span class="di-small" title="${esc(d.descr || '')}">${esc(d.descr || '')}</span>
                ${ed(d, 'item_name', d.item_name, 'small' + (d.item_name ? '' : ' miss'), `placeholder="Tally stock item" title="${esc(d.item_name || '')}"`)}</td>
            <td><div class="trio">${box(d, 'qty', num(d.qty), 'Total', `DR qty ${num(d.dr_qty)}`)}${box(d, 'packages', num(d.packages), 'Pkgs', `DR: ${num(d.dr_req)} ${d.bin || ''}`)}${box(d, 'pieces', num(d.pieces), 'Pcs', `DR: ${num(d.dr_size)} each`)}</div>
                <div class="di-small">DR ${num(d.dr_req)} ${esc(d.bin || '')} × ${num(d.dr_size)} = ${num(d.dr_qty)}</div></td>
            <td>${ed(d, 'title', d.title ?? 'KANBAN', 'small')}</td>
            <td class="num">${ed(d, 'rate', d.rate == null ? '' : (+d.rate).toFixed(2), 'num' + (d.rate ? '' : ' miss'))}
                ${d.rate_po != null && d.rate != null && Math.abs(d.rate - d.rate_po) >= .005 ? `<div class="di-small">PO ${n2(d.rate_po)}</div>` : ''}
                ${priceCell(d)}</td>
            <td>${gstCell(d)}</td>
            <td class="num">${n2(d.amount)}<div><b>${n2(d.total)}</b></div>${d.round_off ? `<div class="di-small">R/O ${d.round_off > 0 ? '+' : ''}${(+d.round_off).toFixed(2)}</div>` : ''}</td>
            <td>${d.status === 'sent' ? `<span class="di-small">${esc(d.remarks || '')}</span>`
                : packCell(d)}</td>
            <td><span class="di-b ${d.status}${st === 'Ready' ? ' ready' : ''}">${st}</span>
                ${d.verified_by && d.status !== 'draft' ? `<div class="di-small">${esc(d.verified_by)}</div>` : ''}</td>
            </tr>` + (sub ? `<tr class="${d.status} sub"><td></td><td colspan="10"><div class="di-iss">${notes.map(i => `<span class="${i.level}">${esc(i.text).replace(/DR (\d{7,9})/g, (m, dr) => `<a href="#" onclick="findInvoice('${dr}');return false">DR ${dr}</a>`)}</span>`).join('')}
                ${d.tally_msg && d.status !== 'sent' ? `<span class="error">Tally: ${esc(d.tally_msg)}</span>` : ''}</div></td></tr>` : '');
        }).join('') + '</tbody>';
    if (was) {                 // the table was drawn again (a value was saved): stay in the same box
        const el = t.querySelector(`[data-nav="${was.nav}"]`);
        if (el) { el.focus(); if (was.typed) el.value = was.val; else el.select(); }
    }
    const sum = ds.reduce((a, d) => a + (d.total || 0), 0);
    document.getElementById('di-foot').textContent = `${ds.length} invoice(s), total ₹${inr(sum)}. Ticked: ${DI.ticked.size}.`;
}

// Remarks: crate (its lid from CHEP Transfer comes with it) or carton box, one count for crate and lid;
// "Other" keeps free text
function packCell(d) {
    const p = d.pack || { kind: 'text' };
    const crates = (DI.data.config && DI.data.config.crates) || [];
    const val = p.kind === 'crate' ? `crate:${p.crate}` : p.kind;
    const opts = crates.map(c => `<option value="crate:${c.crate}" ${val === 'crate:' + c.crate ? 'selected' : ''} title="Crate ${c.crate}${c.lid ? ' with lid ' + c.lid : ''}">${c.crate}</option>`).join('') +
        `<option value="carton" ${val === 'carton' ? 'selected' : ''}>Carton</option><option value="text" ${val === 'text' ? 'selected' : ''}>Other</option>`;
    const head = `<div class="pk"><select class="ed small" onchange="packSet(${d.id}, this.value)">${opts}</select>
        ${p.kind !== 'text' ? `<label class="pk-n" title="Crates and lids (the same count)"><input class="ed num small" type="number" min="1" value="${p.nos || ''}" data-nav="${d.id}:pack_nos"
            onchange="edit(${d.id}, 'pack_nos', this.value)"><span>nos</span></label>` : ''}</div>`;
    const text = p.kind === 'text'
        ? `<textarea class="ed small rem" rows="${Math.max(2, Math.ceil((d.remarks || '').length / 20))}" onchange="edit(${d.id}, 'remarks', this.value)">${esc(d.remarks || '')}</textarea>`
        : `<div class="pk-text">${esc(d.remarks || '')}</div>`;
    return head + text;
}

function packSet(id, v) {
    if (v === 'text') { const d = DI.data.drafts.find(x => x.id === id); if (d) { d.pack = { kind: 'text' }; render(); } return; }
    if (v === 'carton') return edit(id, 'pack_kind', 'carton');
    apiJson(`/api/drinv/drafts/${id}`, 'POST', { pack_kind: 'crate', pack_crate: v.split(':')[1] }).then(() => loadDrafts())
        .catch(e => showToast(e.message, 'danger'));
}

// PO price period: which of the PO's prices the invoice uses (picked by its "price as on" day)
const sd = iso => iso && iso < '9999' ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(2, 4)}` : '';
function priceCell(d) {
    const on = d.price_date || d.inv_date;
    if (d.status === 'sent') return d.price_date ? `<div class="di-small">price as on ${dmy(d.price_date)}</div>` : '';
    const ps = d.periods || [];
    if (!ps.length) return '<div class="di-small" style="color:#b91c1c">no PO price</div>';
    const cur = ps.find(p => p.from <= on && on <= p.to);
    const opts = ps.map(p => `<option value="${p.from}" ${cur === p ? 'selected' : ''} title="${sd(p.from)}${p.to < '9999' ? ' to ' + sd(p.to) : ' onwards'}">${n2(p.rate)} · ${p.from.slice(8, 10)}.${p.from.slice(5, 7)}</option>`).join('');
    return `<select class="ed small pp" title="PO price period used" onchange="edit(${d.id}, 'price_date', this.value === '${esc(d.inv_date)}' ? '' : this.value)">
        ${cur ? '' : '<option selected value="">no price on this day</option>'}${opts}</select>
        ${d.price_date ? `<div class="di-small">as on ${sd(d.price_date)} <a href="#" onclick="edit(${d.id}, 'price_date', ''); return false" title="back to the invoice date">↺</a></div>` : ''}`;
}

async function priceDateTicked() {
    const ids = tickedIds(); if (!ids.length) return;
    const price_date = document.getElementById('bulk-price-date').value;
    try {
        DI.data = await apiJson('/api/drinv/price-date', 'POST', { ids, price_date });
        render(); renderHistory();
        showToast(`PO price ${price_date ? 'as on ' + dmy(price_date) : 'of the invoice date'} for ${ids.length} invoice(s) - verify them again`, 'success', 6000);
    } catch (e) { showToast(e.message, 'danger'); }
}

// GST shown the way the invoice prints it: CGST 2.5 % + SGST 2.5 % (MDU, Tamil Nadu) or IGST 5 % (DBR)
function gstCell(d) {
    const g = +d.gst_rate || 0;
    const rate = d.status === 'sent' ? `${num(g)}%` :
        `<input class="ed num tiny" value="${num(g)}" onchange="edit(${d.id}, 'gst_rate', this.value)">%`;
    const lines = d.igst
        ? `<div>IGST ${num(g)}% <b>₹${n2(d.igst)}</b></div>`
        : `<div>CGST ${num(g / 2)}% <b>₹${n2(d.cgst)}</b></div><div>SGST ${num(g / 2)}% <b>₹${n2(d.sgst)}</b></div>`;
    return `<div class="di-small">GST ${rate}</div>${lines}`;
}

function renderHistory() { if (document.getElementById('history-view').classList.contains('active')) loadHistory(); }

// ---------- History: batches (same action, same person, within 15 minutes), each opens to its invoices
const HS = { action: '', open: new Set(), data: null };
const HS_LOOK = {
    'Sent to Tally': ['#166534', '#dcfce7', g => `Sent ${g.count} invoice${g.count > 1 ? 's' : ''} to Tally`],
    'Tally refused': ['#991b1b', '#fee2e2', g => `Tally refused ${g.count} invoice${g.count > 1 ? 's' : ''}`],
    'Uploaded DR': ['#1e40af', '#dbeafe', g => `Uploaded ${g.events} DR file${g.events > 1 ? 's' : ''} → ${g.count} invoice draft${g.count > 1 ? 's' : ''}`],
    'Verified': ['#3730a3', '#e0e7ff', g => `Verified ${g.count} invoice${g.count > 1 ? 's' : ''}`],
    'Numbered': ['#92400e', '#fef3c7', g => `Numbered ${g.count} invoice${g.count > 1 ? 's' : ''}`],
    'Numbered from Tally': ['#92400e', '#fef3c7', g => `Numbered ${g.count} invoice${g.count > 1 ? 's' : ''} from Tally's last number`],
    'Deleted drafts': ['#475569', '#f1f5f9', g => `Deleted ${g.count} draft${g.count > 1 ? 's' : ''}`],
};
const hsTime = iso => new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
const hsClock = iso => new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

async function loadHistory() {
    const day = document.getElementById('hs-day').value;
    try { HS.data = await api(`/api/drinv/history?action=${encodeURIComponent(HS.action)}&day=${day}`); }
    catch (e) { return showToast(e.message, 'danger'); }
    const acts = ['', ...HS.data.actions];
    document.getElementById('hs-chips').innerHTML = acts.map(a => `<button class="di-chip ${HS.action === a ? 'on' : ''}"
        onclick="HS.action='${esc(a)}';HS.open.clear();loadHistory()">${esc(a || 'All')}</button>`).join('');
    const gs = HS.data.groups;
    const sent = gs.filter(g => g.action === 'Sent to Tally');
    document.getElementById('hs-sum').innerHTML = gs.length ? `${gs.length} batch${gs.length > 1 ? 'es' : ''}` +
        (sent.length ? ` · <b>${sent.reduce((a, g) => a + g.count, 0)}</b> invoices sent to Tally for <b>₹${inr(sent.reduce((a, g) => a + g.total, 0))}</b>` : '') : '';
    document.getElementById('hs-list').innerHTML = gs.length ? gs.map((g, i) => hsBatch(g, i)).join('')
        : '<p class="muted" style="padding:1rem">Nothing here.</p>';
}

function hsBatch(g, i) {
    const [fg, bg, title] = HS_LOOK[g.action] || ['#334155', '#f1f5f9', x => `${x.action}${x.count > 1 ? ` (${x.count})` : ''}`];
    const key = `${g.action}|${g.start}`, open = HS.open.has(key);
    const range = g.first ? (g.first === g.last ? g.first : `${g.first} → ${g.last}`) : '';
    const plants = Object.entries(g.plants || {}).map(([p, n]) => `${p} ${n}`).join(' · ');
    const when = g.start.slice(0, 16) === g.end.slice(0, 16) ? hsTime(g.start) : `${hsTime(g.start)} – ${hsClock(g.end)}`;
    return `<div class="hs-batch ${open ? 'open' : ''}">
        <div class="hs-head" onclick="hsToggle('${esc(key)}')">
            <span class="hs-arrow">${open ? '▾' : '▸'}</span>
            <span class="hs-when">${esc(when)}</span>
            <span class="hs-badge" style="color:${fg};background:${bg}">${esc(g.action)}</span>
            <span class="hs-title">${esc(title(g))}</span>
            ${range ? `<span class="hs-meta">${esc(range)}</span>` : ''}
            ${plants ? `<span class="hs-meta">${esc(plants)}</span>` : ''}
            ${g.total ? `<span class="hs-amt">₹${inr(g.total)}</span>` : ''}
            <span class="hs-who">${esc(g.user || '')}</span>
        </div>
        ${open ? hsDetail(g, i) : ''}
    </div>`;
}

function hsToggle(key) { HS.open.has(key) ? HS.open.delete(key) : HS.open.add(key); loadHistoryRender(); }
function loadHistoryRender() {
    if (!HS.data) return loadHistory();
    document.getElementById('hs-list').innerHTML = HS.data.groups.map((g, i) => hsBatch(g, i)).join('');
}

function hsDetail(g, i) {
    const it = g.items || [];
    if (!it.length) return `<div class="hs-body"><ul class="hs-notes">${g.details.map(d => `<li>${esc(d)}</li>`).join('')}</ul></div>`;
    const tax = x => x.igst ? `IGST ${num(x.gst_rate)}% ₹${n2(x.igst)}` : (x.cgst ? `CGST ${num(x.gst_rate / 2)}% ₹${n2(x.cgst)} · SGST ₹${n2(x.sgst)}` : '');
    const rows = it.map(x => `<tr>
        <td><b>${esc(x.inv_no || '—')}</b><div class="di-small">${x.inv_date ? dmy(x.inv_date) : ''}</div></td>
        <td><b>${esc(x.plant || '')}</b><div class="di-small">DR ${esc(x.dr_no || '')}</div><div class="di-small">PO ${esc(x.po_no || '')}</div></td>
        <td><b>${esc(x.part || '')}</b><div class="di-small">${esc(x.item_name || x.descr || '')}</div></td>
        <td class="num">${num(x.qty)}</td><td class="num">${num(x.packages)}</td><td class="num">${num(x.pieces)}</td>
        <td class="num">${x.rate != null ? n2(x.rate) : ''}${x.price_date ? `<div class="di-small">as on ${dmy(x.price_date)}</div>` : ''}</td>
        <td class="num">${n2(x.amount)}</td><td class="di-small">${tax(x)}</td>
        <td class="num"><b>${n2(x.total)}</b>${x.round_off ? `<div class="di-small">R/O ${(+x.round_off).toFixed(2)}</div>` : ''}</td>
        <td class="di-small">${esc(x.remarks || '')}</td>
        <td class="di-small">${esc(x.tally_msg || x.status || '')}</td></tr>`).join('');
    const sum = k => it.reduce((a, x) => a + (+x[k] || 0), 0);
    return `<div class="hs-body">
        <div class="hs-tools"><span class="di-small">${it.length} invoice(s) · taxable ₹${inr(sum('amount'))} · GST ₹${inr(sum('cgst') + sum('sgst') + sum('igst'))} · total ₹${inr(sum('total'))}</span>
            <button class="btn btn-secondary btn-sm" onclick="hsCsv(${i})">Download (Excel CSV)</button></div>
        <div class="table-wrapper"><table class="data-table compact hs-table">
        <thead><tr><th>Invoice</th><th>Plant · DR · PO</th><th>Part · Tally item</th><th class="num">Total nos</th><th class="num">Pkgs</th>
        <th class="num">Pcs</th><th class="num">Rate</th><th class="num">Taxable</th><th>GST</th><th class="num">Total</th><th>Remarks</th><th>Result</th></tr></thead>
        <tbody>${rows}<tr class="hs-tot"><td colspan="3"><b>Total</b></td><td class="num">${num(sum('qty'))}</td><td class="num">${num(sum('packages'))}</td><td></td><td></td>
        <td class="num">${n2(sum('amount'))}</td><td class="di-small">₹${n2(sum('cgst') + sum('sgst') + sum('igst'))}</td><td class="num"><b>${n2(sum('total'))}</b></td><td></td><td></td></tr></tbody>
        </table></div></div>`;
}

function hsCsv(i) {
    const g = HS.data.groups[i];
    const cols = ['inv_no', 'inv_date', 'plant', 'party', 'dr_no', 'po_no', 'part', 'item_name', 'qty', 'packages', 'pieces', 'title', 'rate',
        'price_date', 'gst_rate', 'amount', 'cgst', 'sgst', 'igst', 'round_off', 'total', 'remarks', 'status', 'tally_msg'];
    const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [cols.join(','), ...g.items.map(x => cols.map(c => q(x[c])).join(','))].join('\r\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv' }));
    a.download = `${g.action.replace(/\W+/g, '_')}_${g.start.slice(0, 16).replace(/[:T]/g, '-')}.csv`;
    a.click();
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
            const pd = document.getElementById('price-date').value;
            const r = await api(`/api/drinv/upload?name=${encodeURIComponent(f.name)}&date=${date}${pd ? `&price_date=${pd}` : ''}`, { method: 'POST', body: f });
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
    // from Tally's last number NOW (asked through the Tally bridge); only if Tally cannot be reached, from the box
    try {
        const r = await apiJson('/api/drinv/assign-numbers', 'POST', Object.assign({ ids }, await tallyAnswer((await api('/api/drinv/numbers-request')).xml)));
        document.getElementById('start-no').value = r.next;
        document.getElementById('tally-last').textContent = r.last ? `Tally's last: ${r.last}` : '';
        await loadDrafts();
        showToast(`Tally's last invoice ${r.last}: numbered ${r.given[0] || ''} to ${r.given[r.given.length - 1] || ''}` +
            (r.reopened.length ? `. Not in Tally any more, back to draft: ${r.reopened.join(', ')}` : ''), 'success', 9000);
        return;
    } catch (e) {
        if (!await confirmBox('Tally not reached', `${e.message}. Number the ticked invoices from ${document.getElementById('start-no').value} instead?`)) return;
    }
    const start = document.getElementById('start-no').value.trim();
    const order = shown().filter(d => ids.includes(d.id)).sort((a, b) => (a.plant || '').localeCompare(b.plant || '') || a.dr_no.localeCompare(b.dr_no)).map(d => d.id);
    try { DI.data = await apiJson('/api/drinv/number', 'POST', { start, ids: order }); render(); showToast(`Numbered ${ids.length} invoice(s) from ${start}`, 'success'); }
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
function logLine(t, id = 'di-log') {
    const el = document.getElementById(id);
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

// Tally's answer to a request, ready to post to the hub (gzip when the browser can)
async function tallyAnswer(xml) {
    const text = await tallyCall(xml);
    const gz = await gzipB64(text);
    return gz ? { gz } : { text };
}

async function nextFromTally() {
    try {
        const r = await apiJson('/api/drinv/tally-next', 'POST', await tallyAnswer((await api('/api/drinv/numbers-request')).xml));
        document.getElementById('start-no').value = r.next;
        document.getElementById('tally-last').textContent = r.last ? `Tally's last: ${r.last}` : '';
        showToast(`Last invoice ${r.last} (from ${r.source}, ${r.count} invoice numbers read from Tally): numbers start from ${r.next}` +
            (r.reopened && r.reopened.length ? `. Not in Tally any more, back to draft: ${r.reopened.join(', ')}` : ''), 'success', 9000);
        if (r.reopened && r.reopened.length) loadDrafts();
    } catch (e) { showToast(e.message, 'danger', 9000); }
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

async function learnFile(f) {
    if (!f) return;
    try {
        const r = await api(`/api/drinv/learn-file?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
        logLine(r.message);
        showToast(r.message, r.ok ? 'success' : 'danger', 9000);
        loadDrafts();
    } catch (e) { showToast(e.message, 'danger', 9000); }
}

async function sendToTally() {
    const sel = shown().filter(d => DI.ticked.has(d.id) && d.status === 'verified').map(d => d.id);
    const ids = sel.length ? sel : DI.data.drafts.filter(d => d.status === 'verified').map(d => d.id);
    if (!ids.length) return showToast('No verified invoices to send', 'danger');
    if (!await confirmBox('Send to Tally?', `${ids.length} verified invoice(s) will be created in Tally as ${DI.data.config.vtype}, numbered from Tally's last invoice number + 1 ` +
        '(in plant / DR order). ' +
        'Then generate the IRN (e-invoice) for them in Tally.')) return;
    const btn = document.getElementById('btn-send');
    btn.disabled = true;
    document.getElementById('di-log').textContent = '';
    try {
        // invoice numbers straight from Tally: its last number now (invoices typed by hand included) + 1, 2, ...
        logLine('Asking Tally for its last invoice number…');
        const nr = await apiJson('/api/drinv/assign-numbers', 'POST', Object.assign({ ids }, await tallyAnswer((await api('/api/drinv/numbers-request')).xml)));
        logLine(`Tally's last invoice: ${nr.last || '—'}` + (nr.changed.length
            ? `. Numbered: ${nr.changed.map(c => (c.old ? c.old + ' → ' : '') + c.new).join(', ')}` : '. Numbers kept.'));
        document.getElementById('tally-last').textContent = nr.last ? `Tally's last: ${nr.last}` : '';
        let plan = await apiJson('/api/drinv/send-plan', 'POST', { ids });
        if (plan.need_learn.length) {
            logLine(`Learning the invoice format for ${plan.need_learn.join(', ')} first…`);
            await learnFromTally(true);
            plan = await apiJson('/api/drinv/send-plan', 'POST', { ids });
        }
        if (plan.no_fields.length) {          // never send without the packing fields: Tally would get them empty
            logLine(`Not sent: the invoice format of ${plan.no_fields.join(', ')} is not learned, so NO OF PICES, ` +
                'NO OF PACKAGES, TOTAL NOS and Title cannot be written in Tally. Upload a Tally invoice (XML) for it first.');
            showToast('Not sent - learn the invoice format first (Upload a Tally invoice, XML)', 'danger', 9000);
            btn.disabled = false; return;
        }
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
        // read back from Tally the numbers it really gave (its automatic numbering may differ from the hub's)
        try {
            const back = await apiJson('/api/drinv/tally-next', 'POST', await tallyAnswer((await api('/api/drinv/numbers-request')).xml));
            logLine(`Tally's last invoice now: ${back.last}`);
        } catch (e) { logLine(`Could not read the numbers back from Tally: ${e.message}`); }
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

// ---------- Read Tally structure
async function loadStructure() {
    let r;
    try { r = await api('/api/drinv/structure'); } catch (e) { return; }
    const box = document.getElementById('st-nos');
    if (!box.value && r.defaults.length) box.value = r.defaults.join(', ');
    const t = document.getElementById('st-table');
    t.innerHTML = r.samples.length ? `<thead><tr><th>When</th><th>What</th><th>Size</th><th>Found</th></tr></thead><tbody>` +
        r.samples.map(x => {
            const s = x.summary || {};
            const found = s.error ? `<span style="color:#b91c1c">${esc(s.error)}</span>` : [
                s.udf ? `<div><b>Fields:</b> ${esc(s.udf.map(u => u.tag + ' ' + u.attrs).join(' · ') || 'none')}</div>` : '',
                s.address ? `<div><b>Address:</b> ${esc(s.address.join(' · ') || 'none')}</div>` : '',
                s.ledgers ? `<div><b>Ledger lines:</b> ${esc(s.ledgers.map(l => `${l.LEDGERNAME} ${l.AMOUNT} (${l.ISDEEMEDPOSITIVE}/${l.ISLASTDEEMEDPOSITIVE || '-'})`).join(' · '))}</div>` : '',
                s.tags ? `<div class="di-small">${esc(s.tags.join(', '))}</div>` : '',
                s.size ? `${inr(s.size, 0)} characters` : ''].join('');
            return `<tr><td style="white-space:nowrap">${esc(when(x.at))}<div class="di-small">${esc(x.user || '')}</div></td>
                <td><b>${esc(x.kind)}</b><div>${esc(x.ref)}</div></td><td class="num">${inr(x.size || 0, 0)}</td>
                <td style="font-size:.75rem">${found} <a href="/api/drinv/structure-download?ids=${x.id}" download>download</a></td></tr>`;
        }).join('') + '</tbody>' : '<tr><td class="muted" style="padding:.8rem">Nothing read yet.</td></tr>';
}

async function readStructure() {
    const btn = document.getElementById('btn-structure');
    const nos = document.getElementById('st-nos').value.split(/[,\s]+/).filter(Boolean);
    btn.disabled = true;
    document.getElementById('st-log').textContent = '';
    try {
        const plan = await apiJson('/api/drinv/structure-plan', 'POST', { nos });
        if (plan.unknown.length) logLine(`Not found in the hub's Tally data (pull from Tally first, or check the number): ${plan.unknown.join(', ')}`, 'st-log');
        for (const q of plan.requests) {
            logLine(`Reading ${q.kind} ${q.ref} from Tally…`, 'st-log');
            try {
                const text = await tallyCall(q.xml);
                const gz = await gzipB64(text);
                const r = await apiJson('/api/drinv/structure-save', 'POST', Object.assign({ kind: q.kind, ref: q.ref, want: q.want }, gz ? { gz } : { text }));
                r.saved.forEach(x => logLine(`  saved ${x.kind} ${x.ref} (${x.size} characters)${x.summary && x.summary.error ? ' - ' + x.summary.error : ''}`, 'st-log'));
                if (r.learn) logLine(`  ${r.learn.message}`, 'st-log');
            } catch (e) { logLine(`  ${e.message}`, 'st-log'); if (e.message === BRIDGE_HELP) break; }
        }
        showToast('Tally structure read and saved in the hub', 'success');
    } catch (e) { showToast(e.message, 'danger', 9000); }
    btn.disabled = false;
    loadStructure();
    loadDrafts();
}

// ---------- Delivery challans from Tally (Admin)
async function loadDC() {
    let r;
    const q = (document.getElementById('dc-q') || {}).value || '';
    try { r = await api(`/api/drinv/dc?q=${encodeURIComponent(q)}`); } catch (e) { return; }
    const s = r.summary || {};
    document.getElementById('dc-sum').textContent = s.n ? `${inr(s.n, 0)} DCs in the hub, ${dmy(s.first)} to ${dmy(s.last)} · pulled ${when(s.pulled)}` : 'No DC pulled yet';
    const t = document.getElementById('dc-table');
    t.innerHTML = r.dcs.length ? `<thead><tr><th>DC no</th><th>Date</th><th>Party</th><th>PO</th><th>Items</th><th>Qty</th>
        <th>Pcs / Pkgs / Total</th><th>Narration</th></tr></thead><tbody>` + r.dcs.map(d => `<tr${d.cancelled ? ' style="opacity:.5"' : ''}>
        <td><b>${esc(d.vno)}</b>${d.cancelled ? '<div class="di-small" style="color:#b91c1c">cancelled</div>' : ''}<div class="di-small">${esc(d.vtype)}</div></td>
        <td style="white-space:nowrap">${dmy(d.vdate)}</td><td>${esc(d.party)}${d.party_name ? `<div class="di-small">${esc(d.party_name)}</div>` : ''}</td>
        <td>${esc(d.po_no || d.order_no || '')}</td>
        <td style="min-width:220px">${d.lines.map(l => `<div>${esc(l.item)} <span class="di-small">${num(l.qty)} ${esc(l.unit || '')}${l.rate ? ' @ ' + inr(l.rate) : ''}</span></div>`).join('')}</td>
        <td class="num">${num(d.qty)}</td><td>${[d.pieces, d.packages, d.total_nos].map(x => esc(x || '–')).join(' / ')}</td>
        <td style="min-width:220px">${esc(d.narration || '')}</td></tr>`).join('') + '</tbody>'
        : `<tr><td class="muted" style="padding:.8rem">${q ? 'No DC matches.' : 'No DC pulled yet.'}</td></tr>`;
}

async function pullDC() {
    const from = document.getElementById('dc-from').value, to = document.getElementById('dc-to').value || todayIso();
    if (!from) return showToast('Pick the From date', 'danger');
    const btn = document.getElementById('btn-dc');
    btn.disabled = true;
    document.getElementById('dc-log').textContent = '';
    let total = 0, bad = 0;
    try {
        const plan = await apiJson('/api/drinv/dc/plan', 'POST', { from, to });
        for (const c of plan.chunks) {
            logLine(`${dmy(c.from)} – ${dmy(c.to)}: reading DCs from Tally…`, 'dc-log');
            try {
                let r = null;
                for (const xml of [c.xml, c.xml_plain]) {
                    const text = await tallyCall(xml);
                    const gz = await gzipB64(text);
                    r = await apiJson('/api/drinv/dc/save', 'POST', Object.assign({ from: c.from, to: c.to }, gz ? { gz } : { text }));
                    if (r.ok) break;
                    logLine(`  Tally said: ${r.error} - trying the simple request`, 'dc-log');
                }
                if (!r.ok) { bad++; logLine(`  not read: ${r.error}`, 'dc-log'); continue; }
                total += r.dcs || 0;
                logLine(r.note ? `  ${r.note}` : `  ${r.dcs} DC(s), ${r.lines} item line(s)${r.with_fields ? `, ${r.with_fields} with pieces / packages` : ''}`, 'dc-log');
            } catch (e) { bad++; logLine(`  ${e.message}`, 'dc-log'); if (e.message === BRIDGE_HELP) break; }
        }
        showToast(`${total} DC(s) pulled from Tally${bad ? `, ${bad} period(s) not read` : ''}`, bad ? 'danger' : 'success', 7000);
    } catch (e) { showToast(e.message, 'danger', 9000); }
    btn.disabled = false;
    loadDC();
}

async function dqmsSync() {
    try { const r = await apiJson('/api/drinv/dqms-sync', 'POST', {}); showToast(`DQMS Upload: ${r.invoices} invoice(s), ${r.drs} new DR line(s) copied`, 'success', 7000); }
    catch (e) { showToast(e.message, 'danger'); }
}

// ---------- tabs: Main page / History / Admin (Admin only for admins when login is on)
function switchView(name) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(`${name}-view`).classList.add('active');
    document.getElementById(`nav-${name}-btn`).classList.add('active');
    try { history.replaceState(null, '', `#${name}`); } catch (e) { /* ignore */ }
    if (name === 'main') loadDrafts();
    else if (name === 'history') loadHistory();
    else if (name === 'admin') { loadStructure(); loadDC(); }
}

(function () {
    const me = window.HUB_USER;
    if (me && me.login && !me.admin) document.getElementById('nav-admin-btn').style.display = 'none';
})();

document.getElementById('inv-date').value = todayIso();
loadDrafts();
loadStructure();
document.getElementById('dc-to').value = todayIso();
{
    const tab = location.hash.replace('#', '');
    if (['history', 'admin'].includes(tab) && document.getElementById(`nav-${tab}-btn`).style.display !== 'none') switchView(tab);
}

// Enter (or Tab) in Total -> Pkgs -> Pcs -> crate nos -> the next invoice's Total, like a form: the value is
// saved and the cursor goes on to the next box
document.addEventListener('keydown', e => {
    const el = e.target;
    if (!el.dataset || !el.dataset.nav || !(e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey))) return;
    const all = [...document.querySelectorAll('#di-table [data-nav]')];
    const next = all[all.indexOf(el) + 1];
    if (!next) return;
    e.preventDefault();
    next.focus();              // leaving the box saves it (its change event), once
    next.select();
});
