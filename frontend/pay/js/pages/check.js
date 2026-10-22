// Check page: sources, totals, vouchers and the invoice-by-invoice result.

const CAT_INFO = {
    'To mark': { cls: 'active', help: 'Paid by TAFE (credit line in the export) and not yet marked — these get the voucher number and date.' },
    'Credit + debit note': { cls: 'active', help: 'Paid, but TAFE also raised a debit note (ZK) on the invoice. Marked like any paid invoice, as was done by hand before. Untick to leave them.' },
    'Amount differs': { cls: 'warn', help: 'Paid, but the credit is not close to the invoice amount (TDS is about 0.1 %). Check, then tick or untick.' },
    'Already marked': { cls: 'sent', help: 'The register already has this voucher number — nothing to do.' },
    'Marked with another number': { cls: 'warn', help: 'The register has a different number for this invoice (often a typo, e.g. 1383032039 for 138032039). Not changed unless you tick it.' },
    'Debit note only': { cls: 'muted', help: 'Only a debit note (ZK) for this invoice in the export — that is not a payment, so it is not marked.' },
    'Not in register': { cls: 'inactive', help: 'Invoice number from the export not found in the register (old year, or typed without year).' },
    'Cancelled in register': { cls: 'inactive', help: 'Payment against an invoice that is cancelled in the register — check by hand.' },
};
const CAT_ORDER = Object.keys(CAT_INFO);
const LOCKED = new Set(['Already marked', 'Debit note only', 'Not in register']);

function catBadge(c) {
    return `<span class="status-badge ${(CAT_INFO[c] || {}).cls || 'muted'}">${esc(c)}</span>`;
}

function renderSources() {
    const r = appState.register, p = appState.payments || {};
    const regCard = document.getElementById('src-register');
    regCard.classList.toggle('ready', !!r);
    document.getElementById('src-register-sub').textContent = r ? r.name : 'Not uploaded';
    document.getElementById('src-register-body').innerHTML = r ? `
        <span class="chip"><b>${inr(r.info.invoices, 0)}</b> invoices</span>
        <span class="chip"><b>${inr(r.info.marked, 0)}</b> marked</span>
        <span class="chip"><b>${inr(r.info.unmarked, 0)}</b> not marked</span>` : '';
    const payCard = document.getElementById('src-payments');
    payCard.classList.toggle('ready', !!p.n);
    document.getElementById('src-payments-sub').textContent = p.n
        ? `${shortDate(p.first)} to ${shortDate(p.last)}` : 'Not uploaded';
    document.getElementById('src-payments-body').innerHTML = p.n ? `
        <span class="chip"><b>${inr(p.vouchers, 0)}</b> vouchers</span>
        <span class="chip"><b>${inr(p.n, 0)}</b> lines</span>` : '';
    document.getElementById('voucher-count-badge').textContent = inr(p.vouchers || 0, 0);
}

function renderSummary() {
    const run = appState.run;
    const set = (id, v) => { document.getElementById(id).textContent = v; };
    document.getElementById('btn-marked').disabled = !run;
    document.getElementById('btn-report').disabled = !run;
    if (!run) {
        ['st-mark', 'st-done', 'st-look', 'st-none'].forEach(id => set(id, '—'));
        document.getElementById('voucher-card').style.display = 'none';
        document.getElementById('mark-count-badge').textContent = '0';
        renderPills();
        return;
    }
    const s = run.summary, c = s.cats;
    const n = k => (c[k] || {}).n || 0;
    set('st-mark', inr(s.to_mark, 0));
    set('st-mark-sub', `${rupees(s.mark_value)} received`);
    set('st-done', inr(n('Already marked'), 0));
    set('st-done-sub', 'nothing to do');
    set('st-look', inr(n('Marked with another number') + n('Amount differs') + n('Cancelled in register'), 0));
    set('st-look-sub', `${inr(n('Marked with another number'), 0)} other number · ${inr(n('Amount differs'), 0)} amount`);
    set('st-none', inr(n('Debit note only') + n('Not in register'), 0));
    set('st-none-sub', `${inr(n('Debit note only'), 0)} debit note only · ${inr(n('Not in register'), 0)} not found`);
    document.getElementById('mark-count-badge').textContent = inr(s.to_mark, 0);

    document.getElementById('voucher-card').style.display = '';
    document.getElementById('voucher-tbody').innerHTML = s.vouchers.map(v => `
        <tr><td><b>${esc(v.pv)}</b></td><td>${dotted(v.pv_date)}</td><td class="num">${inr(v.lines, 0)}</td>
        <td class="num">${inr(v.amount)}</td><td class="num">${inr(v.credit)}</td><td class="num">${inr(v.debit)}</td>
        <td class="num">${v.discount ? inr(v.discount) : ''}</td><td class="num strong">${inr(v.net)}</td>
        <td>${v.tallies ? '<span class="status-badge active">Tallies</span>' : '<span class="status-badge inactive">Does not tally</span>'}</td></tr>`).join('');
    renderPills();
}

function renderPills() {
    const run = appState.run;
    const c = run ? run.summary.cats : {};
    const total = run ? run.summary.invoices : 0;
    const pill = (key, label, count) => `<button class="cat-pill ${appState.cat === key ? 'active' : ''}" data-c="${esc(key)}">
        ${esc(label)}<span class="pill-count">${inr(count, 0)}</span></button>`;
    document.getElementById('cat-pills').innerHTML = !run ? '' :
        pill('', 'All', total) + pill('marking', 'Being marked', run.summary.to_mark) +
        CAT_ORDER.filter(k => (c[k] || {}).n).map(k => pill(k, k, c[k].n)).join('');
    document.querySelectorAll('#cat-pills .cat-pill').forEach(b => b.onclick = () => {
        appState.cat = b.dataset.c;
        renderPills();
        loadLines(0);
    });
    const help = document.getElementById('cat-help');
    const info = CAT_INFO[appState.cat];
    if (run && info) {
        const cc = c[appState.cat];
        const bulk = LOCKED.has(appState.cat) ? '' : `
            <div class="btn-row">
                <button class="btn btn-outline btn-sm" onclick="setCategory('mark')">Tick all ${inr(cc.n, 0)}</button>
                <button class="btn btn-outline btn-sm" onclick="setCategory('skip')">Untick all</button>
            </div>`;
        help.innerHTML = `<span>${esc(info.help)}</span>${bulk}`;
        help.style.display = '';
    } else {
        help.style.display = 'none';
    }
}

async function loadLines(offset = 0) {
    appState.offset = offset;
    const tbody = document.getElementById('lines-tbody');
    if (!appState.run) {
        tbody.innerHTML = `<tr><td colspan="14" class="muted-cell">Upload the two files, then press Check payments</td></tr>`;
        document.getElementById('lines-total-text').textContent = '';
        return;
    }
    const q = encodeURIComponent(document.getElementById('line-search').value.trim());
    try {
        const d = await api(`/api/pay/check/lines?cat=${encodeURIComponent(appState.cat)}&q=${q}&limit=${PAGE}&offset=${offset}`);
        tbody.innerHTML = d.lines.length ? d.lines.map(l => {
            const canTick = l.reg_row && !LOCKED.has(l.cat);
            const box = canTick
                ? `<input type="checkbox" class="mark-box" data-seq="${l.seq}" ${l.action === 'mark' ? 'checked' : ''}>`
                : (l.cat === 'Already marked' ? '<span class="tick-done">✓</span>' : '');
            const now = l.reg_mark ? `${esc(l.reg_mark)} <span class="stat-sub">${esc(l.reg_mark_date.includes('-') ? dotted(l.reg_mark_date) : l.reg_mark_date)}</span>` : '<span class="stat-sub">blank</span>';
            return `<tr class="${l.action === 'mark' ? 'row-mark' : ''}">
                <td class="center">${box}</td><td>${catBadge(l.cat)}</td><td><b>${esc(l.inv)}</b></td>
                <td class="num">${l.reg_row || ''}</td><td>${dotted(l.reg_date)}</td><td class="wrap">${esc(l.reg_party)}</td>
                <td class="num">${l.reg_amount != null ? inr(l.reg_amount) : ''}</td><td><b>${esc(l.pv)}</b></td><td>${dotted(l.pv_date)}</td>
                <td class="num">${l.credit ? inr(l.credit) : ''}</td><td class="num">${l.debit ? inr(l.debit) : ''}</td>
                <td>${esc(l.doc_types)}</td><td>${now}</td><td class="wrap stat-sub">${esc(l.note)}</td></tr>`;
        }).join('') : `<tr><td colspan="14" class="muted-cell">Nothing here</td></tr>`;
        tbody.querySelectorAll('.mark-box').forEach(cb => cb.onchange = () => setAction(cb));
        document.getElementById('lines-total-text').innerHTML = `<b>${inr(d.total, 0)}</b> invoices`;
        pager(document.getElementById('lines-pager'), d.total, offset, o => loadLines(o));
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function setAction(cb) {
    try {
        appState.run = await apiJson(`/api/pay/check/lines/${cb.dataset.seq}`, 'PUT', { action: cb.checked ? 'mark' : 'skip' });
        cb.closest('tr').classList.toggle('row-mark', cb.checked);
        renderSummary();
    } catch (e) {
        cb.checked = !cb.checked;
        showToast(e.message, 'danger');
    }
}

async function setCategory(action) {
    try {
        appState.run = await apiJson('/api/pay/check/category', 'PUT', { cat: appState.cat, action });
        renderSummary();
        loadLines(appState.offset);
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function runCheck(quiet) {
    const btn = document.getElementById('btn-check');
    if (!appState.register) return showToast('Upload the invoice register first.', 'danger');
    if (!(appState.payments || {}).n) return showToast('Upload the TAFE payment details export first.', 'danger');
    setBusy(btn, true, 'Checking…');
    try {
        appState.run = await apiJson('/api/pay/check', 'POST', {});
        appState.cat = appState.run.summary.to_mark ? 'marking' : '';
        renderSummary();
        loadLines(0);
        const s = appState.run.summary;
        const bad = s.vouchers.filter(v => !v.tallies).length;
        showToast(`${inr(s.to_mark, 0)} invoices to mark · ${inr(s.cats['Already marked'].n, 0)} already marked` +
            (bad ? ` · <b>${bad} voucher(s) do not tally</b>` : ''), bad ? 'danger' : 'success', 5000);
    } catch (e) {
        showToast(e.message, 'danger');
    } finally {
        setBusy(btn, false);
    }
}

async function downloadMarked() {
    const run = appState.run;
    if (!run) return;
    if (!run.summary.to_mark) {
        const ok = await confirmBox('Nothing is ticked', 'No invoice is ticked for marking. Download the register unchanged?');
        if (!ok) return;
    }
    const name = await downloadFile('/api/pay/export/marked', document.getElementById('btn-marked'), 'Register_marked.xlsx');
    if (name) {
        showToast(`${inr(run.summary.to_mark, 0)} invoices marked in <b>${esc(name)}</b>. That file is now the register — the next check starts from it.`, 'success', 7000);
        await refreshBootstrap();
        renderSources();
    }
}

function downloadReport() {
    downloadFile('/api/pay/export/report', document.getElementById('btn-report'), 'Payment_Check.xlsx');
}
