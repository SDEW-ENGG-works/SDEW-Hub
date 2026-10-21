// Bill page: totals, plant pills, bill lines (the agreed 17 columns), Excel download.

function renderBillSummary() {
    const run = appState.run;
    const s = run && run.summary;
    const set = (id, v) => { document.getElementById(id).textContent = v; };
    document.getElementById('btn-export').disabled = !run;
    document.getElementById('btn-export-pending').disabled = !run;
    if (!s) {
        ['st-basic', 'st-gst', 'st-total', 'st-lines'].forEach(id => set(id, '—'));
        document.getElementById('bill-plant-pills').innerHTML = '';
        document.getElementById('bill-tbody').innerHTML =
            `<tr><td colspan="16"><div class="empty-state"><h3>No bill yet</h3><p>Upload the POs, GRIN files and the Tally Sales Register on the Uploads page, then press <b>Calculate bill</b>.</p></div></td></tr>`;
        document.getElementById('missing-po-card').style.display = 'none';
        return;
    }
    set('st-basic', rupees(s.total.bill_value));
    set('st-gst', rupees(s.total.gst));
    set('st-total', rupees(s.total.with_gst));
    set('st-lines', inr(s.total.bill_lines, 0));
    document.getElementById('bill-count-badge').textContent = inr(s.total.bill_lines, 0);
    const p = run.params || {};
    document.getElementById('bill-desc').innerHTML =
        `TAFE price revision ${shortDate(p.old_date)} → ${shortDate(p.new_date)} · calculated ${esc(when(run.created_at))}`;

    const billed = s.plants.filter(x => x.bill_lines > 0);
    if (!billed.find(x => x.plant === appState.billPlant)) appState.billPlant = billed.length ? billed[0].plant : null;
    document.getElementById('bill-plant-pills').innerHTML = billed.map(x => `
        <button class="cat-pill ${x.plant === appState.billPlant ? 'active' : ''}" onclick="pickBillPlant('${esc(x.plant)}')">
            ${esc(x.plant)}<span class="pill-count">${inr(x.bill_lines, 0)} · ${rupees(x.bill_value)}</span>
        </button>`).join('');

    const missing = s.missing_pos || [];
    document.getElementById('missing-po-card').style.display = missing.length ? '' : 'none';
    document.getElementById('missing-po-list').innerHTML = missing.map(([po, n]) =>
        `<span class="chip"><b>${esc(po)}</b> · ${n} lines</span>`).join('');
    const notBilled = s.plants.reduce((a, x) => a + Object.entries(x.cats).filter(([k]) => k !== 'Bill').reduce((b, [, v]) => b + v.lines, 0), 0);
    document.getElementById('review-count-badge').textContent = inr(notBilled, 0);
}

function pickBillPlant(p) {
    appState.billPlant = p;
    appState.billOffset = 0;
    renderBillSummary();
    loadBillLines();
}

async function loadBillLines(offset) {
    if (typeof offset === 'number') appState.billOffset = offset;
    else appState.billOffset = 0;
    if (!appState.run || !appState.billPlant) return;
    const q = encodeURIComponent(document.getElementById('bill-search').value.trim());
    const tbody = document.getElementById('bill-tbody');
    try {
        const d = await api(`/api/supp/bill/lines?plant=${encodeURIComponent(appState.billPlant)}&cat=Bill&q=${q}&limit=${PAGE}&offset=${appState.billOffset}`);
        const ovr = new Set(((appState.run.params || {}).overrides || []).map(o => o.part));
        tbody.innerHTML = d.lines.length ? d.lines.map(l => `
            <tr>
                <td>${esc(l.voucher)}</td><td>${shortDate(l.inv_date)}</td><td>${esc(l.order_no)}</td>
                <td><b>${esc(l.part)}</b></td><td class="wrap">${esc(l.descr)}</td><td>${esc(l.hsn)}</td>
                <td class="num">${inr(l.gst, 0)}</td><td class="num">${qty(l.qty)}</td><td class="num">${inr(l.rate)}</td>
                <td class="num">${inr(l.old_rate)}</td><td class="num ${ovr.has(l.part) ? 'yellow' : ''}">${inr(l.new_rate)}</td>
                <td class="num">${inr(l.diff)}</td><td class="num strong">${inr(l.value)}</td>
                <td>${esc(l.grn_no)}</td><td>${dmy(l.grn_date)}</td>
                <td title="${esc(l.notes)}">${statusBadge(l.status)}${l.notes ? ' <span class="stat-sub">ⓘ</span>' : ''}</td>
            </tr>`).join('') : `<tr><td colspan="16" class="muted-cell">No lines match</td></tr>`;
        document.getElementById('bill-total-text').innerHTML =
            `<b>${inr(d.total, 0)}</b> lines · qty <b>${qty(d.qty)}</b> · basic value <b>${rupees(d.value)}</b>`;
        pager(document.getElementById('bill-pager'), d.total, appState.billOffset, o => loadBillLines(o));
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function runBill() {
    const btn = document.getElementById('btn-run');
    setBusy(btn, true, 'Calculating…');
    try {
        await api('/api/supp/bill/run', { method: 'POST' });
        await refreshBootstrap();
        showToast(`Bill calculated: ${rupees(appState.run.summary.total.bill_value)} (${inr(appState.run.summary.total.bill_lines, 0)} lines)`, 'success');
        renderBillSummary();
        loadBillLines();
    } catch (e) {
        showToast(e.message, 'danger', 6000);
    } finally {
        setBusy(btn, false);
    }
}

async function downloadExcel() {
    const btn = document.getElementById('btn-export');
    setBusy(btn, true, 'Preparing…');
    try {
        const res = await fetch('/api/supp/bill/export');
        if (!res.ok) throw new Error((await res.json()).error || 'Export failed');
        const blob = await res.blob();
        const name = (res.headers.get('content-disposition') || '').match(/filename="([^"]+)"/);
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = name ? name[1] : 'SDEW_Supplementary_Bill.xlsx';
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) {
        showToast(e.message, 'danger');
    } finally {
        setBusy(btn, false);
    }
}

async function downloadPending() {
    const btn = document.getElementById('btn-export-pending');
    setBusy(btn, true, 'Preparing…');
    try {
        const res = await fetch('/api/supp/bill/export-pending');
        if (!res.ok) throw new Error((await res.json()).error || 'Export failed');
        const blob = await res.blob();
        const name = (res.headers.get('content-disposition') || '').match(/filename="([^"]+)"/);
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = name ? name[1] : 'SDEW_GRIN_Pending_List.xlsx';
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) {
        showToast(e.message, 'danger');
    } finally {
        setBusy(btn, false);
    }
}
