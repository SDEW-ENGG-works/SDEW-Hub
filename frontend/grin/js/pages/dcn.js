// Debit / credit notes from TAFE Channel: fetch (Get data step 4) and the 'Debit notes' tab.

const DCN = { data: null, tab: 'docs', q: '', lines: {} };
const DCN_KIND = {
    'Rate difference': { cls: 'st-od', hint: 'TAFE paid the PO rate – we billed a higher rate' },
    'Rejection': { cls: 'st-ng', hint: 'parts rejected and scrapped on our account (TAFE tax invoice)' },
    'Cash discount': { cls: 'st-wait', hint: 'deducted for paying early' },
    'Credit note': { cls: 'st-paid', hint: 'TAFE gives money back' },
    'Premium freight': { cls: 'st-short', hint: 'urgent freight TAFE paid on our behalf' },
    'Freight charges': { cls: 'st-short', hint: 'transport TAFE paid (free delivery / rejected material moved)' },
    'Rework / segregation': { cls: 'st-debit', hint: '2% for rework / sorting done at TAFE' },
    'Shortage': { cls: 'st-ng', hint: 'less quantity received than billed' },
    'Other debit': { cls: 'st-debit', hint: 'other debit intimations' },
};

document.addEventListener('DOMContentLoaded', () => {
    const t = new Date();
    const fy = t.getMonth() >= 3 ? t.getFullYear() : t.getFullYear() - 1;
    const f = document.getElementById('dcn-from'), to = document.getElementById('dcn-to');
    if (f) f.value = `${fy}-04-01`;
    if (to) to.value = new Date(t.getTime() - t.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    api('/api/grin/notes/fetch').then(showDcn).catch(() => { });
    dcnKv();
});

// ---------- Get data: fetch ----------
function showDcn(st) {
    const b = document.getElementById('dcn-badge');
    if (!b) return;
    if (st.running) { b.className = 'status-badge sent'; b.textContent = 'Fetching…'; }
    else if (st.error) { b.className = 'status-badge inactive'; b.textContent = 'Last fetch stopped'; }
    else if (st.finished) { b.className = 'status-badge active'; b.textContent = `Last fetch ${when(st.finished)}`; }
    else { b.className = 'status-badge muted'; b.textContent = 'Ready'; }
    showLog('dcn-log', st.log);
    document.getElementById('btn-dcn').disabled = !!st.running;
}

async function dcnKv() {
    try {
        const s = await api('/api/grin/notes');
        const k = s.kinds || {};
        const el = document.getElementById('dcn-kv');
        if (!el) return;
        el.innerHTML = `<dt>Loaded</dt><dd>${s.docs.length ? `${inr(s.docs.length, 0)} documents, ${dmy(s.range.first)} to ${dmy(s.range.last)}` : 'not yet'}</dd>
            ${Object.entries(k).map(([n, v]) => `<dt>${esc(n)}</dt><dd>${inr(v.n, 0)} · ${rupees(v.amount)}</dd>`).join('')}
            ${s.unread ? `<dt>Still to read</dt><dd>${inr(s.unread, 0)} notes – press Fetch again</dd>` : ''}`;
    } catch (e) { /* page shows it */ }
}

let _dcnTimer = null;
async function dcnFetch() {
    const body = { from: document.getElementById('dcn-from').value, to: document.getElementById('dcn-to').value };
    document.getElementById('btn-dcn').disabled = true;
    showDcn({ running: true, log: ['Logging in to TAFE Channel…'] });
    const finish = st => {
        showToast(st.error ? esc(st.error) : 'Debit / credit notes loaded from TAFE Channel', st.error ? 'danger' : 'success', 9000);
        dcnKv(); loadStatus(0); DCN.data = null;
    };
    try {
        let r = await apiJson('/api/grin/notes/fetch', 'POST', body);
        showDcn(r);
        while (r.more && !r.error) {                // the website reads ~45 s per call - keep going
            r = await apiJson('/api/grin/notes/fetch', 'POST', body);
            showDcn(r);
        }
        if (r.done) { finish(r); return; }
        clearInterval(_dcnTimer);
        _dcnTimer = setInterval(async () => {
            try {
                const st = await api('/api/grin/notes/fetch');
                showDcn(st);
                if (!st.running) { clearInterval(_dcnTimer); finish(st); }
            } catch (e) { clearInterval(_dcnTimer); }
        }, 2500);
    } catch (e) {
        showDcn({ error: e.message, log: [`Stopped: ${e.message}`] });
        showToast(e.message, 'danger', 9000);
    }
}

// ---------- the Debit notes tab ----------
function dcnRange() {
    const p = new URLSearchParams();
    const f = document.getElementById('dcn-f').value, t = document.getElementById('dcn-t').value;
    if (f) p.set('from', f);
    if (t) p.set('to', t);
    return p;
}
function dcnDownload() { location.href = `/api/grin/notes/export?${dcnRange()}`; }

async function loadDcn() {
    const box = document.getElementById('dcn-body');
    box.innerHTML = '<div class="card muted-cell">Loading…</div>';
    try {
        DCN.data = await api(`/api/grin/notes?${dcnRange()}`);
        DCN.lines = {};
        renderDcn();
    } catch (e) { box.innerHTML = `<div class="banner danger">${esc(e.message)}</div>`; }
}

function renderDcn() {
    const d = DCN.data, box = document.getElementById('dcn-body');
    if (!d.docs.length) {
        box.innerHTML = `<div class="card"><p class="muted-cell">No debit / credit notes yet. Go to <a href="#" onclick="switchView('sources');return false">Get data</a> → step 4 and press <b>Fetch debit / credit notes</b>.</p></div>`;
        return;
    }
    const kinds = Object.entries(d.kinds).sort((a, b) => Math.abs(b[1].amount) - Math.abs(a[1].amount));
    const kNames = kinds.map(k => k[0]);
    box.innerHTML = `
        ${d.unread ? `<div class="banner">${inr(d.unread, 0)} note(s) not read yet – press Fetch again on Get data to see what is inside them.</div>` : ''}
        <div class="mr-cards">
            <div class="mr-card"><div class="k">Total debited (net)</div><div class="v">${rupees(d.total)}</div>
                <div class="s">${inr(d.docs.length, 0)} documents · ${dmy(d.range.first)} to ${dmy(d.range.last)}</div></div>
            ${kinds.map(([k, v]) => `<div class="mr-card"><div class="k"><span class="st ${(DCN_KIND[k] || {}).cls || ''}">${esc(k)}</span></div>
                <div class="v">${rupees(v.amount)}</div><div class="s">${inr(v.n, 0)} document(s) · ${esc((DCN_KIND[k] || {}).hint || '')}</div>
                ${v.deducted ? `<div class="s">${rupees(v.deducted)} already cut from a TAFE payment</div>` : ''}</div>`).join('')}
        </div>
        <div class="card">
            <div class="card-title">Month by month</div>
            <div class="table-wrapper"><table class="data-table grin-table">
                <thead><tr><th>Month</th>${kNames.map(k => `<th class="num">${esc(k)}</th>`).join('')}<th class="num">Total</th></tr></thead>
                <tbody>${d.months.map(m => `<tr><td><b>${esc(mrLabel(m.month))}</b></td>${kNames.map(k => {
                    const x = m.kinds[k]; return `<td class="num">${x ? rupees(x.amount) + `<span class="sub">${x.n} doc</span>` : '–'}</td>`;
                }).join('')}<td class="num"><b>${rupees(m.total)}</b></td></tr>`).join('')}</tbody>
            </table></div>
        </div>
        <div class="card">
            <div class="card-header-flex">
                <div class="category-pills" id="dcn-tabs">
                    ${[['docs', `Documents (${inr(d.docs.length, 0)})`], ['Rate difference', 'Rate difference – by invoice & part'],
                       ['Rejection', 'Rejections – parts'], ['Cash discount', 'Cash discount – by invoice'], ['parts', 'Rate difference – by part']]
                        .map(([k, l]) => `<button class="cat-pill ${DCN.tab === k ? 'active' : ''}" data-k="${esc(k)}">${esc(l)}</button>`).join('')}
                </div>
                <div class="search-box"><input type="text" id="dcn-search" placeholder="Invoice, part, document or PO…" value="${esc(DCN.q)}"></div>
            </div>
            <div class="table-wrapper" id="dcn-table"></div>
        </div>`;
    box.querySelectorAll('#dcn-tabs .cat-pill').forEach(b => b.onclick = () => {
        DCN.tab = b.dataset.k;
        box.querySelectorAll('#dcn-tabs .cat-pill').forEach(x => x.classList.toggle('active', x === b));
        dcnTable();
    });
    document.getElementById('dcn-search').oninput = e => { DCN.q = e.target.value; debounced(dcnTable, 250); };
    dcnTable();
}

async function dcnLines(kind) {
    if (!DCN.lines[kind]) DCN.lines[kind] = (await api(`/api/grin/notes/lines?kind=${encodeURIComponent(kind)}&limit=20000&${dcnRange()}`)).rows;
    return DCN.lines[kind];
}

async function dcnTable() {
    const el = document.getElementById('dcn-table');
    if (!el) return;
    const q = DCN.q.trim().toLowerCase();
    const hit = (...v) => !q || v.some(x => String(x ?? '').toLowerCase().includes(q));
    const LIMIT = 600;
    let head, list, body;
    if (DCN.tab === 'docs') {
        list = DCN.data.docs.filter(x => hit(x.doc_no, x.kind, x.reason, x.plant, x.pv));
        head = '<th>Document</th><th>Date</th><th>Type</th><th>Kind</th><th>Plant</th><th>Reason</th><th class="num">Amount</th><th>Cut from payment</th>';
        body = list.slice(0, LIMIT).map(x => `<tr><td><b>${esc(x.doc_no)}</b></td><td>${shortDate(x.doc_date)}</td>
            <td>${esc(x.doc_type)}<span class="sub">${esc(x.type_label)}</span></td>
            <td><span class="st ${(DCN_KIND[x.kind] || {}).cls || ''}">${esc(x.kind)}</span></td><td>${esc(x.plant)}</td>
            <td>${esc(x.reason || '')}${x.status === '' || x.status === 'error' ? '<span class="sub">not read yet</span>' : ''}</td>
            <td class="num"><b>${rupees(x.amount)}</b>${x.lines ? `<span class="sub">${x.lines} line(s)</span>` : ''}</td>
            <td>${x.pv ? `${esc(x.pv)}<span class="sub">${shortDate(x.pv_date)}</span>` : '<span class="sub">not yet</span>'}</td></tr>`);
    } else {
        el.innerHTML = '<p class="muted-cell">Loading…</p>';
        const kind = DCN.tab === 'parts' ? 'Rate difference' : DCN.tab;
        const all = await dcnLines(kind);
        if (DCN.tab === 'parts') {
            const g = {};
            all.forEach(r => {
                const k = r.part || '?';
                const a = g[k] = g[k] || { part: k, desc: r.part_desc, n: 0, qty: 0, value: 0, bill: new Set(), po: new Set(), plants: new Set() };
                a.n++; a.qty += r.qty || 0; a.value += r.net || 0;
                if (r.bill_rate) a.bill.add(r.bill_rate); if (r.po_rate) a.po.add(r.po_rate); if (r.plant) a.plants.add(r.plant);
            });
            list = Object.values(g).filter(x => hit(x.part, x.desc)).sort((a, b) => b.value - a.value);
            head = '<th>Part</th><th>Description</th><th>Plant</th><th class="num">Times</th><th class="num">Qty</th><th>We billed</th><th>TAFE PO rate</th><th class="num">Debited (net)</th>';
            body = list.slice(0, LIMIT).map(x => `<tr><td><b>${esc(x.part)}</b></td><td>${esc(x.desc || '')}</td><td>${esc([...x.plants].join(', '))}</td>
                <td class="num">${x.n}</td><td class="num">${qty(x.qty)}</td><td>${[...x.bill].map(v => inr(v)).join(', ')}</td>
                <td>${[...x.po].map(v => inr(v)).join(', ')}</td><td class="num"><b>${rupees(x.value)}</b></td></tr>`);
        } else if (kind === 'Rejection') {
            list = all.filter(x => hit(x.inv_raw, x.part, x.part_desc, x.doc_no, x.rej_doc));
            head = '<th>Document</th><th>Date</th><th>Our invoice</th><th>Plant</th><th>Part</th><th class="num">Qty</th><th class="num">Rate</th><th class="num">Value + GST</th><th>Reason</th><th>Rejection doc</th>';
            body = list.slice(0, LIMIT).map(x => `<tr><td>${esc(x.doc_no)}</td><td>${shortDate(x.doc_date)}</td><td><b>${esc(x.inv_raw || '')}</b></td>
                <td>${esc(x.plant || x.doc_plant || '')}</td><td>${esc(x.part || '')}<span class="sub">${esc(x.part_desc || '')}</span></td>
                <td class="num">${qty(x.qty)}</td><td class="num">${inr(x.bill_rate)}</td><td class="num"><b>${rupees(x.net)}</b></td>
                <td>${esc(x.reason || '')}</td><td>${esc(x.rej_doc || x.ref_no || '')}</td></tr>`);
        } else if (kind === 'Cash discount') {
            list = all.filter(x => hit(x.inv_raw, x.doc_no, x.grn_no));
            head = '<th>Document</th><th>Date</th><th>Our invoice</th><th>GRIN No</th><th>GRIN date</th><th class="num">Invoice amount</th><th class="num">Days</th><th class="num">Cash discount</th>';
            body = list.slice(0, LIMIT).map(x => `<tr><td>${esc(x.doc_no)}</td><td>${shortDate(x.doc_date)}</td><td><b>${esc(x.inv_raw || '')}</b></td>
                <td>${esc(x.grn_no || '')}</td><td>${shortDate(x.grn_date)}</td><td class="num">${rupees(x.basic)}</td><td class="num">${x.days ?? ''}</td>
                <td class="num"><b>${rupees(x.net)}</b></td></tr>`);
        } else {
            list = all.filter(x => hit(x.inv_raw, x.part, x.part_desc, x.doc_no, x.po_no, x.grn_no));
            head = '<th>Document</th><th>Date</th><th>Our invoice</th><th>Plant</th><th>Part</th><th class="num">GRIN qty</th><th class="num">We billed</th><th class="num">PO rate</th><th class="num">Diff / unit</th><th class="num">Debited (net)</th><th>PO</th>';
            body = list.slice(0, LIMIT).map(x => `<tr><td>${esc(x.doc_no)}</td><td>${shortDate(x.doc_date)}</td>
                <td><b>${esc(x.inv_raw || '')}</b><span class="sub">${shortDate(x.inv_date)}</span></td><td>${esc(x.plant || x.doc_plant || '')}</td>
                <td>${esc(x.part || '')}<span class="sub">${esc(x.part_desc || '')}</span></td><td class="num">${qty(x.qty)}</td>
                <td class="num">${inr(x.bill_rate)}</td><td class="num">${inr(x.po_rate)}</td><td class="num">${inr(x.diff_rate)}</td>
                <td class="num"><b>${rupees(x.net)}</b></td><td>${esc(x.po_no || '')}</td></tr>`);
        }
    }
    const cols = (head.match(/<th/g) || []).length;
    el.innerHTML = `<table class="data-table grin-table"><thead><tr>${head}</tr></thead><tbody>${body.length ? body.join('')
        : `<tr><td colspan="${cols}" class="muted-cell">Nothing here${q ? ' for this search' : ''}.</td></tr>`}</tbody></table>
        ${list.length > LIMIT ? `<div class="table-footer"><span>Showing ${LIMIT} of ${inr(list.length, 0)} – search, or Download Excel for all.</span></div>` : ''}`;
}
