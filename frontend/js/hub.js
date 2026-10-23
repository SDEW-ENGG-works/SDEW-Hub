// SDEW Hub page: Today, Find & trace, Drop files, Follow-ups, Masters.

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function inr(n, dec = 2) {
    if (n === null || n === undefined || n === '') return '';
    return (parseFloat(n) || 0).toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
const rupees = n => `₹${inr(n)}`;
const qty = n => (n === null || n === undefined || n === '') ? '' : (parseFloat(n) || 0).toLocaleString('en-IN', { maximumFractionDigits: 3 });
function dmy(iso) {
    if (!iso || String(iso).length < 10) return iso || '';
    iso = String(iso);
    return `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}`;
}
function when(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}
async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    if (res.status === 401) { location.replace('/login.html'); throw new Error('Please log in'); }
    const isJson = (res.headers.get('content-type') || '').includes('json');
    const data = isJson ? await res.json() : await res.blob();
    if (!res.ok) throw new Error((data && data.error) || `Server error ${res.status}`);
    return data;
}
const apiJson = (path, method, body) =>
    api(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
function showToast(message, type = 'info', ms = 3600) {
    const c = document.getElementById('toast-container');
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.innerHTML = `<span>${message}</span>`;
    c.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'all .3s'; setTimeout(() => t.remove(), 300); }, ms);
}
const MOD = { supp: 'Supp', chep: 'CHEP', dqms: 'DQMS', grin: 'GRIN', pos: 'POs', cross: 'Across', hub: 'Hub' };
const modTag = m => `<span class="mod-tag ${esc(m)}">${esc(MOD[m] || m)}</span>`;

// ------------------------------------------------------------------ routing
const VIEWS = ['today', 'find', 'drop', 'items', 'masters'];
function go(view, hash) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-links .nav-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(`${view}-view`).classList.add('active');
    document.getElementById(`nav-${view}-btn`).classList.add('active');
    try { history.replaceState(null, '', '#' + (hash || view)); } catch (e) { /* ignore */ }
    if (view === 'today') loadToday();
    else if (view === 'items') loadItems();
    else if (view === 'masters') loadMasters();
    else if (view === 'find') setTimeout(() => document.getElementById('find-input').focus(), 30);
}
function route() {
    const h = decodeURIComponent(location.hash.replace(/^#/, ''));
    const [k, ...rest] = h.split('=');
    const v = rest.join('=');
    if (k === 'find' && v) return hubFind(v);
    if (k === 'inv' && v) return openInvoice(v);
    if (k === 'part' && v) return openPart(v);
    if (k === 'po' && v) return openPo(v);
    if (k === 'dr' && v) return openDr(v);
    if (!k || k === 'home') return;   // the home screen (app icons) is drawn by hubbar.js
    const mine = (window.HUB_USER && window.HUB_USER.access) || VIEWS;
    const first = VIEWS.find(v => mine.includes(v)) || 'today';
    go(VIEWS.includes(k) && mine.includes(k) ? k : first);
}
document.addEventListener('DOMContentLoaded', () => {
    initDrop();
    route();
    window.addEventListener('hashchange', route);
    const mine = (window.HUB_USER && window.HUB_USER.access) || VIEWS;
    if (!location.hash.startsWith('#today') && location.hash && mine.includes('today')) loadToday(true);
});

// ------------------------------------------------------------------ Today
async function loadToday(quiet) {
    let d;
    try { d = await api('/api/hub/overview'); } catch (e) { showToast(`Could not load: ${e.message}`, 'danger'); return; }
    window.hubBadges && window.hubBadges(d);
    const attn = d.checks.filter(c => c.count).length;
    document.getElementById('checks-badge').textContent = attn;
    document.getElementById('items-badge').textContent = d.open_items.length;
    if (quiet) return;
    document.getElementById('today-desc').textContent =
        `${new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })} · ` +
        `${attn ? attn + ' check(s) need attention' : 'nothing needs attention'} · ${d.db_mode === 'cloud' ? 'cloud database' : 'data on this PC'}`;

    document.getElementById('chain').innerHTML = d.chain.map(s => `
        <a class="chain-step" href="${esc(s.href)}">
            <div class="k">${esc(s.step)}</div>
            <div class="v">${(s.count || 0).toLocaleString('en-IN')}</div>
            <div class="s">${esc(s.sub)}</div>
        </a>`).join('');

    const m = d.modules;
    const repAge = m.dqms.report && (m.dqms.report.report_time || m.dqms.report.uploaded_at);
    document.getElementById('mod-cards').innerHTML = `
        <a class="card mod-card" href="/supp/"><h3>Supplementary Bill</h3><span class="hint no-margin">TAFE price revision bills, plant-wise</span>
            <dl><dt>POs loaded</dt><dd>${m.supp.pos}</dd>
                <dt>Sales Register up to</dt><dd>${dmy(m.supp.sales_last) || '—'}</dd>
                <dt>GRIN up to</dt><dd>${dmy(m.supp.grin_last) || '—'}</dd>
                <dt>Bill calculated</dt><dd>${when(m.supp.bill_at) || '—'}</dd></dl></a>
        <a class="card mod-card" href="/chep/"><h3>CHEP Transfer</h3><span class="hint no-margin">Packing list → CHEP BulkTransfer → LEAP</span>
            <dl><dt>Packing lists</dt><dd>${m.chep.packing_lists}</dd>
                <dt>History files</dt><dd>${m.chep.files}</dd>
                <dt>Last file</dt><dd>${m.chep.last ? esc(dmy(m.chep.last.doc_date)) : '—'}</dd>
                <dt>Parts with a CHEP size</dt><dd>${m.chep.parts}</dd></dl></a>
        <a class="card mod-card" href="/dqms/"><h3>DQMS Upload</h3><span class="hint no-margin">Invoice PDFs → TAFE DQMS template.csv</span>
            <dl><dt>Invoices waiting</dt><dd>${m.dqms.waiting}</dd>
                <dt>Files made</dt><dd>${m.dqms.files}</dd>
                <dt>Last file</dt><dd>${m.dqms.last ? esc(m.dqms.last.file_name) : '—'}</dd>
                <dt>DQMS report</dt><dd>${repAge ? esc(String(repAge).slice(0, 16).replace('T', ' ')) : '—'}</dd></dl></a>` +
        (m.grin && m.grin.ok ? `
        <a class="card mod-card" href="/grin/"><h3>GRIN &amp; Payments</h3><span class="hint no-margin">Tally invoice → TAFE GRIN → TAFE payment</span>
            <dl><dt>Not GRINed (remind)</dt><dd>${m.grin.not_grined} · ₹${inr(m.grin.not_grined_value, 0)}</dd>
                <dt>Payment overdue</dt><dd>${m.grin.overdue} · ₹${inr(m.grin.overdue_value, 0)}</dd>
                <dt>Awaiting payment</dt><dd>${m.grin.awaiting} · ₹${inr(m.grin.awaiting_value, 0)}</dd>
                <dt>Payments up to</dt><dd>${dmy(m.grin.pay_until) || '—'}</dd></dl></a>` : '');

    const mb = document.getElementById('money-body');
    if (!d.money) {
        mb.innerHTML = `<p class="hint">No bill calculated yet — open <a href="/supp/">Supplementary Bill</a> and press Calculate bill.</p>`;
        document.getElementById('money-sub').textContent = '';
    } else {
        const mo = d.money;
        document.getElementById('money-sub').textContent = `calculated ${when(mo.at)}`;
        const max = Math.max(...mo.plants.map(p => p.value), 1);
        const pend = Object.entries(mo.pending).filter(([c, x]) => c !== 'Excluded');
        mb.innerHTML = `
            <div class="money-row">
                <div><div class="money-lbl">Basic value</div><div class="money-big">${rupees(mo.bill_value)}</div></div>
                <div><div class="money-lbl">GST</div><div class="money-mid">${rupees(mo.gst)}</div></div>
                <div><div class="money-lbl">With GST</div><div class="money-mid">${rupees(mo.with_gst)}</div></div>
                <div><div class="money-lbl">Lines</div><div class="money-mid">${(mo.lines || 0).toLocaleString('en-IN')}</div></div>
            </div>
            <div class="bar-list">${mo.plants.map(p => `
                <div class="bar-item"><span><b>${esc(p.plant)}</b></span>
                    <div class="bar-track"><div class="bar-fill" style="width:${(p.value / max * 100).toFixed(1)}%"></div></div>
                    <span class="amt">${rupees(p.value)}</span></div>`).join('')}
            </div>
            ${pend.length ? `<p class="hint" style="margin-top:.8rem">Not in the bill yet: ${pend.map(([c, x]) =>
                `<b>${esc(c)}</b> ${x.lines} line(s)${x.value ? ' · ' + rupees(x.value) : ''}`).join(' &nbsp;·&nbsp; ')}</p>` : ''}`;
    }

    const sorted = [...d.checks].sort((a, b) => (b.count > 0) - (a.count > 0));
    document.getElementById('checks').innerHTML = sorted.map((c, i) => `
        <div class="check-item ${c.count ? '' : 'ok'}" id="chk-${i}">
            <div class="check-head" onclick="document.getElementById('chk-${i}').classList.toggle('open')">
                ${modTag(c.module)}<span class="t">${esc(c.title)}</span><span class="c">${c.count || '✓'}</span>
            </div>
            <div class="check-body">
                ${c.detail ? `<div class="d">${esc(c.detail)}</div>` : ''}
                ${c.items.length ? `<div class="table-wrapper"><table class="data-table compact"><tbody>${c.items.map(x => `
                    <tr><td class="mono">${refLink(x.ref)}</td><td>${esc(x.plant || '')}</td><td>${esc(dmy(x.date))}</td><td>${esc(x.detail || '')}</td></tr>`).join('')}
                    </tbody></table></div>` : ''}
                ${c.count > c.items.length ? `<div class="d">… and ${c.count - c.items.length} more</div>` : ''}
                <a class="btn btn-outline btn-sm" style="margin-top:.4rem" href="${esc(c.href)}">Open to fix →</a>
            </div>
        </div>`).join('');

    document.getElementById('today-items').innerHTML = d.open_items.slice(0, 8).map(it => `
        <li>${modTag(it.module)}<span class="x" title="${esc(it.detail)}">${esc(it.title)}</span></li>`).join('') ||
        '<li><span class="x hint">Nothing open</span></li>';
    document.getElementById('today-activity').innerHTML = d.activity.map(a => `
        <li><span class="w">${esc(when(a.at))}</span>${modTag(a.module)}<span class="x">${esc(a.action)}${a.detail ? ' — ' + esc(a.detail) : ''}</span></li>`).join('') ||
        '<li><span class="x hint">No activity yet</span></li>';
}

// a reference in a check / table: invoice numbers, parts, POs open their own view
function refLink(ref) {
    const r = String(ref ?? '');
    if (/^\d{2,6}\/\d\d-\d\d$/.test(r)) return `<a href="#inv=${encodeURIComponent(r)}" onclick="openInvoice('${esc(r)}');return false;">${esc(r)}</a>`;
    if (/^\d{10}$/.test(r)) return `<a href="#po=${r}" onclick="openPo('${r}');return false;">${esc(r)}</a>`;
    if (/^[0-9A-Z]{8,12}$/.test(r) && /[A-Z]/.test(r)) return `<a href="#part=${r}" onclick="openPart('${r}');return false;">${esc(r)}</a>`;
    return esc(r);
}

// ------------------------------------------------------------------ Find
async function hubFind(q) {
    q = String(q || '').trim();
    if (!q) return;
    go('find', 'find=' + encodeURIComponent(q));
    document.getElementById('find-input').value = q;
    const box = document.getElementById('find-results');
    document.getElementById('find-detail').innerHTML = '';
    box.style.display = '';
    box.innerHTML = '<p class="hint">Searching…</p>';
    let d;
    try { d = await api('/api/hub/search?q=' + encodeURIComponent(q)); } catch (e) { box.innerHTML = `<p class="hint">${esc(e.message)}</p>`; return; }
    const groups = d.groups;
    const total = groups.reduce((n, g) => n + g.items.length, 0);
    if (!total) { box.innerHTML = `<p class="hint">Nothing found for “${esc(q)}”.</p>`; return; }
    // one exact invoice / part / PO: open it straight away
    const exact = groups.flatMap(g => g.items.map(x => [g.kind, x])).filter(([k, x]) => String(x.ref).toUpperCase() === q.toUpperCase());
    if (total === 1 || exact.length === 1) {
        const [k, x] = exact[0] || [groups[0].kind, groups[0].items[0]];
        box.style.display = 'none';
        return openKind(k, x.ref);
    }
    box.innerHTML = groups.map(g => `
        <div class="result-group"><h4>${esc(g.title)} (${g.items.length})</h4>
            ${g.items.map(x => `<div class="result-item" onclick="openKind('${g.kind}', '${esc(x.ref)}')">
                <span class="r">${esc(x.ref)}</span><span class="d">${esc([dmy(x.date), x.detail, x.n ? x.n + (g.kind === 'part' ? ' PO(s)' : g.kind === 'po' ? ' parts' : ' line(s)') : ''].filter(Boolean).join(' · '))}</span>
            </div>`).join('')}
        </div>`).join('');
}
function openKind(kind, ref) {
    if (kind === 'invoice') return openInvoice(ref);
    if (kind === 'part') return openPart(ref);
    if (kind === 'po') return openPo(ref);
    if (kind === 'dr') return openDr(ref);
    if (kind === 'grin') return hubFind(ref);
}
function table(cols, rows) {
    if (!rows || !rows.length) return '';
    return `<div class="table-wrapper"><table class="data-table compact"><thead><tr>${cols.map(c => `<th class="${c[2] || ''}">${esc(c[1])}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(r => `<tr>${cols.map(c => `<td class="${c[2] || ''}">${typeof c[0] === 'function' ? c[0](r) : esc(r[c[0]] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function detailShell(title, sub, body) {
    document.getElementById('find-results').style.display = 'none';
    document.getElementById('find-detail').innerHTML = `
        <div class="card"><div class="card-header-flex"><div class="card-title">${title}</div><span class="hint no-margin">${sub || ''}</span></div>${body}</div>`;
}

async function openInvoice(no) {
    go('find', 'inv=' + encodeURIComponent(no));
    document.getElementById('find-input').value = no;
    let d;
    try { d = await api('/api/hub/invoice?no=' + encodeURIComponent(no)); } catch (e) { return showToast(e.message, 'danger'); }
    const S = Object.fromEntries(d.steps.map(s => [s.key, s]));
    const body = d.steps.map(s => {
        let inner = '';
        if (s.key === 'tally') inner = table([['part', 'Part', 'mono'], ['descr', 'Description'], [r => esc(dmy(r.inv_date)), 'Date'], ['party', 'Party'],
            [r => refLink(r.order_no), 'Order No'], [r => qty(r.qty), 'Qty', 'num'], [r => inr(r.rate), 'Rate', 'num'], [r => inr(r.qty * r.rate), 'Value', 'num']], s.rows);
        else if (s.key === 'dr') inner = (s.drs.length ? `<div class="trail-note">DR ${s.drs.map(x => `<a href="#dr=${x}" onclick="openDr('${x}');return false;">${esc(x)}</a>`).join(', ')}</div>` : '') +
            table([['dr_no', 'DR'], ['part', 'Part', 'mono'], ['order_no', 'Order'], ['bin', 'Bin'], ['req', 'Units', 'num'], [r => qty(r.size), 'Unit size', 'num'], [r => qty(r.qty), 'Qty', 'num']], s.rows);
        else if (s.key === 'packing') inner = table([['file', 'Packing list'], ['sheet', 'Sheet'], ['dr', 'DR'], ['part', 'Part', 'mono'], [r => qty(r.qty), 'Qty', 'num'],
            ['chep', 'CHEP', 'num'], ['carton', 'Carton', 'num'], [r => esc(Object.entries(r.sizes || {}).map(([k, v]) => `size ${k} × ${v}`).join(', ')), 'Sizes']], s.rows);
        else if (s.key === 'chep') inner = table([['file', 'History file'], [r => esc(dmy(r.doc_date)), 'Doc Date'], ['plant', 'Plant'], ['customer', 'To customer'],
            ['sku', 'SKU', 'mono'], ['qty', 'Qty', 'num'], [r => esc(r.leap || 'not via hub'), 'LEAP']], s.rows) +
            (s.rows.length ? `<a class="btn btn-outline btn-sm" href="/chep/#history">Open CHEP History</a>` : '');
        else if (s.key === 'dqms') {
            const iv = s.invoice;
            inner = (iv ? `<div class="kv"><div><span>Invoice value</span><b>${rupees(iv.total)}</b></div><div><span>Order No</span><b>${refLink(iv.order_no)}</b></div>
                <div><span>Packages</span><b>${iv.packages ?? ''}</b></div><div><span>E-way bill</span><b>${esc((iv.edits || {}).eway || iv.eway || '—')}</b></div></div>` : '') +
                table([['file_name', 'DQMS file'], [r => esc(when(r.created_at)), 'Made']], s.rows) +
                table([['record', 'Row'], ['part', 'Part'], ['batch_no', 'Batch'], ['status', 'Portal status'], ['message', 'Message']], s.status) +
                `<a class="btn btn-outline btn-sm" href="/dqms/">Open DQMS Upload</a>`;
        } else if (s.key === 'grin') inner = table([['grin_no', 'GRIN'], [r => esc(dmy(r.grin_date)), 'Date'], ['plant', 'Plant'], [r => refLink(r.po_no), 'PO'],
            [r => refLink(r.part_no), 'Part', 'mono'], [r => qty(r.grin_qty), 'GRIN qty', 'num'], [r => qty(r.accepted_qty), 'Accepted', 'num'],
            [r => qty(r.rejected_qty), 'Rejected', 'num'], [r => inr(r.part_rate), 'Rate', 'num']], s.rows);
        else if (s.key === 'bill') inner = table([['plant', 'Plant'], ['cat', 'Category'], [r => refLink(r.part), 'Part', 'mono'], [r => qty(r.qty), 'Qty', 'num'],
            [r => inr(r.rate), 'Billed', 'num'], [r => inr(r.old_rate), 'Existing', 'num'], [r => inr(r.new_rate), 'Reversed', 'num'],
            [r => inr(r.value), 'Value', 'num'], ['reason', 'Reason'], ['notes', 'Notes']], s.rows);
        return `<div class="trail-step ${s.ok ? 'ok' : 'no'}"><span class="trail-dot"></span>
            <div class="trail-title">${esc(s.title)}</div>${s.note ? `<div class="trail-note">${esc(s.note)}</div>` : ''}${inner}</div>`;
    }).join('');
    const party = (S.tally.rows[0] || {}).party || '';
    detailShell(`Invoice ${esc(d.invoice)}`, esc(party), d.found ? `<div class="trail">${body}</div>` :
        `<p class="hint">Invoice ${esc(no)} is not in any module's data. Check the number (format 13295/26-27).</p>`);
}

async function openPart(part) {
    go('find', 'part=' + encodeURIComponent(part));
    document.getElementById('find-input').value = part;
    let d;
    try { d = await api('/api/hub/part?part=' + encodeURIComponent(part)); } catch (e) { return showToast(e.message, 'danger'); }
    const st = d.sales_total || {}, gt = d.grin_total || {};
    const body = `
        <div class="kv">
            <div><span>CHEP size</span><b>${d.chep_size ? 'Size ' + esc(d.chep_size.type) : '—'}</b></div>
            <div><span>DQMS batch balance</span><b>${qty(d.balance)}</b></div>
            <div><span>Invoiced (Sales Register)</span><b>${qty(st.q || 0)}</b></div>
            <div><span>GRIN qty / rejected</span><b>${qty(gt.q || 0)} / ${qty(gt.rej || 0)}</b></div>
        </div>
        <div class="trail-title">On these POs</div>
        ${table([[r => refLink(r.po_no), 'PO'], ['plant', 'Plant'], ['item', 'Line item', 'num'], ['descr', 'Description'],
            [r => inr(r.old), `Rate on ${dmy(d.old_date)}`, 'num'], [r => inr(r.new), `Rate on ${dmy(d.new_date)}`, 'num'], [r => inr(r.rate), 'PO rate', 'num']], d.po_items) || '<p class="hint">In no uploaded PO.</p>'}
        ${d.bill.length ? `<div class="trail-title" style="margin-top:1rem">Supplementary bill (last run)</div>` + table([['plant', 'Plant'], ['cat', 'Category'], ['n', 'Lines', 'num'],
            [r => qty(r.q), 'Qty', 'num'], [r => inr(r.v), 'Value', 'num']], d.bill) : ''}
        ${d.batches.length ? `<div class="trail-title" style="margin-top:1rem">DQMS batches (oldest first)</div>` + table([['batch_no', 'Batch'], [r => qty(r.total), 'Total', 'num'],
            [r => qty(r.consumed), 'Consumed', 'num'], [r => qty(r.balance), 'Balance', 'num'], ['created', 'Created']], d.batches) : ''}
        ${d.sales.length ? `<div class="trail-title" style="margin-top:1rem">Latest invoices</div>` + table([[r => refLink(r.voucher), 'Invoice'], [r => esc(dmy(r.inv_date)), 'Date'],
            ['party', 'Party'], [r => refLink(r.order_no), 'Order'], [r => qty(r.qty), 'Qty', 'num'], [r => inr(r.rate), 'Rate', 'num']], d.sales) : ''}`;
    detailShell(`Part ${esc(d.part)}`, esc(d.name || ''), body);
}

async function openPo(po) {
    go('find', 'po=' + encodeURIComponent(po));
    document.getElementById('find-input').value = po;
    let d;
    try { d = await api('/api/hub/po?po=' + encodeURIComponent(po)); } catch (e) { return showToast(e.message, 'danger'); }
    const h = d.header, typed = Object.fromEntries(d.typed.map(t => [t.part, t.item]));
    const revised = d.items.filter(i => i.old != null && i.new != null && Math.round((i.new - i.old) * 100) !== 0).length;
    const body = `
        <div class="kv">
            <div><span>Plant</span><b>${esc(h.plant || '—')}</b></div>
            <div><span>Parts / revised</span><b>${d.items.length} / ${revised}</b></div>
            <div><span>Invoices on it</span><b>${(d.sales || {}).inv || 0}</b></div>
            <div><span>GRIN lines</span><b>${(d.grin || {}).n || 0}</b></div>
        </div>
        ${d.bill.length ? `<p class="hint">Last bill: ${d.bill.map(b => `<b>${esc(b.cat)}</b> ${b.n} line(s)${b.v ? ' · ' + rupees(b.v) : ''}`).join(' &nbsp;·&nbsp; ')}</p>` : ''}
        ${table([['item', 'Line', 'num'], [r => refLink(r.part), 'Part', 'mono'], ['descr', 'Description'], ['uom', 'UOM'],
            [r => inr(r.old), `Existing (${dmy(d.old_date)})`, 'num'], [r => inr(r.new), `Reversed (${dmy(d.new_date)})`, 'num'],
            [r => typed[r.part] ? `<b>${typed[r.part]}</b> typed` : '', 'DQMS line typed']], d.items)}`;
    detailShell(`PO ${esc(po)}`, esc([h.po_date, h.valid_till && 'valid till ' + h.valid_till, h.source].filter(Boolean).join(' · ')), body);
}

async function openDr(dr) {
    go('find', 'dr=' + encodeURIComponent(dr));
    document.getElementById('find-input').value = dr;
    let d;
    try { d = await api('/api/hub/dr?dr=' + encodeURIComponent(dr)); } catch (e) { return showToast(e.message, 'danger'); }
    const body = (table([['part', 'Part', 'mono'], ['order_no', 'Order'], ['descr', 'Description'], ['bin', 'Bin'], ['req', 'Units', 'num'],
        [r => qty(r.size), 'Unit size', 'num'], [r => qty(r.qty), 'Qty', 'num'], ['file_name', 'DR PDF']], d.lines) || '<p class="hint">DR PDF not uploaded.</p>') +
        (d.packing.length ? `<div class="trail-title" style="margin-top:1rem">On the packing list</div>` + table([['file', 'Packing list'], ['sheet', 'Sheet'],
            [r => refLink(r.invoice), 'Invoice'], [r => esc(dmy(r.inv_date)), 'Date'], [r => refLink(r.part), 'Part', 'mono'], [r => qty(r.qty), 'Qty', 'num'], ['chep', 'CHEP', 'num']], d.packing) : '') +
        (d.invoices.length ? `<div class="trail-title" style="margin-top:1rem">Invoices (DQMS)</div>` + table([[r => refLink(r.inv_no), 'Invoice'], [r => esc(dmy(r.inv_date)), 'Date'],
            [r => inr(r.total), 'Value', 'num'], [r => r.run_id ? 'in a DQMS file' : 'waiting', 'DQMS']], d.invoices) : '');
    detailShell(`Delivery Request ${esc(dr)}`, '', body);
}

// ------------------------------------------------------------------ Drop
function initDrop() {
    const dz = document.getElementById('hub-dropzone');
    ['dragenter', 'dragover'].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.remove('over'); }));
    dz.addEventListener('drop', ev => dropFiles(ev.dataTransfer.files));
    // drop anywhere on the hub page = drop in the box
    document.addEventListener('dragover', ev => ev.preventDefault());
    document.addEventListener('drop', ev => {
        if (dz.contains(ev.target)) return;
        ev.preventDefault();
        if (ev.dataTransfer.files.length) { go('drop'); dropFiles(ev.dataTransfer.files); }
    });
}
async function dropFiles(files) {
    const out = document.getElementById('drop-results');
    for (const f of Array.from(files || [])) {
        const row = document.createElement('div');
        row.className = 'upload-row';
        row.innerHTML = `<span class="status-badge muted">reading</span><b>${esc(f.name)}</b><span class="hint no-margin">…</span>`;
        out.prepend(row);
        try {
            const r = await api('/api/hub/upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f });
            row.innerHTML = `${modTag(r.module)}<b>${esc(f.name)}</b><span class="x">${esc(r.message)}</span>
                <a class="btn btn-outline btn-sm" style="margin-left:auto" href="${esc(r.page)}">Open ${esc(r.module_name)} →</a>`;
        } catch (e) {
            row.innerHTML = `<span class="status-badge warn">not read</span><b>${esc(f.name)}</b><span class="x">${esc(e.message)}</span>`;
        }
    }
    document.getElementById('hub-file-input').value = '';
    loadToday(true);
}

// ------------------------------------------------------------------ Follow-ups
async function loadItems() {
    const [items, act] = await Promise.all([api('/api/hub/open-items'), api('/api/hub/activity')]);
    document.getElementById('items-badge').textContent = items.filter(i => i.status === 'open').length;
    document.getElementById('items-tbody').innerHTML = items.map(it => `
        <tr style="${it.status === 'done' ? 'opacity:.55' : ''}">
            <td>${modTag(it.module)}</td>
            <td><b>${esc(it.title)}</b>${it.detail ? `<div class="hint no-margin">${esc(it.detail)}</div>` : ''}</td>
            <td>${esc(dmy(it.created_at))}</td>
            <td>${it.status === 'open' ? `<button class="oi-done" onclick="setItem(${it.id}, 'done')">✓ Done</button>`
            : `<span class="hint no-margin">done ${esc(dmy(it.done_at))}</span> <button class="oi-done" onclick="setItem(${it.id}, 'open')">reopen</button>`}</td>
        </tr>`).join('');
    document.getElementById('activity-list').innerHTML = act.map(a => `
        <li><span class="w">${esc(when(a.at))}</span>${modTag(a.module)}<span class="x">${esc(a.action)}${a.detail ? ' — ' + esc(a.detail) : ''}</span></li>`).join('') ||
        '<li><span class="x hint">No activity yet</span></li>';
}
async function setItem(id, status) {
    try { await apiJson(`/api/hub/open-items/${id}`, 'PUT', { status }); loadItems(); } catch (e) { showToast(e.message, 'danger'); }
}
async function addItem() {
    const t = document.getElementById('oi-title');
    try {
        await apiJson('/api/hub/open-items', 'POST', { module: document.getElementById('oi-module').value, title: t.value });
        t.value = '';
        loadItems();
    } catch (e) { showToast(e.message, 'danger'); }
}

// ------------------------------------------------------------------ Masters
async function loadMasters() {
    let d;
    try { d = await api('/api/hub/masters'); } catch (e) { return showToast(e.message, 'danger'); }
    const yes = b => b ? '<span class="env-ok">set</span>' : '<span class="env-no">not set</span>';
    document.getElementById('masters-body').innerHTML = `
        <div class="kv">
            <div><span>POs / part lines</span><b>${d.counts.pos} / ${d.counts.po_items}</b></div>
            <div><span>Parts with CHEP size</span><b>${d.counts.parts_sized}</b></div>
            <div><span>DQMS line items typed</span><b>${d.counts.typed_lines}</b></div>
            <div><span>Price dates</span><b>${dmy(d.price_dates.old)} → ${dmy(d.price_dates.new)}</b></div>
        </div>
        <div class="card"><div class="card-header-flex"><div class="card-title">Plants</div>
            <span class="hint no-margin">edit in <a href="/supp/#settings">Supplementary Bill › Settings</a> and <a href="/chep/#settings">CHEP › Settings</a></span></div>
            ${table([['code', 'Plant'], ['party', 'Tally party'], ['grin_plant', 'TAFE plant code'], [r => refLink(r.main_po), 'Main PO'], ['bill_to', 'PO Bill-to word'],
                ['chep_customer', 'CHEP customer'], ['pos', 'POs loaded', 'num']], d.plants)}
        </div>
        <div class="hub-grid">
            <div class="card"><div class="card-header-flex"><div class="card-title">CHEP sizes (BP ${esc(d.chep_bp)})</div>
                <a class="hint no-margin" href="/chep/#settings">edit</a></div>
                ${table([['code', 'Size'], ['names', 'Packing list headings'], ['pallet', 'Pallet SKU', 'mono'], ['lid', 'Lid SKU', 'mono']], d.crate_sizes)}</div>
            <div class="card"><div class="card-header-flex"><div class="card-title">DQMS</div><a class="hint no-margin" href="/dqms/#settings">edit</a></div>
                <p class="hint">Transporter <b>${esc(d.transporter)}</b></p>
                <p class="hint">Reasons for gap: ${d.reasons.map(esc).join(' · ')}</p></div>
        </div>
        <div class="hub-grid">
            <div class="card"><div class="card-header-flex"><div class="card-title">Supplementary bill rules</div><a class="hint no-margin" href="/supp/#settings">edit</a></div>
                <p class="hint">Diff basis: <b>${d.diff_basis === 'po' ? 'PO (Reversed − Existing)' : 'billed rate'}</b> · Rate pending POs: ${d.rate_pending_pos.map(refLink).join(', ') || '—'}</p>
                <div class="trail-title" style="margin-top:.6rem">Fixed rates</div>
                ${table([[r => refLink(r.part), 'Part'], [r => inr(r.existing), 'Existing', 'num'], [r => inr(r.revised), 'Reversed', 'num'], ['note', 'Note']], d.fixed_rates) || '<p class="hint">none</p>'}
                <div class="trail-title" style="margin-top:.6rem">Part number corrections</div>
                ${table([['plant', 'Plant'], ['from', 'Tally part'], [r => refLink(r.to), 'PO part'], ['note', 'Note']], d.part_corrections) || '<p class="hint">none</p>'}</div>
            <div class="card"><div class="card-title">Logins and connections (.env)</div>
                <table class="data-table compact"><tbody>
                    <tr><td>TAFE Channel (Fetch GRIN, DQMS report)</td><td>${yes(d.env.tafe_login)}</td></tr>
                    <tr><td>LEAP (CHEP upload)</td><td>${yes(d.env.leap_login)}</td></tr>
                    <tr><td>Playwright on this PC</td><td>${d.env.playwright ? '<span class="env-ok">installed</span>' : '<span class="env-no">not installed</span>'}</td></tr>
                    <tr><td>Login password (APP_PASSWORD)</td><td>${yes(d.env.password)}</td></tr>
                    <tr><td>Database</td><td><b>${d.env.cloud ? 'Turso cloud' : 'this PC (data\\sdew_hub.db)'}</b></td></tr>
                </tbody></table></div>
        </div>`;
}
window.hubFind = hubFind;
window.addEventListener('hashchange', route);
