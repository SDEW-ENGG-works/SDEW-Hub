// Monthly report: how much TAFE paid in a month, deductions, per plant / voucher / invoice, and what is still pending.

const MR = { month: '', data: null, tab: 'vouchers', q: '' };
const MR_KIND = { 'Overdue': 'st-od', 'Not yet due': 'st-aw', 'Not GRINed': 'st-ng' };

function mrLabel(m) {
    const d = new Date(`${m}-01T00:00:00`);
    return d.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
}
const lakh = n => {
    const v = parseFloat(n) || 0;
    if (Math.abs(v) >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
    if (Math.abs(v) >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
    return `₹${inr(v, 0)}`;
};

async function loadMonthly(month = MR.month) {
    const box = document.getElementById('mr-body');
    if (!MR.data) box.innerHTML = '<div class="card muted-cell">Working out the month…</div>';
    try {
        const d = await api(`/api/grin/monthly${month ? `?month=${month}` : ''}`);
        MR.data = d;
        MR.month = d.month;
        renderMonthly();
    } catch (e) {
        box.innerHTML = `<div class="banner danger">${esc(e.message)}</div>`;
    }
}

function mrStep(dir) {
    const ms = (MR.data && MR.data.months) || [];
    const i = ms.indexOf(MR.month);
    const j = i - dir;                 // months are newest first
    if (j >= 0 && j < ms.length) loadMonthly(ms[j]);
}

function mrDownload() {
    location.href = `/api/grin/monthly/export?month=${encodeURIComponent(MR.month)}`;
}

function mrDelta(now, before) {
    if (before === null || before === undefined || !before) return '';
    const p = ((now - before) / Math.abs(before)) * 100;
    const cls = p >= 0 ? 'up' : 'down';
    return `<span class="mr-delta ${cls}">${p >= 0 ? '▲' : '▼'} ${Math.abs(p).toFixed(0)}% vs ${esc(mrLabel(MR.data.prev.month).split(' ')[0])}</span>`;
}

function renderMonthly() {
    const d = MR.data, s = d.summary, sp = d.speed, b = d.billed, p = d.pending, pv = d.prev;
    const sel = document.getElementById('mr-month');
    sel.innerHTML = d.months.map(m => `<option value="${m}" ${m === d.month ? 'selected' : ''}>${esc(mrLabel(m))}</option>`).join('');
    const i = d.months.indexOf(d.month);
    document.getElementById('mr-prev').disabled = i >= d.months.length - 1;
    document.getElementById('mr-next').disabled = i <= 0;

    const ded = s.debit_note + s.discount + s.other;
    const paidPct = sp.on_time_n + sp.late_n ? Math.round(sp.on_time_n * 100 / (sp.on_time_n + sp.late_n)) : null;
    const billedPaidPct = b.value ? Math.round(b.paid_same_month * 100 / b.value) : 0;
    const maxTrend = Math.max(1, ...d.trend.map(t => Math.max(t.net, t.billed)));

    document.getElementById('mr-body').innerHTML = `
        ${d.notes.map(n => `<div class="banner info">${esc(n)}</div>`).join('')}

        <div class="mr-hero">
            <div class="mr-net">
                <div class="k">Net received in ${esc(d.label)}</div>
                <div class="v">${rupees(s.net)}</div>
                <div class="s">${inr(s.payments, 0)} payment voucher(s) · ${inr(s.invoices, 0)} invoice(s) paid · ${esc(s.source || 'no payments')}</div>
                ${pv ? `<div class="s">${mrDelta(s.net, pv.net)} <span class="dim">(${esc(mrLabel(pv.month))}: ${lakh(pv.net)})</span></div>` : ''}
            </div>
            <div class="mr-calc">
                <div><span>Invoices paid (gross)</span><b>${rupees(s.gross)}</b></div>
                <div class="minus"><span>Less: debit notes (ZK)</span><b>− ${rupees(s.debit_note)}</b></div>
                <div class="minus"><span>Less: cash discount (KG)</span><b>− ${rupees(s.discount)}</b></div>
                ${s.other ? `<div class="minus"><span>Less: other deductions</span><b>− ${rupees(s.other)}</b></div>` : ''}
                <div class="tot"><span>Net received</span><b>${rupees(s.net)}</b></div>
                ${s.gross ? `<div class="dim small">Deductions are ${(ded * 100 / s.gross).toFixed(2)}% of the invoices paid</div>` : ''}
            </div>
        </div>

        <div class="mr-cards">
            <div class="mr-card">
                <div class="k">How fast TAFE paid</div>
                <div class="v">${sp.avg_grin ?? '–'} <small>days</small></div>
                <div class="s">from GRIN to payment (avg) · ${sp.avg_inv ?? '–'} days from invoice</div>
            </div>
            <div class="mr-card">
                <div class="k">Paid on time</div>
                <div class="v">${paidPct === null ? '–' : paidPct + '%'}</div>
                <div class="s">${inr(sp.on_time_n, 0)} within ${d.credit_days} days of GRIN · <span class="neg">${inr(sp.late_n, 0)} late</span>${sp.late_avg ? ` by ${sp.late_avg} days avg (${lakh(sp.late_value)})` : ''}</div>
            </div>
            <div class="mr-card">
                <div class="k">Billed in ${esc(d.label.split(' ')[0])}</div>
                <div class="v">${lakh(b.value)}</div>
                <div class="s">${inr(b.n, 0)} invoice(s) · ${billedPaidPct}% (${lakh(b.paid_same_month)}) paid within the month</div>
                <div class="mr-bar">${b.by_status.map(x => `<span class="${ST_CLASS[x.status] || ''}" style="flex:${x.value || 0.0001}" title="${esc(x.status)}: ${inr(x.n, 0)} · ${rupees(x.value)}"></span>`).join('')}</div>
                <div class="mr-legend">${b.by_status.map(x => `<span><i class="${ST_CLASS[x.status] || ''}"></i>${esc(x.status)} ${lakh(x.value)}</span>`).join('')}</div>
            </div>
            <div class="mr-card">
                <div class="k">Still to come at ${d.to > new Date().toISOString().slice(0, 10) ? 'today' : 'month end'}</div>
                <div class="v">${lakh(p.value)}</div>
                <div class="s">${inr(p.n, 0)} invoice(s) not paid</div>
                <div class="mr-split">
                    <span class="st st-od">Overdue ${lakh(p.overdue_value)} (${inr(p.overdue_n, 0)})</span>
                    <span class="st st-aw">Not yet due ${lakh(p.due_value)} (${inr(p.due_n, 0)})</span>
                    <span class="st st-ng">Not GRINed ${lakh(p.ng_value)} (${inr(p.ng_n, 0)})</span>
                </div>
            </div>
        </div>

        <div class="mr-grid2">
            <div class="card">
                <div class="card-title">By plant</div>
                <div class="table-wrapper"><table class="data-table grin-table">
                    <thead><tr><th>Plant</th><th class="num">Invoices</th><th class="num">Gross</th><th class="num">Debit notes</th><th class="num">Net</th><th class="num">Share</th></tr></thead>
                    <tbody>${d.by_plant.map(x => `<tr><td><b>${esc(x.plant)}</b></td><td class="num">${inr(x.invoices, 0)}</td>
                        <td class="num">${rupees(x.gross)}</td><td class="num">${x.deductions ? rupees(x.deductions) : '–'}</td>
                        <td class="num"><b>${rupees(x.net)}</b></td><td class="num">${s.gross ? (x.gross * 100 / s.gross).toFixed(1) + '%' : ''}</td></tr>`).join('')}
                    ${s.discount ? `<tr class="dimrow"><td>Cash discount (whole voucher)</td><td></td><td></td><td class="num">${rupees(s.discount)}</td><td class="num">− ${rupees(s.discount)}</td><td></td></tr>` : ''}
                    </tbody>
                    <tfoot><tr><td><b>Total</b></td><td class="num"><b>${inr(s.invoices, 0)}</b></td><td class="num"><b>${rupees(s.gross)}</b></td>
                        <td class="num"><b>${rupees(ded)}</b></td><td class="num"><b>${rupees(s.net)}</b></td><td></td></tr></tfoot>
                </table></div>
            </div>
            <div class="card">
                <div class="card-title">When the money came</div>
                <div class="mr-weeks">${d.by_week.length ? d.by_week.map(w => `
                    <div class="mr-week"><span class="lbl">${esc(w.label)}</span>
                        <span class="bar"><i style="width:${s.net ? Math.max(2, w.net * 100 / s.net) : 0}%"></i></span>
                        <b>${lakh(w.net)}</b><span class="dim">${w.payments} PV</span></div>`).join('')
                    : '<p class="muted-cell">No payments in this month.</p>'}</div>
            </div>
        </div>

        <div class="card">
            <div class="card-header-flex">
                <div class="category-pills" id="mr-tabs">
                    ${[['vouchers', `Payment vouchers (${d.vouchers.length})`], ['invoices', `Invoices paid (${inr(d.invoices_total ?? d.invoices.length, 0)})`],
                       ['deductions', `Deductions (${d.deductions.length})`], ['pending', `Pending (${inr(d.pending_list.length, 0)})`],
                       ['trend', 'Month by month']].map(([k, l]) =>
                        `<button class="cat-pill ${MR.tab === k ? 'active' : ''}" onclick="mrTab('${k}')">${esc(l)}</button>`).join('')}
                </div>
                <div class="search-box"><input type="text" id="mr-search" placeholder="Invoice, voucher or plant…" value="${esc(MR.q)}" oninput="MR.q=this.value; debounced(mrTable, 200)"></div>
            </div>
            <div class="table-wrapper" id="mr-table"></div>
        </div>

        <div class="card">
            <div class="card-title">Received vs billed, month by month</div>
            <div class="mr-trend">${d.trend.map(t => `
                <div class="mr-tcol ${t.month === d.month ? 'on' : ''}" onclick="loadMonthly('${t.month}')" title="${esc(mrLabel(t.month))}: received ${rupees(t.net)} · billed ${rupees(t.billed)}">
                    <div class="bars"><i class="rec" style="height:${t.net * 100 / maxTrend}%"></i><i class="bil" style="height:${t.billed * 100 / maxTrend}%"></i></div>
                    <b>${lakh(t.net)}</b><span>${esc(mrLabel(t.month).slice(0, 3))} ${t.month.slice(2, 4)}</span>
                </div>`).join('')}</div>
            <div class="mr-legend"><span><i class="rec"></i>Net received</span><span><i class="bil"></i>Billed (invoices raised)</span></div>
        </div>`;
    mrTable();
}

function mrTab(k) {
    MR.tab = k;
    document.querySelectorAll('#mr-tabs .cat-pill').forEach(b => b.classList.toggle('active', b.getAttribute('onclick') === `mrTab('${k}')`));
    mrTable();
}

function mrTable() {
    const d = MR.data, el = document.getElementById('mr-table');
    if (!d || !el) return;
    const q = MR.q.trim().toLowerCase();
    const hit = (...vals) => !q || vals.some(v => String(v ?? '').toLowerCase().includes(q));
    const LIMIT = 500;
    let head, body, list;
    if (MR.tab === 'vouchers') {
        list = d.vouchers.filter(v => hit(v.pv, v.source));
        head = '<th>Voucher (PV)</th><th>Date</th><th>Source</th><th class="num">Invoices</th><th class="num">Gross</th><th class="num">Debit notes</th><th class="num">Cash discount</th><th class="num">Net received</th>';
        body = list.map(v => `<tr><td><b>${esc(v.pv)}</b></td><td>${shortDate(v.pv_date)}</td><td>${esc(v.source)}</td>
            <td class="num">${inr(v.invoices, 0)}</td><td class="num">${rupees(v.gross)}</td><td class="num">${v.debit_note ? rupees(v.debit_note) : '–'}</td>
            <td class="num">${v.discount ? rupees(v.discount) : '–'}</td><td class="num"><b>${rupees(v.net)}</b></td></tr>`);
    } else if (MR.tab === 'invoices') {
        list = d.invoices.filter(x => hit(x.inv_no, x.pv, x.plant));
        head = '<th>Invoice</th><th>Inv. date</th><th>Plant</th><th class="num">Invoice value</th><th class="num">Paid</th><th>Voucher</th><th>Paid on</th><th>GRIN</th><th class="num">Days</th><th>On time?</th>';
        body = list.slice(0, LIMIT).map(x => {
            const diff = x.amount ? x.paid - x.amount : 0;
            return `<tr><td><b>${esc(x.inv_no)}</b></td><td>${shortDate(x.inv_date)}</td><td>${esc(x.plant)}</td>
            <td class="num">${x.amount ? rupees(x.amount) : ''}</td>
            <td class="num">${rupees(x.paid)}${Math.abs(diff) > 1 ? `<span class="sub ${diff < 0 ? 'neg' : ''}">${diff > 0 ? '+' : ''}${inr(diff)}</span>` : ''}</td>
            <td>${esc(x.pv)}<span class="sub">${esc(x.source === 'Invoice register' ? 'register' : '')}</span></td><td>${shortDate(x.pv_date)}</td>
            <td>${shortDate(x.grin_date)}</td><td class="num">${x.days_grin ?? ''}<span class="sub">${x.days_inv != null ? x.days_inv + ' from inv' : ''}</span></td>
            <td>${x.on_time === true ? '<span class="st st-paid">On time</span>' : x.on_time === false ? `<span class="st st-od">${x.late_days} days late</span>` : ''}</td></tr>`;
        });
    } else if (MR.tab === 'deductions') {
        list = d.deductions.filter(x => hit(x.pv, x.ref, x.kind, x.plant));
        head = '<th>Voucher</th><th>Date</th><th>Kind</th><th>Reference</th><th>TAFE doc</th><th>Plant</th><th class="num">Amount</th>';
        body = list.map(x => `<tr><td>${esc(x.pv)}</td><td>${shortDate(x.pv_date)}</td>
            <td><span class="st ${x.kind === 'Debit note' ? 'st-debit' : 'st-wait'}">${esc(x.kind)}</span> <span class="tag">${esc(x.doc_type)}</span></td>
            <td>${esc(x.ref)}</td><td>${esc(x.ref_doc)}</td><td>${esc(x.plant)}</td><td class="num"><b>${rupees(x.amount)}</b></td></tr>`);
    } else if (MR.tab === 'pending') {
        list = d.pending_list.filter(x => hit(x.inv_no, x.plant, x.kind));
        head = '<th>Where</th><th>Invoice</th><th>Inv. date</th><th>Plant</th><th class="num">Value</th><th>GRIN</th><th>Due</th><th class="num">Overdue by</th><th>Paid later</th>';
        body = list.slice(0, LIMIT).map(x => `<tr><td><span class="st ${MR_KIND[x.kind] || ''}">${esc(x.kind)}</span></td>
            <td><b>${esc(x.inv_no)}</b></td><td>${shortDate(x.inv_date)}</td><td>${esc(x.plant)}</td><td class="num">${rupees(x.amount)}</td>
            <td>${shortDate(x.grin_date)}</td><td>${shortDate(x.due_date)}</td><td class="num">${x.late_days ? x.late_days + ' days' : ''}</td><td>${shortDate(x.paid_on)}</td></tr>`);
    } else {
        list = d.trend.slice().reverse().filter(t => hit(t.month, mrLabel(t.month)));
        head = '<th>Month</th><th class="num">Vouchers</th><th class="num">Invoices paid</th><th class="num">Gross</th><th class="num">Deductions</th><th class="num">Net received</th><th class="num">Billed</th><th class="num">Pending at month end</th><th class="num">of which overdue</th><th>Source</th>';
        body = list.map(t => `<tr class="${t.month === d.month ? 'on' : ''}" style="cursor:pointer" onclick="loadMonthly('${t.month}')"><td><b>${esc(mrLabel(t.month))}</b></td>
            <td class="num">${t.payments}</td><td class="num">${inr(t.invoices, 0)}</td><td class="num">${rupees(t.gross)}</td>
            <td class="num">${t.deductions ? rupees(t.deductions) : '–'}</td><td class="num"><b>${rupees(t.net)}</b></td>
            <td class="num">${rupees(t.billed)}<span class="sub">${inr(t.billed_n, 0)} inv</span></td><td class="num">${rupees(t.pending)}</td>
            <td class="num">${t.overdue ? rupees(t.overdue) : '–'}</td><td>${esc(t.source)}</td></tr>`);
    }
    const cols = (head.match(/<th/g) || []).length;
    el.innerHTML = `<table class="data-table grin-table"><thead><tr>${head}</tr></thead><tbody>${body.length ? body.join('')
        : `<tr><td colspan="${cols}" class="muted-cell">Nothing here${q ? ' for this search' : ''}.</td></tr>`}</tbody></table>
        ${list.length > LIMIT && (MR.tab === 'invoices' || MR.tab === 'pending') ? `<div class="table-footer"><span>Showing ${LIMIT} of ${inr(list.length, 0)} - search, or Download Excel for all.</span></div>` : ''}`;
}
