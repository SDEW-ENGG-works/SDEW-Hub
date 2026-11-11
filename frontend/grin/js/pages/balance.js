// TAFE outstanding on the Status page: what TAFE's books say it owes (Account Balance-Outstanding, fetched daily)
// against our invoices - expected this week, received this week, not in TAFE's books yet, total to receive.

const BAL = { data: null, tab: 'week', open: false, q: '' };
const BAL_CLS = { 'Overdue': 'st-od', 'This week': 'st-aw', 'Later': 'st-wait', 'Debit note': 'st-debit',
    'GRINed, not booked by TAFE': 'st-short', 'Not GRINed yet': 'st-ng' };
const L_ = n => {
    const v = parseFloat(n) || 0, a = Math.abs(v), sg = v < 0 ? '− ' : '';
    if (a >= 1e7) return `${sg}₹${(a / 1e7).toFixed(2)} Cr`;
    if (a >= 1e5) return `${sg}₹${(a / 1e5).toFixed(2)} L`;
    return `${sg}₹${inr(a, 0)}`;
};
const dShort = iso => iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short' }) : '';

async function loadBalance() {
    const el = document.getElementById('tafe-bal');
    if (!el) return;
    try {
        BAL.data = await api('/api/grin/balance');
        renderBalance();
        const f = BAL.data.fetch;
        if (f && f.running) pollBalance();
    } catch (e) {
        el.innerHTML = `<div class="banner danger">TAFE outstanding: ${esc(e.message)}</div>`;
    }
}

let _balTimer = null;
function pollBalance() {
    clearInterval(_balTimer);
    _balTimer = setInterval(async () => {
        try {
            const st = await api('/api/grin/balance/fetch');
            balFetchState(st);
            if (!st.running) {
                clearInterval(_balTimer);
                if (st.error) showToast(esc(st.error), 'danger', 9000);
                else showToast('TAFE outstanding updated', 'success');
                loadBalance();
            }
        } catch (e) { clearInterval(_balTimer); }
    }, 2500);
}

function balFetchState(st) {
    const b = document.getElementById('btn-bal');
    const s = document.getElementById('bal-state');
    if (b) b.disabled = !!st.running;
    if (s) s.textContent = st.running ? ((st.log || []).slice(-1)[0] || 'Fetching…').replace(/^\d\d:\d\d:\d\d\s+/, '') : '';
}

async function balFetch() {
    balFetchState({ running: true, log: ['Logging in to TAFE Channel…'] });
    try {
        const r = await apiJson('/api/grin/balance/fetch', 'POST', {});
        if (r.done) {
            if (r.error) showToast(esc(r.error), 'danger', 9000); else showToast('TAFE outstanding updated', 'success');
            balFetchState({});
            loadBalance();
        } else pollBalance();
    } catch (e) { balFetchState({}); showToast(e.message, 'danger', 9000); }
}

function renderBalance() {
    const d = BAL.data, el = document.getElementById('tafe-bal');
    const run = d.run;
    const head = `<div class="bal-head">
        <div><b>TAFE outstanding</b> <span class="dim">· week ${dShort(d.week_from)} – ${dShort(d.week_to)}</span></div>
        <div class="bal-head-r"><span id="bal-state" class="dim"></span>
            <span class="dim">${run ? `TAFE Channel read ${esc(when(run.fetched_at))} (${esc(run.source)}) · updates by itself every morning` : 'not fetched yet'}</span>
            <button class="btn btn-secondary btn-sm" id="btn-bal" onclick="balFetch()">Fetch now</button>
            ${run ? `<button class="btn btn-outline btn-sm" onclick="BAL.open=!BAL.open;renderBalance()">${BAL.open ? 'Hide details' : 'Details'}</button>` : ''}</div></div>`;
    if (!run) {
        el.innerHTML = `<div class="card bal-card">${head}<p class="muted-cell" style="padding:0.8rem!important">Press <b>Fetch now</b> to read Account Info › Account Balance-Outstanding from TAFE Channel.
            ${d.not_booked ? ` Meanwhile, from our own data: GRINed and unpaid ${L_(d.not_booked.value)} (${d.not_booked.n}), not GRINed ${L_(d.not_grined.value)} (${d.not_grined.n}).` : ''}</p></div>`;
        return;
    }
    const tw = d.this_week, prev = d.prev;
    const delta = prev ? d.owed - prev.owed : null;
    const adv = (run.balances || []).filter(b => b.amount && b.name !== 'General Acct. Bal.');
    const received = d.received.value + (d.received.value ? 0 : d.cleared.value);
    const maxT = Math.max(1, ...d.trend.map(t => t.owed));
    el.innerHTML = `<div class="card bal-card">${head}
        <div class="bal-cards">
            <div class="bal-c main"><div class="k">TAFE owes you (their books)</div><div class="v">${L_(d.owed)}</div>
                <div class="s">${inr(run.lines, 0)} documents booked · invoices ${L_(run.credit)}${run.debit ? ` − their debit notes ${L_(run.debit)}` : ''}</div>
                ${delta !== null && Math.abs(delta) >= 1 ? `<div class="s">${delta > 0 ? '▲' : '▼'} ${L_(Math.abs(delta))} since ${dShort(prev.fetch_date)}</div>` : ''}</div>
            <div class="bal-c"><div class="k">Expected this week</div><div class="v">${L_(tw.value)}</div>
                <div class="s">${inr(tw.n, 0)} invoice(s) due by ${dShort(d.week_to)} · TAFE pays ~${d.lag} days after GRIN</div>
                ${tw.late ? `<div class="s neg">incl. ${L_(tw.late)} overdue (${tw.late_n}) – past ${d.credit_days} days from GRIN</div>` : ''}
                ${tw.debits ? `<div class="s">after their debit notes ${L_(tw.debits)}</div>` : ''}</div>
            <div class="bal-c"><div class="k">Received this week</div><div class="v">${L_(received)}</div>
                <div class="s">${d.received.n ? `${inr(d.received.n, 0)} invoice(s) paid since ${dShort(d.week_from)} (payment data up to ${esc(dmy(d.received.pay_until))})` : 'no payment loaded for this week yet'}</div>
                ${d.cleared.n ? `<div class="s">${inr(d.cleared.n, 0)} document(s) ${L_(d.cleared.value)} left TAFE's list since ${dShort(d.cleared.since)}</div>` : ''}</div>
            <div class="bal-c"><div class="k">Not in TAFE's books yet</div><div class="v">${L_(d.not_booked.value + d.not_grined.value)}</div>
                <div class="s">GRINed, not booked ${L_(d.not_booked.value)} (${d.not_booked.n})</div>
                <div class="s">Not GRINed yet ${L_(d.not_grined.value)} (${d.not_grined.n})</div></div>
            <div class="bal-c total"><div class="k">Total still to receive</div><div class="v">${L_(d.total_due)}</div>
                <div class="s">booked ${L_(d.owed)} + not booked ${L_(d.not_booked.value + d.not_grined.value)}</div>
                <div class="s">after this week: ${L_(d.total_due - tw.value)}</div>
                ${adv.map(a => `<div class="s">${esc(a.name)}: ${L_(a.amount)} (advance – TAFE recovers it)</div>`).join('')}</div>
        </div>
        ${d.trend.length > 2 ? `<div class="bal-trend" title="What TAFE owes, day by day">${d.trend.map(t => `<span style="height:${Math.max(4, t.owed * 100 / maxT)}%" title="${esc(dmy(t.fetch_date))}: ${rupees(t.owed)} (${t.lines} docs)"></span>`).join('')}<em>last ${d.trend.length} days</em></div>` : ''}
        ${d.mismatch.n ? `<div class="banner" style="margin:0.6rem 0 0">${d.mismatch.n} invoice(s) (${L_(d.mismatch.value)}) are still unpaid in TAFE's books but marked paid in our data – check the payment marking.</div>` : ''}
        ${BAL.open ? balDetails() : ''}
    </div>`;
    if (BAL.open) {
        el.querySelectorAll('#bal-tabs .cat-pill').forEach(b => b.onclick = () => { BAL.tab = b.dataset.k; renderBalance(); });
        const s = document.getElementById('bal-q');
        s.oninput = e => { BAL.q = e.target.value; debounced(() => { renderBalance(); const n = document.getElementById('bal-q'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 250); };
    }
}

function balDetails() {
    const d = BAL.data;
    const by = b => d.items.filter(i => i.bucket === b);
    const tabs = [['week', 'This week', [...by('Overdue'), ...by('This week'), ...by('Debit note')]], ['later', 'Later', by('Later')],
        ['overdue', 'Overdue', by('Overdue')], ['notbooked', 'Not in TAFE books', d.not_booked_items],
        ['mismatch', 'Paid in our data', d.items.filter(i => i.flag && i.our_status === 'Paid')], ['all', 'All TAFE lines', d.items],
        ['bal', 'TAFE balances', null]];
    const cur = tabs.find(t => t[0] === BAL.tab) || tabs[0];
    const q = BAL.q.trim().toLowerCase();
    let table;
    if (cur[0] === 'bal') {
        table = `<table class="data-table grin-table"><thead><tr><th>Account (TAFE Channel)</th><th class="num">Balance</th></tr></thead><tbody>
            ${d.run.balances.map(b => `<tr><td>${esc(b.name)}</td><td class="num">${rupees(b.amount)}</td></tr>`).join('')}
            <tr><td><b>Net (negative = TAFE owes you)</b></td><td class="num"><b>${rupees(d.run.net)}</b></td></tr></tbody></table>`;
    } else {
        const list = cur[2].filter(i => !q || [i.ref, i.doc_no, i.plant, i.our_status, i.narration].some(v => String(v || '').toLowerCase().includes(q)));
        const sum = list.reduce((a, i) => a + (i.amount || 0), 0);
        if (cur[0] === 'notbooked') {
            table = `<table class="data-table grin-table"><thead><tr><th>Where</th><th>Invoice</th><th>Date</th><th>Plant</th><th class="num">Value</th><th>GRIN date</th><th class="num">Days</th></tr></thead><tbody>
                ${list.slice(0, 600).map(i => `<tr><td><span class="st ${BAL_CLS[i.bucket] || ''}">${esc(i.bucket)}</span></td><td><b>${esc(i.ref)}</b></td><td>${shortDate(i.inv_date)}</td>
                <td>${esc(i.plant)}</td><td class="num">${rupees(i.amount)}</td><td>${shortDate(i.grin_date)}</td><td class="num">${i.days ?? ''}</td></tr>`).join('') || '<tr><td colspan="7" class="muted-cell">Nothing here.</td></tr>'}</tbody></table>`;
        } else {
            table = `<table class="data-table grin-table"><thead><tr><th>When</th><th>Invoice / ref</th><th>Plant</th><th>TAFE doc</th><th>Booked</th><th>GRIN</th><th>Expected</th><th class="num">Amount</th><th>Our status</th><th>Narration</th></tr></thead><tbody>
                ${list.slice(0, 600).map(i => `<tr><td><span class="st ${BAL_CLS[i.bucket] || ''}">${esc(i.bucket)}</span>${i.late_days ? `<span class="sub neg">${i.late_days} days late</span>` : ''}</td>
                <td><b>${esc(i.ref)}</b></td><td>${esc(i.plant)}</td><td>${esc(i.doc_no)}<span class="sub">${esc(i.doc_type)}</span></td><td>${shortDate(i.doc_date)}</td>
                <td>${shortDate(i.grin_date)}</td><td>${dShort(i.expected)}</td><td class="num"><b>${rupees(i.amount)}</b></td>
                <td>${esc(i.our_status || '–')}${i.flag ? `<span class="sub">${esc(i.flag)}</span>` : ''}</td><td>${esc(i.narration || '')}</td></tr>`).join('') || '<tr><td colspan="10" class="muted-cell">Nothing here.</td></tr>'}</tbody></table>`;
        }
        table = `<div class="dim small" style="margin:0.3rem 0">${inr(list.length, 0)} line(s) · ${rupees(sum)}${list.length > 600 ? ' · showing 600' : ''}</div>` + table;
    }
    return `<div class="bal-details"><div class="card-header-flex">
        <div class="category-pills" id="bal-tabs">${tabs.map(t => `<button class="cat-pill ${t[0] === cur[0] ? 'active' : ''}" data-k="${t[0]}">${esc(t[1])}${t[2] ? `<span class="pill-count">${t[2].length}</span>` : ''}</button>`).join('')}</div>
        <div class="search-box"><input type="text" id="bal-q" placeholder="Invoice, TAFE doc, plant…" value="${esc(BAL.q)}"></div></div>
        <div class="table-wrapper" style="max-height:460px;overflow:auto">${table}</div></div>`;
}
