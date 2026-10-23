// Status page: one row per TAFE invoice - GRINed? paid? - with filters, detail and Excel.

const G = { status: '', plant: '', offset: 0, data: null };
const ST_CLASS = {
    'Not GRINed': 'st-ng', 'GRIN short / rejected': 'st-short', 'Payment overdue': 'st-od',
    'Awaiting payment': 'st-aw', 'GRIN pending': 'st-wait', 'Debit note only': 'st-debit', 'Paid': 'st-paid',
};
const ST_HINT = {
    'Not GRINed': 'remind the buyer', 'GRIN short / rejected': 'check with stores', 'Payment overdue': 'follow up payment',
    'Awaiting payment': 'GRINed, within credit days', 'GRIN pending': 'still inside wait days', 'Debit note only': 'debit note, no payment',
    'Paid': 'payment voucher found',
};
const stBadge = s => `<span class="st ${ST_CLASS[s] || ''}">${esc(s)}</span>`;

function statusQuery(extra = {}) {
    const p = new URLSearchParams();
    const asOf = document.getElementById('as-of').value;
    if (asOf) p.set('as_of', asOf);
    if (G.status) p.set('status', G.status);
    if (G.plant) p.set('plant', G.plant);
    const q = document.getElementById('status-search').value.trim();
    if (q) p.set('q', q);
    Object.entries(extra).forEach(([k, v]) => p.set(k, v));
    return p.toString();
}

async function loadStatus(offset = G.offset) {
    G.offset = offset;
    const tb = document.getElementById('status-tbody');
    try {
        const d = await api(`/api/grin/status?${statusQuery({ offset, limit: PAGE })}`);
        G.data = d;
        renderFresh(d);
        renderPayCheck(d.pay_check);
        renderCards(d);
        renderPlantPills(d);
        tb.innerHTML = d.rows.length ? d.rows.map(rowHtml).join('')
            : `<tr><td colspan="12" class="muted-cell">No invoices${G.status ? ` with status “${esc(G.status)}”` : ''}</td></tr>`;
        tb.querySelectorAll('tr[data-k]').forEach(tr => tr.onclick = () => openInvoice(tr.dataset.k));
        document.getElementById('status-total').innerHTML =
            `<b>${inr(d.total, 0)}</b> invoice(s) · value <b>${rupees(d.value)}</b>`;
        pager(document.getElementById('status-pager'), d.total, offset, loadStatus);
        document.getElementById('ng-badge').textContent = inr(d.counts['Not GRINed'].n, 0);
    } catch (e) {
        tb.innerHTML = `<tr><td colspan="12" class="muted-cell">${esc(e.message)}</td></tr>`;
        showToast(e.message, 'danger');
    }
}

function daysOld(iso) {
    if (!iso) return null;
    return Math.floor((Date.now() - new Date(`${iso.slice(0, 10)}T00:00:00`)) / 86400000);
}

function renderFresh(d) {
    const g = d.dates.grin_until, p = d.dates.pay_until;
    const gOld = daysOld(g), pOld = daysOld(p);
    document.getElementById('fresh').innerHTML = `
        <span>Status on <b>${dmy(d.as_of)}</b></span>
        <span>GRIN data up to <b class="${gOld > 2 ? 'old' : ''}">${g ? dmy(g) : 'none'}</b></span>
        <span>Payments up to <b class="${pOld > 7 ? 'old' : ''}">${p ? dmy(p) : 'none'}</b></span>
        <span>Remind after <b>${d.settings.wait_days}</b> days · TAFE pays within <b>${d.settings.credit_days}</b> days of GRIN</span>
        ${d.untracked.length ? `<span>Not checked: ${esc(d.untracked.join(', '))}</span>` : ''}`;
    const b = [];
    if (!g) b.push(`<div class="banner danger">No GRIN data yet — <a href="#" onclick="switchView('sources');return false">fetch GRIN from TAFE Channel</a>.</div>`);
    else if (gOld > 2) b.push(`<div class="banner">GRIN data is ${gOld} days old. Invoices after ${dmy(g)} show as <b>GRIN pending</b> until you <a href="#" onclick="switchView('sources');return false">fetch GRIN</a> again.</div>`);
    if (!p) b.push(`<div class="banner">No TAFE payment data yet — drop the PaymentDetailsExport (and the invoice register) on <a href="#" onclick="switchView('sources');return false">Get data</a>.</div>`);
    else if (pOld > 7) b.push(`<div class="banner">Payment data is ${pOld} days old — invoices paid since ${dmy(p)} still show as awaiting. Drop a new PaymentDetailsExport on <a href="#" onclick="switchView('sources');return false">Get data</a>.</div>`);
    document.getElementById('status-banners').innerHTML = b.join('');
}

function renderCards(d) {
    document.getElementById('status-cards').innerHTML = d.order.map(s => {
        const c = d.counts[s];
        return `<button class="st-card ${ST_CLASS[s]} ${G.status === s ? 'active' : ''}" data-s="${esc(s)}">
            <div class="k">${esc(s)}</div><div class="v">${inr(c.n, 0)}</div>
            <div class="s">₹${inr(c.value, 0)}</div><div class="h">${esc(ST_HINT[s] || '')}</div></button>`;
    }).join('');
    document.querySelectorAll('.st-card').forEach(b => b.onclick = () => {
        G.status = G.status === b.dataset.s ? '' : b.dataset.s;
        loadStatus(0);
    });
}

function renderPlantPills(d) {
    const total = d.plants.reduce((a, p) => a + d.order.reduce((x, s) => x + (G.status ? (s === G.status ? (p[s] || 0) : 0) : (p[s] || 0)), 0), 0);
    const pills = [`<button class="cat-pill ${!G.plant ? 'active' : ''}" data-p="">All plants<span class="pill-count">${inr(total, 0)}</span></button>`]
        .concat(d.plants.map(p => {
            const n = G.status ? (p[G.status] || 0) : d.order.reduce((x, s) => x + (p[s] || 0), 0);
            if (!n && G.plant !== p.plant) return '';
            return `<button class="cat-pill ${G.plant === p.plant ? 'active' : ''}" data-p="${esc(p.plant)}">${esc(p.plant)}<span class="pill-count">${inr(n, 0)}</span></button>`;
        }));
    const el = document.getElementById('plant-pills');
    el.innerHTML = pills.join('');
    el.querySelectorAll('.cat-pill').forEach(b => b.onclick = () => { G.plant = b.dataset.p; loadStatus(0); });
}

function partsText(r) {
    const ps = r.parts.filter(p => p.part).map(p => `${p.part} × ${qty(p.qty)}`);
    return ps.slice(0, 3).join(', ') + (ps.length > 3 ? ` +${ps.length - 3}` : '');
}

function rowHtml(r) {
    const grin = r.grin_nos
        ? `${esc(r.grin_nos.split(', ')[0])}${r.grin_nos.includes(',') ? ' +' : ''}<span class="sub">${dmy(r.grin_date)}${r.grin_qty !== null ? ` · qty ${qty(r.grin_qty)}` : ''}</span>`
        : '<span class="sub">—</span>';
    const pay = r.pv
        ? `${esc(r.pv)}<span class="sub">${dmy(r.pv_date)}${r.credit ? ` · ₹${inr(r.credit)}` : ''}</span>`
        : (r.due_date ? `<span class="sub">due ${dmy(r.due_date)}${r.overdue_days ? ` · <b>${r.overdue_days} d late</b>` : ''}</span>` : '<span class="sub">—</span>');
    const who = r.status === 'Not GRINed' || r.reminders
        ? `${esc(r.buyer || '—')}${r.reminders ? `<span class="tag rem">${r.reminders}× mailed</span>` : ''}${r.last_reminder ? `<span class="sub">last ${dmy(r.last_reminder.slice(0, 10))}</span>` : ''}`
        : '';
    const checks = [...r.notes, ...(r.note ? [`Note: ${r.note}`] : [])].map(esc).join('<br>');
    return `<tr class="clickable ${r.hold ? 'held' : ''}" data-k="${esc(r.inv_no)}">
        <td>${stBadge(r.status)}${r.hold ? '<span class="tag hold">HOLD</span>' : ''}</td>
        <td class="strong">${esc(r.inv_no)}</td><td>${dmy(r.inv_date)}</td><td>${esc(r.plant)}</td><td>${esc(r.order_no || '')}</td>
        <td class="parts">${esc(partsText(r))}</td>
        <td class="num">${r.amount ? inr(r.amount) : ''}</td><td class="num">${r.age ?? ''}</td>
        <td>${grin}</td><td>${pay}</td><td>${who}</td><td class="checks">${checks}</td></tr>`;
}

function downloadStatus() {
    window.location.href = `/api/grin/export?${statusQuery()}`;
}

// ---------- invoice detail ----------
async function openInvoice(no) {
    const asOf = document.getElementById('as-of').value;
    try {
        const d = await api(`/api/grin/invoice?no=${encodeURIComponent(no)}${asOf ? `&as_of=${asOf}` : ''}`);
        const r = d.row || {};
        document.getElementById('inv-title').innerHTML = `Invoice ${esc(no)} ${r.status ? stBadge(r.status) : ''}`;
        const tallyOk = !!(r.inv_no);
        const grinOk = d.grin.length > 0, payOk = !!r.pv;
        const tbl = (cols, rows) => rows.length ? `<div class="table-wrapper"><table class="data-table compact"><thead><tr>${cols.map(c => `<th class="${c[2] || ''}">${c[1]}</th>`).join('')}</tr></thead>
            <tbody>${rows.map(x => `<tr>${cols.map(c => `<td class="${c[2] || ''}">${typeof c[0] === 'function' ? c[0](x) : esc(x[c[0]] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '<p class="hint">None</p>';
        document.getElementById('inv-body').innerHTML = `
            <div class="trail">
                <div class="step ok"><div class="t">1 · Tally invoice</div><div class="v">${esc(r.inv_no || no)}</div>
                    <div class="d">${dmy(r.inv_date)} · ${esc(r.plant || '')} · PO ${esc(r.order_no || '—')}<br>${r.amount ? `₹${inr(r.amount)} (${esc(r.amount_src)})` : ''}<br>${esc((r.sources || []).join(' + '))}</div></div>
                <div class="step ${grinOk ? 'ok' : 'bad'}"><div class="t">2 · TAFE GRIN</div><div class="v">${grinOk ? esc(r.grin_nos) : 'Not GRINed'}</div>
                    <div class="d">${grinOk ? `${dmy(r.grin_date)} · qty ${qty(r.grin_qty)} of ${qty(r.qty)}${r.rejected ? ` · rejected ${qty(r.rejected)}` : ''}` : `${r.age ?? ''} days since invoice${r.reminders ? ` · ${r.reminders} reminder(s)` : ''}`}</div></div>
                <div class="step ${payOk ? 'ok' : (grinOk ? '' : '')}"><div class="t">3 · TAFE payment</div><div class="v">${payOk ? esc(r.pv) : 'Not paid'}</div>
                    <div class="d">${payOk ? `${dmy(r.pv_date)} · ${esc(r.paid_by)}${r.credit ? ` · ₹${inr(r.credit)}` : ''}` : (r.due_date ? `due ${dmy(r.due_date)}${r.overdue_days ? ` · ${r.overdue_days} days late` : ''}` : '')}</div></div>
            </div>
            ${(r.notes || []).length ? `<div class="banner">${r.notes.map(esc).join('<br>')}</div>` : ''}
            <div class="mini-title">Parts on the invoice</div>
            ${tbl([['part', 'Part'], ['item', 'Item'], [x => qty(x.qty), 'Qty', 'num']], r.parts || [])}
            <div class="mini-title">GRIN lines</div>
            ${tbl([['grin_no', 'GRIN No'], [x => dmy(x.grin_date), 'Date'], ['plant', 'Plant'], ['po_no', 'PO'], ['part_no', 'Part'],
                [x => qty(x.grin_qty), 'GRIN qty', 'num'], [x => qty(x.accepted_qty), 'Accepted', 'num'], [x => qty(x.rejected_qty), 'Rejected', 'num']], d.grin)}
            <div class="mini-title">TAFE payment lines</div>
            ${tbl([['pv', 'Voucher'], [x => dmy(x.pv_date), 'Date'], ['doc_type', 'Type'], ['ref_doc', 'Ref doc'],
                [x => x.debit ? inr(x.debit) : '', 'Debit', 'num'], [x => x.credit ? inr(x.credit) : '', 'Credit', 'num']], d.pay)}
            <div class="mini-title">Reminder mails</div>
            ${tbl([[x => esc(when(x.sent_at || x.created_at)), 'When'], ['status', 'Status'], ['to_addr', 'To']], d.mails)}
            <div class="mini-title">Note</div>
            <div class="form-group"><textarea id="inv-note" rows="2" placeholder="e.g. returned by TAFE, DC pending, spoke to stores…">${esc(r.note || '')}</textarea></div>
            <label class="check"><input type="checkbox" id="inv-hold" ${r.hold ? 'checked' : ''}> Hold — do not send GRIN reminders for this invoice</label>
            <div class="modal-actions" style="margin-top:0.8rem"><button class="btn btn-primary" onclick="saveNote('${esc(d.inv_key)}')">Save note</button></div>`;
        openModal('inv-modal');
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function saveNote(k) {
    try {
        await apiJson('/api/grin/note', 'PUT', { inv_key: k, note: document.getElementById('inv-note').value,
            hold: document.getElementById('inv-hold').checked });
        closeModal('inv-modal');
        showToast('Saved', 'success');
        loadStatus();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

// the hand-marked invoice register checked against TAFE Channel's payments
function renderPayCheck(c) {
    const el = document.getElementById('paycheck');
    if (!c || !(c.agree + c.differ + c.not_marked + c.marked_not_paid)) { el.innerHTML = ''; return; }
    const bad = c.differ + c.not_marked + c.marked_not_paid;
    const label = { differ: 'Different voucher', not_marked: 'Paid in TAFE, not marked', marked_not_paid: 'Marked, but TAFE voucher does not have it' };
    el.innerHTML = `<div class="banner ${bad ? '' : 'info'}"><b>Invoice register vs TAFE Channel:</b> ${inr(c.agree, 0)} agree
        ${c.differ ? ` · <b>${inr(c.differ, 0)}</b> marked with a different voucher` : ''}
        ${c.not_marked ? ` · <b>${inr(c.not_marked, 0)}</b> paid in TAFE but not marked` : ''}
        ${c.marked_not_paid ? ` · <b>${inr(c.marked_not_paid, 0)}</b> marked but not in that TAFE voucher` : ''}
        ${bad ? ` <a href="#" onclick="document.getElementById('paycheck-list').style.display='';return false">show</a>
        <div id="paycheck-list" style="display:none;margin-top:0.4rem;max-height:220px;overflow:auto">${c.examples.map(x =>
            `<div>${esc(label[x.kind] || x.kind)} · <b>${esc(x.inv_no)}</b> · ${esc(x.text)}</div>`).join('')}
            ${bad > c.examples.length ? `<div>… and ${bad - c.examples.length} more (Download Excel → Checks column)</div>` : ''}</div>` : ''}</div>`;
}
